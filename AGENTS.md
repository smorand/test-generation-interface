# AGENTS.md

Compact index for AI agents. Details live in `.agent_docs/`. Read this first, then load only the `.agent_docs/*.md` relevant to the task.

## Overview

QA test generator: FastAPI web app that reads a functional specification whole, distils it
into context, scenarios and requirements, then writes the tests of each scenario and closes
the coverage gaps. Coverage is counted against the requirements the document declares, never
scored by a model. A project is a self-contained folder; each execution is a numbered,
disposable version inside it (`v1`, `v2`, ...), never merged with the previous one. Python
3.13, src/ package layout (`src/tgi`).

## Key Commands

```bash
make sync     # install deps (uv)
make run      # run ASGI server (uvicorn tgi.tgi:app, port 8080)
make check    # quality gate: lint, format-check, typecheck (mypy strict), security (bandit), test-cov >=80%
make test-cov # tests + coverage
make build    # build wheel (includes prompts/schemas/templates/static/samples)
make validate # validate a model/endpoint on the bundled sample, prints a verdict
make stats    # pipeline statistics from OTel traces and project state
```

Dev server: `uv run uvicorn tgi.tgi:app --reload --port 8080`.

## Structure

- `src/tgi/tgi.py` : `create_app()` factory, the 18 routes (`GET /`, `GET /parametres`,
  16 `/api/v1/...`), module-level `app`, `main()`
- `src/tgi/config.py` : `Settings` (env_prefix `TGI_`), `settings` singleton, `log_dir`, `config_dir`
- `src/tgi/grammar.py` : infers the numbering the document gives itself, extracts requirements
- `src/tgi/agents/` : `Orchestrator.run(project_id, version, model, llm, text)` drives
  distiller / scenario_generator / coverage, each constructed with the version's own prompt;
  a Phase 3bis then runs `SimilarityJudgeAgent` over the pairs `testset.similar_scenario_pairs`
  prefiltered, marking the numerically higher scenario of a `doublon`/`a_fusionner` pair with
  `merged_into`/`merge_reason` (never destructive, never touches `coverage_report.py`)
- `src/tgi/classification.py` : `classification_of(refs, grammar)`, the shared deterministic
  MOA/MOE/MOA-MOE/INCONNU classification, consumed by `workbook.py` and `qc_export.py`
- `src/tgi/coverage_report.py` : coverage counted, and the requirement traceability matrix
- `src/tgi/deliverable.py` : the two reading axes (scenario tree, requirement rows); unchanged
  by SPEC-0004, still serves the web view
- `src/tgi/progress.py` : run progress, elapsed/remaining, and the SSE payload shape
- `src/tgi/workbook.py` : the recette xlsx; "ALL" right after "Traçabilité" repeats every test
  of every type sheet in one place, then test sheets are one per (requirement type, attachment
  reference) via `onglet_type_name` (`IHM_<écran>`, `<CU>-RM`, `<CU>-EMOE`), plus
  "Jeux de données", "Analyse" and the Synthèse legend/cross-reference. "ID test" is blank past
  a test's first step row like every other metadata column; the per-test shading tracks that
  from the row that starts each block, not from a column value any more.
- `src/tgi/qc_export.py` : the second workbook, one `QC` sheet shaped for ALM's Excel import,
  `Subject` aligned on `onglet_type_name`, `Classification` column via `classification_of`
- `src/tgi/locks.py` : locks keyed by the running event loop
- `src/tgi/build.py` : build identifier shown in the page and on the stylesheet
- `src/tgi/{logging_config,tracing}.py` : rich console plus file logs, OpenTelemetry
- `src/tgi/{stats,validate}.py` : `tgi-stats` from traces, `tgi-validate` verdict on a model
- `src/tgi/events.py` : SSE fan out keyed by `"<project_id>:<version>"`, one queue per connection
- `src/tgi/services/` : `llm` (`build_llm_client(entry)`, per run), `model_store` (models.json
  CRUD), `prompts` (the three shipped defaults), `doc_parser`, `state_manager`, `paths`
- `src/tgi/services/state_manager.py` : disk layout. `projects/<project_id>/project.json` +
  `source/<filename>`; `projects/<project_id>/v<n>/state.json` + `prompts/*.md` +
  `testplan.xlsx` + `qc.xlsx` once produced. No database, no git repo per project.
  `project.json` carries an optional `source_hash` (SHA-256 of the raw uploaded bytes),
  set on creation only (SPEC-0002), never backfilled onto a project created before it
  shipped; `find_by_source_hash` is the dedup lookup `POST /api/v1/projects` runs under a
  per-hash `lock_for` before creating, so a byte-identical re-upload loads the existing
  project instead of creating a duplicate.
- `src/tgi/services/paths.py` : **every identifier received from a client passes through here**
  before it can compose a disk path. `safe_basename` confines an uploaded filename;
  `validated_project_id` / `validated_version` / `validated_test_id` refuse anything else and
  raise `InvalidIdentifier`, which the HTTP layer turns into a 404
- `src/tgi/{prompts,schemas,templates,static}/` : resources (absolute-path resolved, shipped in wheel);
  `schemas/test_schema.json` is the export contract, held true by `tests/test_test_schema.py`;
  `templates/` is `base.html`, `project.html`, `parametres.html`, `partials/progress.html`,
  rendered with the IBM Carbon Design System (CSS + Web Components via CDN, no bundler)
- `tests/`, `tests/functional/` : unit + API tests (LLM mocked, no network)

## Conventions

- Entry point wires routes only; logic in `agents/` and `services/`
- Resources resolved from `Path(__file__)`, never relative to cwd
- Logging uses `%` formatting; never trace prompts/responses/API keys
- LLM calls wrapped in `trace_span("llm.chat" / "api.list_models")`; operation spans
  `project.create`, `version.run`, `version.delete`, `qc.export`, `models.write`; httpx +
  FastAPI auto-instrumented
- The api key of a model table entry is masked (`sk-***<last 4>`) everywhere outside
  `services/model_store.py`: never in a response, a page, an SSE frame, or a trace
- Module-level singletons kept intentionally: `settings`, `state_manager`, `doc_parser`.
  `LLMClient` is no longer one of them: `build_llm_client(entry)` constructs one per run,
  from the model table entry chosen, because the table holds several endpoints
- Runtime data in `projects/` (gitignored); logs/otel under `TGI_LOGS` (default
  `$HOME/.cache/tgi/logs`); the model table under `TGI_CONFIG_DIR` (default
  `$HOME/.config/tgi/models.json`, mode `0600`)
- **No identifier received from a client composes a disk path without `src/tgi/services/paths.py`.**
  The guard is applied twice on purpose: at the HTTP boundary, where the right error body is
  known, and inside `StateManager.project_dir()` / `version_dir()`, where the traffic actually
  passes. A route added later without the first still hits the second.
- A 404 body is identical whether an identifier is malformed or merely absent, so a probe cannot
  tell the two apart. A rejected identifier is logged at `WARNING` by its **shape**, never its
  value: `request.url.path` is the decoded path and would carry the payload into the logs
- There is no validation gate between deposit and generation any more (DEC-002): the
  interface is two gestures, deposit then launch. The safety net is that a version can be
  deleted and the project relaunched, which did not exist before and is exactly SC-005/SC-006

## Pipeline essentials

Four phases, and the order matters. **Deposit creates no version**: a project is just its
source, self-contained, until `POST .../runs` creates `v1` and the pipeline actually reads
the document (FR-NEW-007, FR-NEW-049). **Phase 0 without a model**: `grammar.py` infers the
document's own numbering (51/51 use cases, 401/401 requirements, 0 orphan, where a model
found 46 and fabricated when interrogated). **Phase 1**: the whole document in one call
(78k tokens against 128k) gives context, scenarios and discards, every identifier filtered
against the text; arithmetic then attaches every requirement left behind, so 468 of 468 are
carried, using the three prompts the version was launched with, edited or not
(FR-NEW-048). **Phase 2**: one call per scenario with its requirements and its section,
volume as a target not a cap. **Phase 3**: gaps computed, then closed by completing an
existing test before adding one.

Two hard rules, both measured. **Enumerate, never interrogate**: asked for the rules of one
named use case a model returned 17 references where 1 exists, while asked to list what it
sees it returned 250 with none invented. **Filter every identifier against the document**,
case insensitively; the letter suffix form `RM07a` broke that comparison twice.

There is no judge. Coverage is arithmetic, because a model judging its own chunks reported a
median of 100 percent on a deliverable nobody could review. Result on the reference document: **313 tests instead of 2199**, 1130 steps instead of 7102,
464 of 468 requirements covered with none missing, and **83 LLM calls instead of 382**, 0 percent
wasted.
Full details and the measured numbers: `.agent_docs/pipeline.md` (read it before touching
the distiller, the generator or coverage).

## Quality Gate

Run `make check` before every commit. Coverage must stay >= 80%.

## Documentation Index

- `WINDOWS.md` : install and use on Windows, for someone who never opened a terminal
- `BACKLOG.md` : decided but not built, each item with the measurement that justifies it
- `.agent_docs/pipeline.md` : pipeline scoring, versions, weak model resilience, state concurrency
- `.agent_docs/python.md` : Python coding standards
- `.agent_docs/makefile.md` : Makefile documentation
- `INSTALL.md` : step by step install for a newcomer
- `docs/architecture.html` : architecture and pipeline diagrams (mcp-htmleditor, IBM Carbon template)
- `VALIDATION.md` : runbook to validate a model on a target infrastructure
- `README.md` : human-facing docs, pipeline, scoring, resilience, API routes, schema
