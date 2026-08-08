# Pipeline: scoring, versions, resilience

Details for the bloc pipeline. Read this before touching `agents/orchestrator.py`,
`agents/judge.py` or `services/llm.py`.

## Flow per bloc

1. EXTRACTOR returns business rules.
2. If no rule, the bloc is finished immediately (`done`, `score: None`). No
   generation, no judging: a table of contents or a diagram caption must not burn
   several LLM calls per pass.
3. GENERATOR produces the initial test set.
4. JUDGE loop, up to `TGI_MAX_JUDGE_PASSES`. Each pass is a **scored version**:
   - score `>= TGI_JUDGE_PASS_SCORE` gives `done` and stops the loop,
   - otherwise GENERATOR regenerates, aimed at the uncovered rules
     (`_targeted_gaps` names each one, which is what moves the score).
5. If the threshold is never met, `_best_version` picks the highest score
   (earliest version on a tie, same coverage with fewer tests), the test set is
   restored with `state_manager.replace_tests`, and the bloc becomes
   `needs_human`.

Cost per bloc: 3 LLM calls at best (extract, generate, judge), 7 at worst
(extract, generate, then 3 judge and 2 regenerate). Each judge step costs one
call per rule batch, and each call can itself repeat up to
`TGI_LLM_JSON_RETRIES` times.

## Scoring

`judge_score_mode = "coverage"` (default) computes the score **locally**:
`covered rules / evaluated rules`. The model only reports which rule ids it
considers covered; ids outside the current batch, unknown ids and duplicates are
dropped, so an invented or miscalculated score cannot inflate the result.
`judge_score_mode = "llm"` averages the model's own `score` across batches,
clamped to 0-100, and is less reproducible.

Rule ids are deduplicated in the extractor: duplicates would distort the
denominator.

## Judge batching (TGI_JUDGE_BATCH_RULES, default 10)

Measured on `gemma-4-26b-a4b-it` with a real 4000 character bloc (29 rules):

| Judge input | Outcome |
|---|---|
| 29 rules x 26 tests, one call | truncated on all 5 retries, no verdict, over 15 min |
| 29 rules x 26 tests, batches of 10 | score 97%, 28/29 covered |
| 10 rules x 26 tests, one call | score 90%, 187 s, no truncation |

Batches run sequentially on purpose: blocs are already processed
`TGI_MAX_PARALLEL_BLOCS` at a time, and parallel batches on top of that multiply
concurrent API calls and trigger rate limiting.

A batch that fails after all retries leaves its rules **unevaluated**. They are
excluded from the score denominator, listed in `gaps`, and added to
`uncovered_rules` so the next regeneration targets them. Counting them as
uncovered instead would report a coverage number the judge never measured.

## The judge never raises

`JudgeAgent.evaluate` catches `LLMJSONError` and returns
`{"score": None, "status": "unknown", ...}`. The generated tests are kept and a
human decides. Only extraction and generation failures fail a bloc.

## Weak model resilience (services/llm.py)

Established empirically against `gemma-4-26b-a4b-it`:

- **Output budget is the main trap.** Reasoning models spend thousands of tokens
  thinking. With `max_tokens` too small, `finish_reason == "length"`, `content` is
  empty, and `reasoning_content` holds a thought cut off mid sentence. Measured:
  4096 tokens gave 1 rule and constant parse failures, 16000 tokens gave 29 rules
  and a clean parse on the first attempt. Hence `TGI_MAX_OUTPUT_TOKENS = 16000`
  and no per-agent `max_tokens` override.
- `extract_json` tries candidates **last first** (fenced blocks, then balanced
  `{}` and `[]`), because a model that reasons out loud answers at the end while
  earlier braces are drafts or an echo of the prompt.
- `chat_json(expected_type=..., shape_hint=...)` retries valid JSON of the wrong
  shape, telling the model the exact structure expected.
- A truncated answer is retried with "do not reason, answer immediately", and the
  truncated thought is **not** echoed back (it would eat the budget again).
- Other failures feed the model its own faulty reply for correction.
- Agents tolerate bare arrays, plain strings, and alternative field names
  (`rule`, `text`), and skip entries without a usable description.
- After all retries, `LLMJSONError` (an expected outcome, not a bug) is logged as
  a warning without a traceback, the bloc gets a readable French message and stays
  rerunnable from the UI.

## State concurrency

Blocs run in parallel (`TGI_MAX_PARALLEL_BLOCS`), all writing the same
`state.json`. Two bugs were fixed and are covered by tests:

- `save()` writes to a temp file then `os.replace()` (atomic), so a concurrent
  `load()` never reads a truncated file.
- An `asyncio.Lock` per project serializes every read-modify-write cycle,
  preventing lost updates.

These locks are in-process only. Running several uvicorn workers would need an
inter-process lock (flock) or a real database.

## UI mapping (templates/partials/blocs.html)

| Condition | Badge |
|---|---|
| `done`, score >= pass | green, "Terminé, score X%" |
| `needs_human`, score >= bad | orange, "Revue humaine, score X%" |
| `needs_human`, score < bad | red, "Couverture faible, score X%" |
| `needs_human`, score None | orange, "score non évalué" |
| `done`, no rule | gray, "Aucune règle métier" |
| `error` | red, message plus rerun button |

Thresholds are passed to the template by the `partials/blocs` endpoint. Every
bloc always shows a rerun button.

## Test set hygiene (TGI_MAX_TESTS_PER_RULE, TGI_TEST_SIMILARITY_THRESHOLD)

Regeneration used to append tests forever. Measured on a real 49 rule bloc: 127
then 177 then 270 tests, 40 percent of them sharing a name with another test, one
rule carrying 26 tests, and the score going 63 then 51 then 65. Paying calls for
redundancy, not for coverage.

`tgi.testset.merge_tests` now gates every insertion:

- near duplicates are dropped, comparing normalized name plus description
  (accents, case and punctuation removed) with a difflib ratio above
  `TGI_TEST_SIMILARITY_THRESHOLD`, but only between tests targeting the same rule
  ids: the same check against another rule is legitimate coverage,
- a test is dropped when every rule it targets already carries
  `TGI_MAX_TESTS_PER_RULE` tests,
- a test whose id already exists replaces the previous one, keeping edits
  idempotent.

`saturated_rule_ids` additionally removes saturated rules from the regeneration
brief, so the loop stops buying tests for a rule the judge keeps rejecting. When
every uncovered rule is saturated the judge loop breaks early.

Replayed on the real data: bloc of 39 rules 102 to 87 tests, bloc of 49 rules 270
to 140 tests, maximum tests per rule 26 to 4.

## Document splitting

The parser preserves the document outline and the splitter follows it:

- Word heading styles become markdown headings, matched on a trailing level digit
  so template styles (`Heading 5`, `H3`, `Titre 2`) all work.
- Paragraphs and tables are walked in **document order**. python-docx exposes
  `doc.paragraphs` and `doc.tables` as two flat lists; emitting all tables at the
  end detached specification tables from their heading and produced a single
  144618 character heading-less blob on the reference document.
- Paragraphs styled as hidden comments are skipped: 222 of them on the reference
  document were being fed to the extractor as if they were specification.
- Sections are merged while they fit `TGI_CHUNK_SIZE`; a section larger than that
  is packed by paragraphs with `TGI_CHUNK_OVERLAP`. Overlap applies **only** to
  those forced cuts, never at a heading boundary, because repeating text costs
  duplicate rules.
- A bloc title is its first heading, falling back to its first non table line, so
  an overlap tail never surfaces as the title.

Measured on the reference document, chunk size 4000: real mid sentence cuts fell
from 76 to 51 percent, the largest bloc from 144618 to 4084 characters, and bloc
titles became real section names.

## Reasoning switch (TGI_DISABLE_THINKING)

Reasoning is pure cost here: the pipeline wants JSON, not deliberation. Every call
carries `chat_template_kwargs={"enable_thinking": false}`, the switch documented
for vLLM and SGLang, which is what `Qwen3.6-27B` needs since it thinks by default
and dropped the `/no_think` soft switch.

Gateways that validate parameters reject it with wildly different wording, so
detection keys on the parameter name appearing in the error, not on any phrasing.
Measured rejections: litellm in front of Gemini says "does not support
parameters", ICA in front of Bedrock Claude says "chat_template_kwargs: Extra
inputs are not permitted". On the first rejection the switch is dropped for the
rest of the process and the call is retried immediately.

Known limitation: blocs start in parallel, so up to `TGI_MAX_PARALLEL_BLOCS` first
calls can each pay one rejection before the flag flips. It happens once per
process and is bounded.

Measured on ICA: gemma ignores the switch (it is served through litellm to Gemini
and keeps reasoning), so a reasoning model reached through a gateway that strips
the parameter cannot be sped up from the client side. That is an endpoint
limitation, not an application one.
