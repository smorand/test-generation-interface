# Test Generation Interface (tgi)

## Overview

QA agent that turns a functional specification document (Word, PDF, text) into structured functional tests. It reads the document whole, distils it into user scenarios and the requirements the document declares, has a human validate that map, then writes the tests of each scenario and closes the coverage gaps. Coverage is counted, never scored by a model. FastAPI + HTMX interface, human in the loop, local git versioning per project.

Tech stack: Python 3.13, FastAPI, HTMX, OpenAI compatible LLM client, pydantic-settings, Ruff, mypy, pytest, OpenTelemetry.

## Key Commands

```bash
make sync               # Install dependencies
make run                # Run the ASGI server (uvicorn on port 8080)
make check              # Full quality gate (lint, format-check, typecheck, security, tests+coverage)
make docker-build       # Build Docker image
```

Run the server directly for development:

```bash
uv run uvicorn tgi.tgi:app --reload --port 8080
```

## Project Structure

- `src/tgi/tgi.py` : entry point. `create_app()` factory, module-level `app` (ASGI), `main()` for uvicorn
- `src/tgi/validate.py` : model validation deliverable (`tgi-validate`), sample in `src/tgi/samples/`
- `src/tgi/stats.py` : pipeline statistics from OTel traces (`tgi-stats`)
- `src/tgi/config.py` : Settings via pydantic-settings (env_prefix `TGI_`), `settings` singleton, `log_dir`
- `src/tgi/logging_config.py` : rich console + file logging (`setup_logging`)
- `src/tgi/tracing.py` : OpenTelemetry tracing, JSONL export (`configure_tracing`, `trace_span`)
- `src/tgi/agents/orchestrator.py` : pipeline coordinator, `split_document`, SSE queues
- `src/tgi/agents/{distiller,scenario_generator,coverage}.py` : LLM sub-agents (fresh context per call)
- `src/tgi/grammar.py` : infers the document's own numbering, extracts requirements without a model
- `src/tgi/coverage_report.py` : coverage counted, and the requirement traceability matrix
- `src/tgi/locks.py` : locks keyed by the running event loop
- `src/tgi/deliverable.py` : functionality / use case / rule hierarchy built from `source_ref`
- `src/tgi/progress.py` : run progress, elapsed time, naive remaining estimate
- `src/tgi/workbook.py` : xlsx export (one sheet per functionality, one row per test step)
- `src/tgi/services/llm.py` : async OpenAI compatible client with JSON extraction, retry, tracing
- `src/tgi/services/doc_parser.py` : Word/PDF/text parsing
- `src/tgi/services/git_service.py` : async git per project (asyncio.Lock)
- `src/tgi/services/state_manager.py` : JSON state persistence
- `src/tgi/{prompts,schemas,templates,static}/` : non-python resources (shipped in the wheel)
- `tests/` : unit tests; `tests/functional/` : API tests (ASGI, mocked LLM)

## Conventions

- Entry point `src/tgi/tgi.py` holds route wiring only; business logic lives in `agents/` and `services/`
- Non-python resources are resolved with absolute paths from `__file__`, never relative to cwd
- Logging with `%` formatting, not f-strings
- OTel traces to `<app>-otel.log`, app logs to `<app>.log`, both under `TGI_LOGS` (default `$HOME/.cache/tgi/logs`)
- Never trace prompts, responses, or API keys
- Module-level singletons kept from the original design: `settings`, `llm_client`, `state_manager`, `git_service`, `doc_parser` (pre-existing pattern, no new mutable globals)

## Pipeline behaviour

- There is no judge. Coverage is counted in `coverage_report.py`: a requirement is covered when a
  test cites it, so no model scores its own work.
- The document is read in one call when it fits the reading model's window, and split on its own
  outline when it does not. Every part that answers stands on its own.
- A human validates the map (scenarios, requirements, proposed discards) before anything expensive
  runs. Nothing is discarded silently.
- Weak model handling: JSON is recovered from prose or fences (last candidate first), wrong shapes
  and truncated answers are retried with targeted instructions, and `LLMJSONError` marks the
  scenario `error` with a readable message plus a rerun button. Reasoning models need a large
  `TGI_MAX_OUTPUT_TOKENS` or they are cut off before answering.

## Quality Gate

Run `make check` before every commit. It runs: lint, format-check, typecheck (mypy strict), security (bandit), test-cov (>= 80% coverage).

## Auto-Evaluation Checklist

Before considering any task complete:
- [ ] `make check` passes
- [ ] No sync blocking calls in async code
- [ ] All external calls traced with OpenTelemetry
- [ ] No forbidden practices (bare except, print, mutable defaults, .format(), assert)
- [ ] Config via Settings class, not os.environ
- [ ] Test coverage >= 80%

## Coding Standards

This project follows the `python` skill. Reload it for full coding standards reference.

## Documentation Index

- `WINDOWS.md` : install and use on Windows, for a non technical reader
- `BACKLOG.md` : decided but not built, with the measurement behind each item
- `.agent_docs/python.md` : Python coding standards and conventions
- `.agent_docs/makefile.md` : Detailed Makefile documentation
