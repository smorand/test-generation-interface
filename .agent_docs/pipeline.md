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
