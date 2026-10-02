# Python Coding Standards

## Project Structure

```
project-name/
├── src/
│   ├── (NO __init__.py here) # src/ is NOT a package
│   ├── hello.py              # CLI entry point (Typer)
│   ├── api.py                # FastAPI server with OTel
│   ├── config.py             # Settings (pydantic-settings)
│   ├── logging_config.py     # Logging setup (rich + file)
│   ├── tracing.py            # OpenTelemetry tracing (JSONL)
│   ├── models.py             # Pydantic models
│   └── services/             # Business logic
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── testdata/             # Golden files
│   ├── test_*.py
│   └── functional/           # Integration tests
│       └── test_api.py
├── pyproject.toml
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── CLAUDE.md
└── README.md
```

**Rules:**
- `src/`: Source directory (NOT a package, no `__init__.py` at src/ level)
- Entry point: Use project name as module (e.g., `hello.py`, `server.py`). **NEVER `main.py` or generic `cli.py`**
- Tests parallel source structure
- **ALWAYS use src/ layout**

## Coding Conventions

### Naming
- Clear purpose while being concise
- No abbreviations outside standards (id, api, db)
- Boolean: `is_`, `has_`, `should_` prefixes
- Functions: verbs or verb+noun
- Plurals: `users` (list), `user_list` (wrapped), `user_map` (specific)

### Functions
- One function, one responsibility
- If name needs "and"/"or", split it
- Limit conditional/loop depth to 2 levels (use early return)
- Order functions by call order (top-to-bottom)

### Error Handling
- Handle where meaningful response is possible
- Technical details for logs, actionable guidance for users
- Distinguish expected vs unexpected errors
- Use specific exception types, never bare `except`

## File Structure Order

1. Module docstring
2. `from __future__ import annotations`
3. Standard library imports
4. Third-party imports
5. Local imports
6. Module-level constants
7. Type aliases
8. Exception classes
9. Data classes / Pydantic models
10. Protocols / ABCs
11. Implementation classes
12. Module-level functions
13. `if __name__ == "__main__":` block

## Configuration

- Use `pydantic-settings` for all configuration (`config.py`)
- Environment variables with app-specific prefix (e.g., `HELLO_`)
- `.env` files loaded automatically
- Never access `os.environ` directly

## Async-First

- Always prefer async patterns (asyncio, httpx, asyncpg)
- Use `asyncio.TaskGroup` for structured concurrency
- Use `asyncio.Semaphore` for rate limiting
- Wrap sync libs with `asyncio.to_thread()`

## Logging

- Console: `rich` for colored output
- File: `<app_name>.log` for persistent logs
- Use `%` formatting for log messages (lazy evaluation)
- `-v`/`-q` CLI options for verbosity control

## OpenTelemetry (Mandatory)

- Traces to `<app_name>-otel.log` in JSONL format
- Use `trace_span("category.operation")` context manager
- FastAPI: `opentelemetry-instrumentation-fastapi`
- HTTP clients: `opentelemetry-instrumentation-httpx`
- Never trace: LLM prompts/responses, credentials, PII

## Testing

### Unit Tests
- Use `@pytest.mark.parametrize` for table-driven tests
- Use fixtures in `conftest.py` for shared setup
- Mock with `unittest.mock.AsyncMock` for async code
- Run with `make test`

### Integration Tests
- FastAPI: use `httpx.AsyncClient` with `ASGITransport`
- Verify OTel traces are written
- Run with `make test`

### Coverage
- Run with `make test-cov`
- Minimum 80% coverage enforced

## Forbidden Practices

- **Mutable default arguments**: Use `field(default_factory=list)`
- **Bare except**: Always catch specific exceptions
- **Wildcard imports**: Use explicit imports
- **`assert` in production**: Use `raise ValueError()`
- **`print()` for debugging**: Use `logger.debug()`
- **Global mutable state**: Use dependency injection

## Recommended Libraries

| Purpose | Library |
|---------|---------|
| CLI | typer |
| API | fastapi, uvicorn |
| HTTP | httpx, aiohttp |
| Validation | pydantic |
| Config | pydantic-settings |
| Database | asyncpg, aiosqlite |
| Testing | pytest, pytest-asyncio, respx |
| Logging | rich |
| Tracing | opentelemetry-api, opentelemetry-sdk |

## Path containment (SPEC-0001a, 2026-10-02)

Every identifier a client supplies goes through `src/tgi/services/paths.py` before it can
compose a disk path. Two kinds of guard, not interchangeable: `safe_basename` keeps a name
inside a directory by discarding everything before the last separator, while the `validated_*`
functions refuse a value outright. A name is sanitised because the user is entitled to one; an
identifier is refused because a wrong one means nothing.

Things learned the hard way while closing CWE-22 here, each one a test that looked right and
was not:

- **`%2F` proves nothing.** Starlette decodes it before routing, and a segment holding a `/`
  cannot match a `{param}`, so the router answers 404 without any handler running. The test is
  green against code with no validation at all. Use `%2E%2E`, which decodes to `..` and does
  reach the handler. `%5C` crosses as a single segment and is the one to use for a Windows-style
  traversal.
- **A partial decoy proves nothing either.** If `projects/..` holds no readable state, the
  handler fails on its own and answers 404. The decoy has to be something the vulnerable code
  would successfully serve: copy a real `state.json`.
- **Assert the effect before the refusal.** Wrapping a call in `pytest.raises` short-circuits on
  a guard that does not raise, and the fact that matters is the decoy being overwritten. Read it
  back through a different channel than the one attacked: the filesystem for a write, `git
  rev-parse` for a subprocess.
- **Two attacks can cancel each other out.** `validate-map` creates a commit and `rollback`
  undoes it, so chaining them leaves HEAD where it started and both effect assertions pass while
  both attacks succeeded. Measure between the calls.
- **A test can be unable to pass.** `/stream` is an endless SSE response and `ASGITransport`
  buffers the whole body, so driving it with `AsyncClient` times out even on correct code.
  Drive it in raw ASGI and resolve on the first `http.response.start`.
- **Never log the raw value.** `request.url.path` is the decoded path: logging it copies the
  payload into the traces. Log the route template and a shape.
- **Mutate to check a test has teeth.** Three audit rounds each found a guard that could be
  removed with nothing going red. Revert one guard at a time and confirm the specific test fails
  on its effect assertion.
