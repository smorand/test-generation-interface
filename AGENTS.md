# AGENTS.md

Compact index for AI agents. Details live in `.agent_docs/`. Read this first, then load only the `.agent_docs/*.md` relevant to the task.

## Overview

QA test generator: FastAPI + HTMX web app that reads a functional specification whole, distils it
into context, user scenarios and requirements, has a human validate that map, then writes the tests
of each scenario and closes the coverage gaps. Coverage is counted against the requirements the
document declares, never scored by a model. Each project is versioned with local git. Python 3.13,
src/ package layout (`src/tgi`).

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

- `src/tgi/tgi.py` : `create_app()` factory, module-level `app`, `main()`
- `src/tgi/config.py` : `Settings` (env_prefix `TGI_`), `settings` singleton, `log_dir`
- `src/tgi/grammar.py` : infers the numbering the document gives itself, extracts requirements
- `src/tgi/agents/` : orchestrator + distiller / scenario_generator / coverage
- `src/tgi/coverage_report.py` : coverage counted, and the requirement traceability matrix
- `src/tgi/deliverable.py` : the two reading axes (scenario tree, requirement rows)
- `src/tgi/progress.py` : run progress, elapsed and naive remaining estimate
- `src/tgi/workbook.py` : reviewable xlsx (summary, traceability, one sheet per functionality)
- `src/tgi/locks.py` : locks keyed by the running event loop
- `src/tgi/services/` : llm, doc_parser, git_service, state_manager
- `src/tgi/{prompts,schemas,templates,static}/` : resources (absolute-path resolved, shipped in wheel)
- `tests/`, `tests/functional/` : unit + API tests (LLM mocked, no network)

## Conventions

- Entry point wires routes only; logic in `agents/` and `services/`
- Resources resolved from `Path(__file__)`, never relative to cwd
- Logging uses `%` formatting; never trace prompts/responses/API keys
- LLM calls wrapped in `trace_span("llm.chat" / "api.list_models")`; httpx + FastAPI auto-instrumented
- Module-level singletons kept intentionally: `settings`, `llm_client`, `state_manager`, `git_service`, `doc_parser`
- Runtime data in `projects/` (gitignored); logs/otel under `TGI_LOGS` (default `$HOME/.cache/tgi/logs`)

## Pipeline essentials

Four phases, and the order matters. **Phase 0 without a model**: `grammar.py` infers the
document's own numbering (51/51 use cases, 401/401 requirements, 0 orphan, where a model
found 46 and fabricated when interrogated). **Phase 1**: the whole document in one call
(78k tokens against 128k) gives context, scenarios and discards, every identifier filtered
against the text; arithmetic then attaches every requirement left behind, so 468 of 468 are
carried. A human validates that map before anything expensive runs. **Phase 2**: one call
per scenario with its requirements and its section, volume as a target not a cap.
**Phase 3**: gaps computed, then closed by completing an existing test before adding one.

Two hard rules, both measured. **Enumerate, never interrogate**: asked for the rules of one
named use case a model returned 17 references where 1 exists, while asked to list what it
sees it returned 250 with none invented. **Filter every identifier against the document**,
case insensitively; the letter suffix form `RM07a` broke that comparison twice.

There is no judge. Coverage is arithmetic, because a model judging its own chunks reported a
median of 100 percent on a deliverable nobody could review. Result on the reference document:
284 tests instead of 2199, 1029 steps instead of 7102, 463 of 468 requirements covered.
Full details and the measured numbers: `.agent_docs/pipeline.md` (read it before touching
the distiller, the generator or coverage).

## Quality Gate

Run `make check` before every commit. Coverage must stay >= 80%.

## Documentation Index

- `WINDOWS.md` : install and use on Windows, for someone who never opened a terminal
- `BACKLOG.md` : decided but not built, each item with the measurement that justifies it
- `CLAUDE.md` : fuller project overview (mirrors this index)
- `.agent_docs/pipeline.md` : pipeline scoring, versions, weak model resilience, state concurrency
- `.agent_docs/python.md` : Python coding standards
- `.agent_docs/makefile.md` : Makefile documentation
- `INSTALL.md` : step by step install for a newcomer
- `docs/architecture.html` : architecture and pipeline diagrams (mcp-htmleditor, IBM Carbon template)
- `VALIDATION.md` : runbook to validate a model on a target infrastructure
- `README.md` : human-facing docs, pipeline, scoring, resilience, API routes, schema
