# QA Test Generator

A QA agent that reads a functional specification (Word, PDF, text) whole, distils it into the
context, the user scenarios and the requirements that serve test writing, has a human validate
that map, then writes the tests of each scenario and closes the coverage gaps. Coverage is
counted against the requirements the document declares, never scored by a model. FastAPI and
HTMX interface, human in the loop, local git versioning per project.

## Architecture

```
test-generation-interface/
├── src/tgi/
│   ├── tgi.py                 # FastAPI app factory, routes, SSE, tracing
│   ├── config.py              # pydantic-settings configuration
│   ├── grammar.py             # reads the numbering the document gives itself
│   ├── coverage_report.py     # coverage counted, and the traceability matrix
│   ├── deliverable.py         # the two reading axes: scenarios, requirements
│   ├── progress.py            # run progress and remaining estimate
│   ├── workbook.py            # reviewable xlsx export
│   ├── testset.py             # deduplication and similarity
│   ├── locks.py               # locks bound to the loop that runs them
│   ├── events.py              # SSE fan out, one queue per connected browser
│   ├── agents/
│   │   ├── orchestrator.py     # distil, validate, generate, close gaps
│   │   ├── distiller.py        # phase 1: context, scenarios, discards
│   │   ├── scenario_generator.py  # phase 2: the tests of one scenario
│   │   └── coverage.py         # phase 3: close the gaps, editing before adding
│   ├── services/
│   │   ├── llm.py              # OpenAI compatible async client (traced)
│   │   ├── doc_parser.py       # Word/PDF/text parsing
│   │   ├── git_service.py      # async git per project
│   │   └── state_manager.py    # JSON state persistence
│   ├── prompts/               # one per agent
│   ├── templates/             # Jinja2 + HTMX
│   └── schemas/test_schema.json
└── tests/                     # unit + functional, no network
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

- `WINDOWS.md` : install and use on Windows, written for someone who never opened a terminal

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
| `TGI_MODEL_JUDGE` | `gemma-4-26b-a4b-it` | Kept for compatibility, unused since coverage is counted |
| `TGI_MAX_PARALLEL_BLOCS` | `5` | Max scenarios processed in parallel |
| `TGI_TESTS_PER_SCENARIO` | `5` | Target tests per scenario, editable per project |
| `TGI_LLM_JSON_RETRIES` | `5` | Retries when the model returns no usable JSON |
| `TGI_DISABLE_THINKING` | `false` | Send the vLLM/SGLang switch turning reasoning off |
| `TGI_TEST_SIMILARITY_THRESHOLD` | `0.9` | Above this ratio two tests of the same rule are duplicates |
| `TGI_RULE_SIMILARITY_THRESHOLD` | `0.9` | Above this ratio two rules are flagged for review, never merged |
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

Four phases. The document is read whole, the tests are written per scenario, and coverage
is counted rather than judged.

### Phase 0, without a model: read the numbering

A specification numbers its own content, and that numbering is the only trustworthy
skeleton. `grammar.py` infers the levels instead of assuming them: counting prefixes per
position finds the use case level whatever it is called, and each family keeps its own
depth. On the reference document that finds **51 of 51 use cases, 401 of 401 requirements
with no orphan, and 49 of 51 titles**, where a model asked the same question found 46 and
fabricated references as soon as it was interrogated about a named one.

The document also numbers more than one family. The reference specification has four:
functional (`F.EU.CU.RM` or `EM`, 590 references), screens with their messages and
notifications (`E.M`, `E.N`, 205), batch processes (`T`, 103), then free prose. Reading only
the first is what made 404 requirements look like noise.

### Phase 1: distil, then let a human validate

The whole document goes to the model in one call when it fits, which is the usual case: the
reference specification is **78 000 tokens against a 128 000 token window**. Whether it needs
splitting is computed from the reading model's window, not fixed by design.

The model returns the context useful for writing tests, the scenarios, and the list of what
it deliberately dropped: out of scope material, versioning cartridges, prose nobody can
test. Every identifier it emits is checked against the document, because a model asked about
one named use case returned **17 references where the document declares 1**.

Then arithmetic guarantees nothing is lost: a requirement the model did not cite is attached
to the scenario of its own use case, and a use case with requirements and no scenario gets a
derived one. On the reference document the model cited 201 of 468 requirements and 41 of 55
use cases; after completion, **468 of 468**.

A human validates that map before anything expensive runs. Correcting there costs a minute.
The screen states what is computable without a model: use cases the document declares that
no scenario covers, use cases the document never titles, and every proposed discard to
accept or keep. Accepting one takes its references out of the corpus of truth, and it is
recorded, never applied silently.

### Phase 2: generate per scenario

The unit of work is the scenario, not a chunk of characters. Each call receives the context,
the scenario, its requirements with their statements, and its own section of the document.
The volume is a **target, not a cap**: a scenario carrying 35 requirements legitimately needs
more tests than one carrying two.

Requirements that differ only by a value, such as the messages of a screen, become one
parameterised test with its cases as data rows, instead of one test each.

### Phase 3: close the gaps, editing before adding

What is uncovered is computed, never asked. The model is handed the gap and asked to close
it, preferring to complete an existing test over writing a new one, and it says why. It may
declare a requirement untestable in black box rather than fabricate a test for it, and that
claim stays visible: it counts against coverage until a human accepts it as a discard.

### Measured, same document and model as the first version

| Measure | Chunk pipeline | Scenario pipeline |
|---|---|---|
| Tests | 2199 | **313** |
| Steps | 7102 | **1130** |
| Review at 2 min per step | about 34 person-days | about **5** |
| Requirements covered | not measurable | **464 of 468, 99 percent** |
| Uncovered | unknown | **0**, plus 9 declared untestable |
| Scenarios | none | 64: 53 nominal, 9 error, 2 limit |
| Failed units | 0 of 88 blocs | **0 of 64 scenarios**, 1 for human review |
| LLM calls | 382 to 691 | **83**: 1 distiller, 64 generator, 18 coverage |
| Waste | 0 to 1 percent | **0 percent**, 1.00 attempt per success |
| Tests on screen detail | **38 percent** | parameterised into data rows |
| Coverage figure | median 100 percent, and wrong | counted, no model involved |
| Reading cost | 88 calls | **1** |

The first version reported a median score of 100 percent because each chunk scored coverage
of the rules it had invented for itself. It validated a deliverable nobody could review.

### Reading the deliverable

Two axes, because a reviewer needs both.

**Scenarios** answer "what does this test": functionality, use case, scenario, tests, with
the tests fetched when a scenario is expanded.

**Requirements** answer "is anything forgotten": one row per requirement of the document,
its statement, its status (covered, uncovered, untestable, discarded) and the tests that
cover it. This is the traceability matrix, and it is the first sheet a reviewer opens in the
export.

### Export

`GET /projects/{id}/export` returns the four artefacts in reading order:

1. `1-document.md`, the document as it was read
2. `2-distilled.json`, the corpus every later phase used
3. `3-scenarios.json` and `3-requirements.json`
4. `4-tests.json` for tooling, `4-tests.xlsx` for review

The workbook opens on a summary, then the traceability sheet, then one sheet per
functionality with one row per test step, then the discards. Frozen header, autofilter, no
merged cells, since merged cells break sorting.

### Live updates

Events are an optimisation, never the only path to the truth. Each browser subscribes with its
own queue, because a single shared queue handed every event to whichever client called first,
so a second tab stole the completion event and the watched tab spun forever. On top of that,
every fragment restates the server state when it refreshes and carries its own stopping poll,
so a dropped connection costs at most four seconds. Verified with the event stream closed: the
whole run still reported through to 30 of 30, then stopped polling.

Generation is refused server side while the document is being read, while the map is not
validated, and while a run is already going. Hiding the button is not a guard.

### Resilience

`LLMJSONError` is an expected outcome, not a crash: a scenario that produces no usable JSON
is marked for human review and the run continues. A verdict of the wrong shape leaves its
batch unevaluated. Every exception is reported on its scenario, because a swallowed one once
left 58 scenarios stuck at running with no trace.

## Agent Roles

All agents use fresh context, no conversation history.

| Agent | Role | Calls per document |
|---|---|---|
| DISTILLER | Read the whole document: context, scenarios, discards | 1, or one per part |
| SCENARIO GENERATOR | Write the tests of one scenario | one per scenario |
| COVERAGE | Close the remaining gaps, completing before adding | one per scenario with a gap |

There is no judge. Coverage is arithmetic on the requirements the document declares.

## API Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Home page, upload form, recent projects |
| `POST` | `/upload` | Upload a document, create a project, start phase 1 |
| `GET` | `/projects/{id}` | Project UI (tabbed) |
| `GET` | `/projects/{id}/stream` | SSE event stream |
| `POST` | `/projects/{id}/redistil` | Read the document again |
| `POST` | `/projects/{id}/validate-map` | Human accepts the distilled map |
| `POST` | `/projects/{id}/run` | Generate the tests of every scenario |
| `POST` | `/projects/{id}/scenarios/{sid}/rerun` | Replay one scenario |
| `POST` | `/projects/{id}/discards/{index}` | Accept or keep a proposed discard |
| `GET` | `/projects/{id}/tests` | All tests JSON |
| `PUT` | `/projects/{id}/tests/{test_id}` | Edit one test |
| `GET` | `/projects/{id}/requirements` | Traceability matrix JSON |
| `PUT` | `/projects/{id}/requirements/{ref}` | Edit one requirement |
| `POST` | `/projects/{id}/chat` | Ask about the document, read only |
| `GET` | `/projects/{id}/history` | Git log |
| `POST` | `/projects/{id}/rollback` | Roll back to a commit |
| `GET` | `/projects/{id}/export` | Download the four artefacts |
| `GET` | `/projects/{id}/partials/map` | Distilled map fragment |
| `GET` | `/projects/{id}/partials/scenarios` | Scenario tree (`q`, `gaps`) |
| `GET` | `/projects/{id}/scenarios/{sid}/tests` | Tests of one scenario, on expansion |
| `GET` | `/projects/{id}/partials/requirements` | Matrix (`q`, `status`, `kind`, `page`) |
| `GET` | `/projects/{id}/partials/tests` | Test search (`q`, `requirement`, `scenario`, `status`, `page`) |
| `GET` | `/projects/{id}/partials/progress` | Run progress fragment |

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
