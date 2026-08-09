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

## The judge never raises, and that is checked at runtime now

A verdict shaped as a JSON list instead of an object once failed whole blocs with
`'list' object has no attribute 'get'`: two blocs of a 78 bloc run died that way on
2026-08-07, and the error is still stored in that project state, so the UI keeps showing
it. `expected_type=dict` shipped 2 h 50 later and closed the path: the client retries a
wrong shape with a hint, then raises `LLMJSONError`, which `evaluate` already caught.

The annotation `result: dict[str, Any]` on `_judge_batch` is not a runtime check, so
`evaluate` now verifies the shape itself and leaves the batch unevaluated, exactly like a
batch that returned no JSON. A promise this method makes in its docstring should not
depend on another module keeping a keyword argument.

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

### After the extractor rewrite, same document and model

| Measure | Before | After |
|---|---|---|
| Wall clock | 31.5 min | **17 min** (a repeat run reads 15, the gateway caches) |
| Statuses | done 77, needs_human 11, error 0 | done 82, needs_human 6, **error 0** |
| Rules | 1614, 4.3x the 377 declared | **850, 2.25x** |
| Tests | 3799, 2.4 per rule | **2199, 2.6 per rule** |
| Rules with a reference | 0 percent | **68 percent carry one, 52 percent placeable** |
| Coverage | median 93 | **median 100, min 56** |
| Judge passes | 1 pass 64, 2 passes 11, 3 passes 13 | 1 pass 76, 2 passes 3, 3 passes 6 |
| LLM waste | 1 percent | **0 percent of 382 calls** |

Faster because fewer rules means fewer judge batches, and 76 blocs of 88 converged on
the first pass. Three targets were missed and are stated as such: 850 rules against the
600 expected, 2.6 tests per rule against 2.5, and 52 percent placeable references against
70 percent. The extractor still invents references: only **73 percent of the reference
strings it produced exist verbatim in the document**.

### Waste, measured at span level

The same document was re-run with `configure_tracing()` actually called, since a harness
that forgets it measures nothing:

| Role | Calls | Wasted | Attempts per success | Median |
|---|---|---|---|---|
| extractor | 88 | 0 percent | 1.00 | see the caching warning |
| generator | 157 | 0 percent | 1.00 | 23 s |
| judge | 137 | 0 percent | 1.00 | 4 s |
| total | 382 | **0 percent** | 1.00 | |

Every call returned usable JSON on the first attempt, every `finish_reason` was `stop`,
nothing truncated. 87 blocs done, 1 needs_human, 0 error, median score 100, mean 95,
min 75. Judge passes: 78 blocs converged on the first, 5 took two, 2 took three, 6
improved, none regressed.

### The endpoint caches identical prompts, so re-running the same document lies

That traced run finished in 15 min against 17 for the first one, and the extractor showed
a median of 0.3 s per call, which is impossible for a 4000 character chunk. Measured
directly: a fresh chunk takes 3.2 s and 7.1 s, the very same chunk sent again takes
**0.35 s**. The gateway caches identical prompts.

So timings from a repeat run of the same document are worthless, and **17 min is the
honest wall clock**. Quality and waste figures survive: a cached answer is still a valid
answer, and both runs produced exactly 850 rules and 9.7 rules per bloc. When measuring
speed, change the document or accept that the number is a cache benchmark.

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

Without a destination the telemetry is that JSONL file only. It rotates by size like
the application log, which it did not at first: it is the larger of the two, about
460 kB for a single run over a 90 bloc document, so an unbounded file would have
filled the disk of a long lived service. Rotation happens inside the exporter, under a
lock, since the batch processor calls it from its own thread.

## TLS behind a corporate gateway

`TGI_LLM_CA_BUNDLE` verifies against a given bundle, `TGI_LLM_VERIFY_SSL=false` skips
verification entirely. A custom httpx transport is built only when one of them is set,
so the SDK keeps its own defaults in the common case; that transport uses a 600 second
read timeout because a single generation answer can take minutes.

Disabling verification is never silent: it logs a warning naming the endpoint on every
client build, and `tgi-validate` prints `TLS: verification DISABLED` in its verdict.

Verified against a local HTTPS server with a self signed certificate: verification on
fails with APIConnectionError, verification off connects, and passing the certificate
as the bundle connects too.

## One validation must not count the previous ones

`tgi-validate` writes its traces to `TGI_LOGS`, which persists between runs, and the
JSONL file is appended. Aggregating the whole file made every run inherit the spans of
its predecessors: a second validation of a single bloc reported two extractor calls,
and inflated waste rates and medians accordingly. Reported from the target
infrastructure, where a run showed 17 calls for a 7 call workload.

The run now stamps `time.time_ns()` before the pipeline starts and both
`read_attempt_spans` and `reasoning_switch_usage` accept a `since_ns` window. History
stays in the file, which is what `tgi-stats` wants, while a single validation reports
only itself.

## tgi-stats must not stay silent

Reported from the target infrastructure: after successful validations, `tgi-stats`
printed empty tables and "No bloc state found." with no error anywhere. Two defects,
both mine.

It defaulted to a single hardcoded `<app_name>-otel.log`, while each component writes
its own file: the application writes `tgi-otel.log` and a validation writes
`tgi-validate-otel.log`. Traces existed, just not under the name being read. It now
reads **every** `*-otel.log` in the log directory, and `--otel` still pins one file.

And it said nothing about why the tables were empty. It now states whether each file
is missing, empty, or holds no `llm.json_attempt` span, and tells the user to run the
pipeline or a validation. The projects directory is printed resolved, since the default
is relative to the working directory.

## Rule granularity and traceability

The extractor used to atomize every declared rule into its sub conditions. Measured on
the reference specification, which numbers its own rules (F01.EU01.CU02.RM01):

| | Before | After |
|---|---|---|
| Rules declared by the document (RM/EM/CA) | 377 | 377 |
| Rules extracted | 1614 (4.3x) | about 1.6 to 1.7x |
| Rules carrying the document reference | 4 (0%) | 70 to 81% |

Two costs came with the inflation: an unreviewable deliverable, and no way to map a
test back to `F01.EU01.CU02.RM01`, which is exactly what a test plan is reviewed
against. The prompt now asks for one rule per declared identifier, forbids splitting a
numbered rule, and requires that identifier in a `source_ref` field carried through the
generator, the judge and the UI. Measured with claude-haiku-4-5 and
llama-4-maverick-17b, both land at about 1.6x with 70 to 81 percent traced.

## The deliverable has a shape: functionality, use case, rule, tests

A filterable flat list of 1938 tests is not reviewable. `deliverable.py` rebuilds the
tree from `source_ref` only, with no guessing: `_SOURCE_REF_RE` accepts dot joined
`[A-Z]{1,6}\d+` segments, the last segment is the rule label, the one before closes the
use case, the first is the functionality. `VAL01.CU01.RM03` therefore yields
functionality `VAL01`, use case `VAL01.CU01`, label `RM03`.

Load bearing invariants, each covered by a test:

- **Rule identity is the pair (bloc, rule id)**, key `"bloc-3/R1"`. Ids restart at `R1`
  in every bloc, so a global index by rule id would merge unrelated rules. This is the
  single most dangerous mistake in this module.
- **No reference, or a malformed one, means « Hors numérotation »**, sub grouped by bloc.
  Never an exception, never a silent drop. That group carried 100 % of the rules on the
  reference run (extractor before the rewrite) and 1 % after, so it must stay a first
  class chapter.
- **A test citing only unknown rules becomes an orphan** and is displayed. Attaching it
  by guesswork would hide a generation defect.
- **A test covering several rules appears under each**, flagged « couvre aussi ».

`build_deliverable` returns counters at every level (rules, covered, tests, coverage
percent, has_uncovered) so no template has to compute anything.

## HTML weight decides where filtering happens

Measured: one test card renders about **4.8 kB** of HTML (146 tests gave 698 kB). At 1938
tests the tests tab would push past **9 MB**. Browser side filtering is therefore not an
option: `partials/tests` takes `q`, `rule`, `bloc`, `status`, `page`, `per_page` (default
50, capped at `_MAX_PER_PAGE = 200`) and `page` is clamped into range rather than
returning an empty page.

Same reason in the rules tab: the tree renders counters only, and the tests of a rule are
fetched on expansion with `hx-trigger="toggle once"`. That is not enough on its own:
measured 1.8 kB per rule, so **1.53 MB for the 850 rules** of a real run, the editable
fields being what costs. Responses are therefore gzipped, `ConditionalGZipMiddleware`:
1.53 MB becomes **69 kB**, a factor of 22 on repetitive markup, and the tests page 220 kB
becomes 10 kB. The `/stream` path is excluded because gzip buffers a stream and live
progress would arrive in bursts.

## A reference that names no use case is refused

Measured on the 88 bloc run: 577 rules carried a `source_ref`, but only 73 % of those
strings exist verbatim in the document. The rest were stray labels (`T1`, `E1.M2`, `P1`),
and accepting them as positions built **13 fake functionalities** next to the 4 real ones.
`parse_source_ref` now requires a `CU` segment, or three segments as a fallback, and
returns `None` otherwise: 4 chapters, 48 use cases, 404 rules in « Hors numérotation ».

The `CU` convention is an assumption about this family of specifications, stated openly:
without it there is no way to tell `F03.EU01.CU08` (a use case) from `VAL01.CU01.RM03`
(a rule inside a use case). `totals["traced"]` counts only placeable references, so the
header can never claim more traced rules than the tree actually holds. Consequence accepted: expanding 600
rules fires 600 requests, so no « expand everything » button is offered.

## What the chat is allowed to know, and to do

The chat is **read only**. It used to call a planner and announce an execution plan it
could not carry out, and it committed an empty git commit on every message. Both are
gone, `agents/planner.py` and `prompts/planner.md` deleted.

`_chat_context` sends a permanent run summary (statuses, totals, ratio, median, min, max,
judge pass distribution, per bloc line with its error) plus **at most 3 blocs** in full,
excerpt capped at 1500 characters. Bloc selection is deterministic and free, in order:
explicit `bloc-N`, then a rule id or document reference, then word overlap weighted title
x3, rules x2, chunk x1, then the blocs needing attention (error first, then lowest score).
No embeddings: a question sharing no word with the document finds nothing, and the prompt
requires saying so instead of inventing.

Markdown is rendered client side with **HTML escaped first**, then the markup applied, so
a model reply cannot inject anything.

## A tab must show the state at activation

The rules and tests fragments poll every 30 s while their tab is visible. Switching tabs
alone left stale content on screen for up to 30 s, and a Playwright walkthrough read
« 0 règles » on a project that had 71. `refreshTab(tab)` now triggers an htmx load when a
tab becomes active.

## Rules are a first class object in the UI

Rules drive the tests and the score, so they have their own tab: every rule of the
project with its bloc, its document reference, its description, the number of tests
covering it, and a reviewed flag. Description and reference are editable inline and
saved immediately, each edit committed to the project history. A rule with no test is
flagged. Editing is keyed on the pair (bloc, rule): rule ids restart at R1 in every
bloc, so a rule id alone is ambiguous.

The tests tab filters by rule and by free text. A test can legitimately cover several
rules, so the filter matches any of the rules it cites, and each test shows its rules
as chips.

### Two front end traps met while building this

`x-data="testEditor('{{ id }}', {{ test | tojson }})"` was broken from the start: Jinja
`tojson` escapes `'` but not `"`, so the JSON closed the double quoted attribute early
and the whole inline script failed with "missing ) after argument list". Alpine never
initialised on the tests tab, meaning test editing had never worked. The attribute is
now single quoted.

Panel functions live in `project.html`, never in a partial. Alpine initialises the root
of a swapped fragment before the fragment's trailing `<script>` runs, so a function
defined in the partial is undefined exactly when the root needs it. And no Jinja
expression may appear inside that shared script: it renders empty outside its partial
and breaks the whole block. Both were verified by running `node --check` on the
**rendered** page, not on the template.
