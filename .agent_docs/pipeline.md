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

Reasoning is pure cost here: the pipeline wants JSON, not deliberation. When
`TGI_DISABLE_THINKING` is on, every call carries
`chat_template_kwargs={"enable_thinking": false}`, the switch documented for vLLM
and SGLang, which is what `Qwen3.6-27B` needs since it thinks by default and
dropped the `/no_think` soft switch.

The default is **off**: that field is not part of the OpenAI standard, and the
target infrastructure may reject it. Enable it only after validating the endpoint.
`tgi.stats` reports on its first line whether the switch was sent on every call,
never sent, or sent and then dropped after a refusal, which makes that validation a
single command. Both modes were exercised against a litellm gateway: with the switch off the
bloc completed normally, and with it on the first calls were refused, the switch
was dropped, and the bloc still completed.

Gateways that validate parameters reject it with wildly different wording, so
detection keys on the parameter name appearing in the error, not on any phrasing.
Measured rejections: a litellm gateway in front of Gemini says "does not support
parameters", the same gateway in front of Bedrock Claude says "chat_template_kwargs: Extra
inputs are not permitted". On the first rejection the switch is dropped for the
rest of the process and the call is retried immediately.

Known limitation: blocs start in parallel, so up to `TGI_MAX_PARALLEL_BLOCS` first
calls can each pay one rejection before the flag flips. It happens once per
process and is bounded.

Measured behind a litellm gateway: gemma ignores the switch (it is served through litellm to Gemini
and keeps reasoning), so a reasoning model reached through a gateway that strips
the parameter cannot be sped up from the client side. That is an endpoint
limitation, not an application one.

## Reading the answer, not the reasoning

The answer is `content`. Reasoning traces are read for observability only, and the
field name differs per stack: vLLM renamed `reasoning_content` to `reasoning`
(PR 33402), while SGLang and the hosted Qwen API kept `reasoning_content`. A client
reading only one name silently sees nothing on half the stacks, so
`_reasoning_text` checks both.

Falling back to the reasoning text when `content` is empty is kept as a last
resort for gateways that expose no separate answer field, and it is logged as a
warning. It is safe here only because the value must still parse as JSON of the
expected shape, so a chain of thought cannot pass as an answer. vLLM issue 35221
is the cautionary case: a truncated chain of thought was returned as `content`,
which a naive client would have parsed as the result.

Documented Qwen constraints worth remembering if thinking is ever turned back on:
the recommended output budget is 32768 tokens (81920 for hard tasks), so the
16000 default here is below Qwen's own floor for thinking mode, and Qwen advises
against setting a tight `max_tokens` together with structured output because
truncation yields invalid JSON. Measured need here is far lower: median output per
call is 472 tokens for the extractor, 2333 for the generator, 16 for the judge.

## Full scale measurement (reference)

Whole reference specification, 88 blocs, `claude-haiku-4-5`, 5 blocs in parallel:

| Measure | Value |
|---|---|
| Wall clock | 31.5 min, 21 s per bloc |
| Statuses | done 77, needs_human 11, error 0 |
| Coverage | median 93 percent, mean 91, min 62, max 100 |
| Output | 1614 rules, 3799 tests, 2.4 tests per rule |
| LLM calls | 691 total, 1 percent wasted |
| Judge passes | 1 pass 64 blocs, 2 passes 11, 3 passes 13 |
| Best version kept | v1 67, v2 17, v3 4 |
| Multi pass outcome | 19 improved, 1 regressed |

Two things this confirms. The judge loop earns its cost: 24 blocs needed more than
one pass and 19 of them improved. And keeping the best version is not theoretical:
one bloc scored worse on a later pass and its earlier version was restored.

Event queue: with no browser attached the SSE queue saturates. The oldest event is
dropped rather than the newest, so a client connecting later still gets the current
state, and the warning is logged once per project instead of on every event.

## Near identical rules: reported, never merged

The extractor sometimes states the same rule twice, which suggested deduplicating
rules the way tests are deduplicated. Measuring the 112 pairs above ratio 0.9 on the
reference specification showed that would have been a data destroying bug:

| Pair | Ratio | What they actually are |
|---|---|---|
| "est un Banquier Conseil" vs "n'est pas Banquier Conseil et n'est pas CAGE" | 0.907 | a rule and **its own negation** |
| "notification de suppression de relation" vs "notification d'ajout de relation" | 0.901 | opposite actions |
| "le CDC gestionnaire a changé" vs "le manager du CDC gestionnaire a changé" | 0.946 | different subjects |
| "Quand le RRC se connecte" vs "Quand le binôme se connecte" | 0.964 | different actors |
| "Le lien Supprimer ouvre une Lightbox" vs "Le lien Supprimer dans la colonne Action ouvre une Lightbox" | high | genuinely the same rule restated |

Zero pairs were identical after normalization. A functional specification is written
as parametric variants of the same sentence, so the differing fragment is short but
semantically decisive, and similarity cannot tell a restatement from a variant.
Distinguishing them needs semantics, which means another LLM call with its own error
rate, to delete business rules.

`similar_rule_pairs` therefore only reports: the bloc carries a `similar_rules` list
and the UI shows both wordings side by side, stating that nothing was merged. Rules,
scores and generation are untouched. On the reference specification that flags 112
pairs across 42 of 88 blocs, capped at 20 per bloc, closest first.

## Where the traces go

`TGI_LOGS` holds both the application log and the OTel JSONL export; the same
directory is passed to `setup_logging` and to `configure_tracing`.

`TGI_OTEL_DESTINATION` and `TGI_OTEL_API_KEY` used to be declared in the settings and
read nowhere, so the configuration advertised an OTLP endpoint that did nothing. They
now drive a real `BatchSpanProcessor` over OTLP HTTP, added alongside the JSONL
exporter, never replacing it, because `tgi-stats` reads the file. Batched on purpose:
an unreachable collector must not slow the pipeline.

Verified against a local HTTP receiver: spans arrive on `/v1/traces`, the api key is
sent as `Authorization: Bearer ...`, the JSONL file still holds the span, and pointing
the destination at a closed port changes nothing for the caller.
