# AGENTS.md

Compact index for AI agents. Details live in `.agent_docs/`. Read this first, then load only the `.agent_docs/*.md` relevant to the task.

## Overview

QA test generator: FastAPI + HTMX web app that splits a spec document into blocs, extracts business rules, generates JSON functional tests via LLM sub-agents, iterates with a scoring judge, and versions each project with local git. Python 3.13, src/ package layout (`src/tgi`).

## Key Commands

```bash
make sync     # install deps (uv)
make run      # run ASGI server (uvicorn tgi.tgi:app, port 8080)
make check    # quality gate: lint, format-check, typecheck (mypy strict), security (bandit), test-cov >=80%
make test-cov # tests + coverage
make build    # build wheel (includes prompts/schemas/templates/static)
```

Dev server: `uv run uvicorn tgi.tgi:app --reload --port 8080`.

## Structure

- `src/tgi/tgi.py` : `create_app()` factory, module-level `app`, `main()`
- `src/tgi/config.py` : `Settings` (env_prefix `TGI_`), `settings` singleton, `log_dir`
- `src/tgi/logging_config.py`, `src/tgi/tracing.py` : logging + OpenTelemetry
- `src/tgi/agents/` : orchestrator + extractor/generator/judge/planner
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

Judge scores rule coverage (0 to 100, computed locally). Each pass is a scored
version; the best one wins. Tests are deduplicated and capped per rule, and the
splitter follows the document outline (tables read in document order). Weak models need a large `TGI_MAX_OUTPUT_TOKENS` or
they are truncated before answering. `LLMJSONError` is an expected outcome: warn,
never `logger.exception`. Full details and the measured numbers:
`.agent_docs/pipeline.md` (read it before touching orchestrator, judge, or llm).

## Quality Gate

Run `make check` before every commit. Coverage must stay >= 80%.

## Documentation Index

- `CLAUDE.md` : fuller project overview (mirrors this index)
- `.agent_docs/pipeline.md` : pipeline scoring, versions, weak model resilience, state concurrency
- `.agent_docs/python.md` : Python coding standards
- `.agent_docs/makefile.md` : Makefile documentation
- `README.md` : human-facing docs, pipeline, scoring, resilience, API routes, schema
