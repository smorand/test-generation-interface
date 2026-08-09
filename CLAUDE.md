# Test Generation Interface (tgi)

## Overview

QA agent that turns a functional specification document (Word, PDF, text) into structured functional tests. It splits the doc into business blocs, extracts rules, generates JSON tests via LLM sub-agents, iterates with a judge that scores rule coverage, and exposes everything in a FastAPI + HTMX web interface with human-in-the-loop and local git versioning per project.

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
- `src/tgi/agents/{extractor,generator,judge}.py` : LLM sub-agents (fresh context per call)
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

- Judge scores rule coverage 0 to 100, computed locally from rule ids (never trusted from the model).
  `>= TGI_JUDGE_PASS_SCORE` accepts the bloc, below `TGI_JUDGE_BAD_SCORE` flags poor coverage.
- Each judge pass is a scored version; if the threshold is never met the best scoring version is
  restored and the bloc goes to `needs_human`. Every pass stays in the git history.
- A bloc with no extracted rule is finished immediately, without generation or judging.
- Weak model handling: JSON is recovered from prose or fences (last candidate first), wrong shapes
  and truncated answers are retried with targeted instructions, and `LLMJSONError` marks the bloc
  `error` with a readable message plus a rerun button. Reasoning models need a large
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

- `.agent_docs/python.md` : Python coding standards and conventions
- `.agent_docs/makefile.md` : Detailed Makefile documentation
