# QA Test Generator

A QA agent that takes a functional specification document (Word/PDF/text), splits it into business blocks, generates structured functional tests (JSON) per block via LLM sub-agents, iterates with an independent judge, and exposes everything in a FastAPI + HTMX web interface with human-in-the-loop and local git versioning.

## Architecture

```
test-generation-interface/
├── src/tgi/
│   ├── tgi.py                 # FastAPI app factory, routes, SSE, tracing
│   ├── config.py              # pydantic-settings configuration
│   ├── logging_config.py      # rich console + file logging
│   ├── tracing.py             # OpenTelemetry tracing (JSONL export)
│   ├── agents/
│   │   ├── orchestrator.py     # Main pipeline coordinator
│   │   ├── extractor.py        # Business rule extraction
│   │   ├── generator.py        # Test JSON generation
│   │   ├── judge.py            # Coverage validation
│   ├── deliverable.py         # Functionality / use case / rule hierarchy
│   ├── progress.py            # Run progress and remaining time estimate
│   ├── workbook.py            # Reviewable xlsx workbook (openpyxl)
│   ├── testset.py             # Test deduplication, rule ids, similarity
│   ├── services/
│   │   ├── llm.py              # OpenAI compatible async client (traced)
│   │   ├── doc_parser.py       # Word/PDF/text parsing
│   │   ├── git_service.py      # Async git with asyncio.Lock
│   │   └── state_manager.py    # JSON state persistence
│   ├── prompts/               # System prompts for each agent role
│   ├── templates/             # Jinja2 + HTMX templates
│   ├── static/style.css       # Minimal utility CSS
│   └── schemas/test_schema.json  # JSON Schema for test validation
└── tests/                     # Unit + functional tests
```

## Setup

```bash
# Copy environment config
cp .env.example .env
# Edit .env: set TGI_LLM_BASE_URL and TGI_LLM_API_KEY

# Install with uv
make sync

# Run (uvicorn on port 8080)
make run
# or, for development with reload:
uv run uvicorn tgi.tgi:app --reload --port 8080
```

Open `http://localhost:8080`.

## Documentation

- [INSTALL.md](INSTALL.md) : step by step first install, written for a newcomer
- [docs/architecture.html](docs/architecture.html) : architecture and pipeline diagrams, open in a browser
- [VALIDATION.md](VALIDATION.md) : validate a model on a target infrastructure

## Validating a model on another infrastructure

```bash
tgi-validate --model Qwen/Qwen3.6-27B     # installed from the wheel
make validate ARGS="--model ..."          # from the repository
tgi-stats                                 # statistics of a real run
```

`tgi-validate` runs the real pipeline on a synthetic specification shipped in the
package, so no customer document is needed, and prints a go / no go verdict with
the settings to change. Exit code 0 means usable. Step by step runbook:
[VALIDATION.md](VALIDATION.md).

## Configuration (.env)

All variables use the `TGI_` prefix.

| Variable | Default | Description |
|---|---|---|
| `TGI_LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI compatible endpoint |
| `TGI_LLM_API_KEY` | — | Bearer token, any non empty value if the server needs none |
| `TGI_LLM_VERIFY_SSL` | `true` | Set to `false` to skip TLS verification (exposes the traffic) |
| `TGI_LLM_CA_BUNDLE` | — | Certificate bundle to verify against, the clean fix behind a TLS gateway |
| `TGI_MODEL_GENERATOR` | `gemma-4-26b-a4b-it` | LLM for extraction + generation |
| `TGI_MODEL_JUDGE` | `gemma-4-26b-a4b-it` | LLM for coverage evaluation |
| `TGI_MAX_JUDGE_PASSES` | `3` | Max judge/generator iterations per bloc |
| `TGI_MAX_PARALLEL_BLOCS` | `5` | Max blocs processed in parallel |
| `TGI_LLM_JSON_RETRIES` | `5` | Retries when the model returns no usable JSON |
| `TGI_DISABLE_THINKING` | `false` | Send the vLLM/SGLang switch turning reasoning off |
| `TGI_JUDGE_SCORE_MODE` | `coverage` | `coverage` (computed locally) or `llm` (self-reported) |
| `TGI_JUDGE_PASS_SCORE` | `80` | Score at or above which a bloc is accepted (green) |
| `TGI_JUDGE_BAD_SCORE` | `40` | Score below which coverage is flagged as poor (red) |
| `TGI_JUDGE_BATCH_RULES` | `10` | Rules judged per LLM call (`0` disables batching) |
| `TGI_GENERATOR_BATCH_RULES` | `8` | Rules per generation call (`0` disables batching) |
| `TGI_MAX_TESTS_PER_RULE` | `4` | Cap on tests kept per rule (`0` disables the cap) |
| `TGI_TEST_SIMILARITY_THRESHOLD` | `0.9` | Above this ratio two tests of the same rule are duplicates |
| `TGI_RULE_SIMILARITY_THRESHOLD` | `0.9` | Above this ratio two rules are flagged for review, never merged |
| `TGI_CHUNK_SIZE` | `4000` | Characters per bloc when splitting |
| `TGI_CHUNK_OVERLAP` | `200` | Overlap, applied only when a section must be cut |
| `TGI_MAX_CONTEXT_TOKENS` | `128000` | Minimum required context window |
| `TGI_MAX_OUTPUT_TOKENS` | `16000` | Output budget per call, must fit a reasoning model's thinking |
| `TGI_PROJECTS_DIR` | `./projects` | Where projects are stored |
| `TGI_LOGS` | `$HOME/.cache/tgi/logs`, `%LOCALAPPDATA%\tgi\logs` on Windows | Log + OTel output directory |
| `TGI_OTEL_DESTINATION` | — | OTLP endpoint (overrides local JSONL export) |
| `TGI_OTEL_API_KEY` | — | Bearer token for the OTLP endpoint |

## Logs

`TGI_LOGS` holds **both** files, UTF-8, each rotated at 10 MB with 5 backups kept:

- `tgi.log`, one plain text line per event: `2026-08-08 16:18:27,519 [WARNING] tgi.agents.orchestrator orchestrator._emit: ...`
- `tgi-otel.log`, one JSON object per line (JSONL), one per span, directly parseable

Neither contains prompts, model responses or credentials. A full 88 bloc run
produced 224 kB and 460 kB respectively. `tgi-stats` reads the JSONL file to report
per role latency and waste.

Set `TGI_OTEL_DESTINATION` to an OTLP HTTP traces endpoint to **also** ship spans to
a collector, with `TGI_OTEL_API_KEY` as its bearer token. The export is batched, so an
unreachable collector never slows a request, and the local JSONL file is always
written since that is what `tgi-stats` reads.

```
TGI_LOGS=/var/log/tgi
TGI_OTEL_DESTINATION=http://collector:4318/v1/traces
TGI_OTEL_API_KEY=token
```

On Windows use the same commands through `uv run`, from the project directory: see
[VALIDATION.md](VALIDATION.md#6-running-on-windows).

## Pipeline

```
Upload doc
    → Parse (Word/PDF/text)
    → Split into blocs
    → [HUMAN CHECKPOINT] validate split
    → For each bloc (max TGI_MAX_PARALLEL_BLOCS in parallel):
        EXTRACTOR → business rules (JSON)
        if no rule → done, nothing to test (no further LLM call)
        GENERATOR → functional tests (JSON)
        JUDGE loop (max TGI_MAX_JUDGE_PASSES passes), each pass is a scored version:
            JUDGE scores rule coverage (0 to 100)
            if score >= TGI_JUDGE_PASS_SCORE → done
            else → GENERATOR regenerates, targeting the uncovered rules
        if threshold never reached → keep the BEST scoring version → needs_human
    → Human can edit tests, chat, rerun a bloc, rollback
    → Export ZIP
```

### Reading the deliverable

A flat list of two thousand tests cannot be reviewed. The **Règles & tests** tab
follows the numbering of the specification itself:

```
F01 Synchronisation des relations        24 règles · 22 couvertes (92 %) · 47 tests
  F01.EU01.CU02 Supprimer les relations   6 règles · 6 couvertes · 13 tests
    RM01 Le système supprime la relation…  3 tests
       TEST-014  Suppression d'un GAC puis contrôle   [couvre aussi RM02]
```

- The hierarchy comes from `source_ref`. The use case is the prefix up to the last `CU`
  segment, so `F01.EU01.CU02.RM01` gives functionality `F01`, use case `F01.EU01.CU02`,
  rule `RM01`, and `F03.EU01.CU08`, which names a use case and no rule, is not split into
  a fake `CU08` rule.
- A reference naming no use case is refused rather than guessed: on a real run, accepting
  stray labels like `T1` or `E1.M2` built **13 fake functionalities**; refusing them left
  the 4 the specification actually has. Those rules go to **Hors numérotation**, grouped
  by bloc, keeping their reference visible. That group is a real chapter, not a bin: it
  held 404 of 850 rules on the reference run.
- The bloc is provenance only. It never becomes a level of the tree.
- A rule identity is the pair (bloc, rule id), because ids restart at `R1` in every bloc.
  `R1` of `bloc-3` is never confused with `R1` of `bloc-4`.
- A test covering several rules appears under each, flagged **couvre aussi**, so it is
  not counted twice by a reader.
- A test citing only rules that do not exist in its bloc goes to **Tests non rattachés**:
  a quality signal, shown rather than silently dropped.
- A rule with no test is flagged at every level of aggregation.

Tests are fetched when a rule is expanded (`GET /projects/{id}/blocs/{b}/rules/{r}/tests`),
so the tree carries counters only. It still weighs about 1.8 kB per rule, 1.53 MB for the
850 rules of a real run, which is why responses are gzipped: 69 kB on the wire, a factor
of 22, since the markup repeats. The event stream is excluded, gzip would buffer it.
Filters run on the server: text, uncovered only,
unreviewed only. Description, reference and the reviewed flag stay editable in place.

The **Recherche** tab remains the search and single test editing view, with server side
filtering and pagination (`q`, `rule`, `bloc`, `status`, `page`, `per_page`). This is not
a preference: one test card renders about 4.8 kB of HTML, so 1938 tests would send more
than 9 MB to the browser.

### Progress

The sticky control bar shows a bar segmented by outcome (done, needs review, error,
running), so a run going wrong is visible immediately, from any tab. The remaining time
is a naive estimate, `elapsed / processed × remaining`, shown only once a first bloc has
finished. `run_started_at` is written to the state when the pipeline starts.

### Export

`GET /projects/{id}/export` returns a ZIP with the JSON for tooling plus `tests.xlsx`
for review: a **Synthèse** sheet (rules, covered, coverage, tests per use case), then one
sheet per functionality plus `Hors numérotation` and `Tests non rattachés` when they are
not empty. One row per test step, frozen header, autofilter, no merged cells, since
merged cells break sorting and filtering.

### Chat

The chat answers, it never writes. It receives a permanent run summary (statuses, totals,
ratio, median, min and max score, judge passes, per bloc detail with errors, coverage per
use case), plus at most 3 blocs in full for the question asked, with their rules, their
references and a document excerpt capped at 1500 characters.

Bloc selection is deterministic and costs no extra LLM call: an explicit `bloc-N` wins,
then a rule id or a document reference, then word overlap weighted title x3, rules x2,
chunk x1; with no signal at all, the blocs needing attention (error, then lowest score).
Answers are rendered as markdown client side, escaping HTML first so a model reply cannot
inject anything.

### Scoring

The judge maps each rule id to the tests covering it. The score is computed
**locally** as `covered rules / evaluated rules`, so a score the model invents or
miscalculates cannot inflate the result. Unknown or duplicated ids are ignored.

Rules are judged in batches of `TGI_JUDGE_BATCH_RULES`, because asking a small
reasoning model about dozens of rules at once makes it spend its whole output
budget thinking and return nothing. A batch that still fails leaves its rules
**unevaluated**: they are excluded from the score denominator, reported in the
gaps, and targeted on the next regeneration, rather than silently counted as
uncovered.

Every judge pass is kept as a scored version. When the threshold is never
reached, the highest scoring version wins (earliest one on a tie, since it
reaches the same coverage with fewer tests), and the test set is restored to
that version. Full test sets of every pass remain in the git history.

| Outcome | Status | UI |
|---|---|---|
| score >= `TGI_JUDGE_PASS_SCORE` | `done` | green, score shown |
| `TGI_JUDGE_BAD_SCORE` <= score < pass | `needs_human` | orange, score shown |
| score < `TGI_JUDGE_BAD_SCORE` | `needs_human` | red, score shown |
| judge produced no verdict | `needs_human` | orange, "score non évalué" |
| no business rule in the bloc | `done` | gray, "Aucune règle métier" |
| extraction or generation failed | `error` | red, rerunnable |

### Resilience to weak models

Small or reasoning models often fail to return clean JSON. The client handles it
without failing the bloc:

- JSON is extracted even when wrapped in prose or markdown fences, trying the
  **last** candidate first, since a model that thinks out loud answers last.
- A valid JSON of the wrong shape (array instead of object) is retried with an
  explicit description of the expected structure.
- On failure the model's own faulty reply is fed back for correction.
- A reply cut off by the output budget is detected via `finish_reason` and
  retried with an instruction to answer directly instead of reasoning.
- Agents tolerate bare arrays, plain strings and missing fields, and rule ids
  are deduplicated so the coverage score stays honest.
- After `TGI_LLM_JSON_RETRIES` attempts the bloc is marked `error` with a
  readable message and a rerun button, logged as a warning without a traceback.

> A reasoning model needs a large `TGI_MAX_OUTPUT_TOKENS`: it spends thousands of
> tokens thinking before answering. With a budget that is too small it is cut off
> mid thought and returns no JSON at all.

### Reasoning models

Hybrid models think before answering, which this pipeline never wants: reasoning
burns the output budget and leaves no JSON. `TGI_DISABLE_THINKING` sends the
documented vLLM and SGLang switch `chat_template_kwargs.enable_thinking=false` on
every call.

It is **off by default**, because that field is not part of the OpenAI standard and
some gateways reject it. Turn it on once the target endpoint is known to accept it,
then confirm on the wire with `uv run python -m tgi.stats`, whose first line reports
whether the switch was sent on every call, never sent, or sent then dropped after a
refusal. Endpoints that validate parameters and refuse it (a litellm gateway in front
of Bedrock answers `chat_template_kwargs: Extra inputs are not permitted`) are
detected on the first call, and the switch is then dropped for the rest of the
process.

Known behaviour of `Qwen3.6-27B`, the intended production model:

- thinking is **on by default**, and the Qwen3 `/no_think` soft switch was removed
  in 3.6, so the chat template flag is the only way to turn it off
- reported reasoning cost ranges from about 3.5k to 39k output tokens per answer
- serve it with `--reasoning-parser qwen3`; to keep structured output while
  reasoning stays on, vLLM also needs
  `--structured-outputs-config.enable_in_reasoning=True`
- the hosted Qwen API does not support structured output in thinking mode

Sources: the Qwen3.6-27B model card and the vLLM structured output and reasoning
documentation.

### Measured behaviour (gemma-4-26b-a4b-it, real 4000 character spec bloc)

| Step | Result | Duration |
|---|---|---|
| Extraction, 4096 token budget | 1 rule, constant parse failures | slow, useless |
| Extraction, 16000 token budget | 29 rules, parsed first try | about 3 min |
| Generation | 15 to 17 tests | about 3 min |
| Judge, 29 rules in one call | no verdict, truncated on all 5 retries | over 15 min |
| Judge, batches of 10 rules | score 97%, 28/29 covered | about 3 min per batch |

Count 3 LLM calls per bloc at best and 7 at worst, plus one call per judge batch,
so a large document is a long run. Reduce `TGI_MAX_JUDGE_PASSES`, or use a
non-reasoning model, if wall clock time matters more than coverage.

## Agent Roles

All agents use **fresh context** (no conversation history). Context is reconstructed from `state.json` on each call.

| Agent | Model | Role |
|---|---|---|
| EXTRACTOR | generator | Extract explicit + implicit business rules from a text chunk |
| GENERATOR | generator | Generate functional tests covering all rules |
| JUDGE | judge | Find gaps and missing coverage (never validates if in doubt) |

## API Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Home page, upload form, recent projects |
| `POST` | `/upload` | Upload doc, create project |
| `GET` | `/projects/{id}` | Project UI (tabbed) |
| `GET` | `/projects/{id}/stream` | SSE event stream |
| `POST` | `/projects/{id}/validate-split` | Human validates bloc split |
| `POST` | `/projects/{id}/run` | Start pipeline |
| `POST` | `/projects/{id}/blocs/{bloc_id}/rerun` | Rerun one bloc |
| `GET` | `/projects/{id}/tests` | All tests JSON |
| `PUT` | `/projects/{id}/tests/{test_id}` | Update one test |
| `GET` | `/projects/{id}/rules` | All rules JSON |
| `PUT` | `/projects/{id}/blocs/{b}/rules/{r}` | Update one rule (description, reference, reviewed) |
| `GET` | `/projects/{id}/partials/rules` | Deliverable tree (`q`, `uncovered`, `unreviewed`) |
| `GET` | `/projects/{id}/blocs/{b}/rules/{r}/tests` | Tests of one rule, loaded on expansion |
| `GET` | `/projects/{id}/partials/tests` | Tests page (`q`, `rule`, `bloc`, `status`, `page`, `per_page`) |
| `GET` | `/projects/{id}/partials/progress` | Run progress fragment |
| `POST` | `/projects/{id}/chat` | Chat with QA agent |
| `GET` | `/projects/{id}/history` | Git log |
| `POST` | `/projects/{id}/rollback` | Rollback to commit hash |
| `GET` | `/projects/{id}/export` | Download ZIP |

## Git Commit Convention

```
init:           project initialization
feat(doc):      document uploaded and parsed
feat(blocs):    block split validated by human
feat(bloc-X):   business rules extracted
feat(bloc-X):   tests generated v1
feat(bloc-X):   judge iteration pass N
fix(bloc-X):    human modification via chat
feat(bloc-X):   human validation
export:         final JSON export
```

## Test JSON Schema

```json
{
  "id": "TEST-001",
  "bloc_id": "bloc-1",
  "business_rule": "Un utilisateur non authentifié...",
  "name": "Accès refusé sans authentification",
  "description": "Vérifie que...",
  "steps": [
    { "order": 1, "description": "...", "expected_result": "..." }
  ],
  "status": "draft",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z"
}
```

## Error Handling

| Situation | Behavior |
|---|---|
| Model context < 128k | Startup error, explicit message |
| Malformed JSON from LLM | Retry 3x with correction prompt |
| Judge loop exhausted | `needs_human` status on bloc |
| LLM timeout | Retry 2x, then `error` status |
| Git rollback | Full state reload |
| Chat out of scope | Agent refuses and explains |
