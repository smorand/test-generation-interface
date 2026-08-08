"""FastAPI application factory: routes, SSE, tracing, and dependency wiring."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from tgi.agents.orchestrator import Orchestrator, get_event_queue
from tgi.config import Settings, settings
from tgi.logging_config import setup_logging
from tgi.services.doc_parser import doc_parser
from tgi.services.git_service import git_service
from tgi.services.llm import llm_client
from tgi.services.state_manager import state_manager
from tgi.testset import rule_ids_of
from tgi.tracing import configure_tracing

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).parent
_STATIC_DIR = _MODULE_DIR / "static"
_TEMPLATES_DIR = _MODULE_DIR / "templates"


def _tests_per_rule(tests: list[dict[str, Any]]) -> dict[str, int]:
    """How many tests cover each rule, keyed by "bloc_id/rule_id".

    A test can legitimately cover several rules, so it counts once per rule it cites.
    """
    counts: dict[str, int] = {}
    for test in tests:
        bloc_id = str(test.get("bloc_id", ""))
        for rule_id in rule_ids_of(test):
            key = f"{bloc_id}/{rule_id}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _rule_filter_options(tests: list[dict[str, Any]]) -> list[str]:
    """Rule ids that actually appear in the tests, for the filter dropdown."""
    seen: set[str] = set()
    for test in tests:
        seen.update(rule_ids_of(test))
    return sorted(seen, key=lambda rid: (len(rid), rid))


def create_app(app_settings: Settings | None = None) -> FastAPI:  # noqa: PLR0915
    """Create and configure the FastAPI application with OTel instrumentation."""
    app_settings = app_settings or settings

    log_dir = app_settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(app_name=app_settings.app_name, log_dir=log_dir)
    provider = configure_tracing(
        app_name=app_settings.app_name,
        log_dir=log_dir,
        destination=app_settings.otel_destination,
        api_key=app_settings.otel_api_key,
    )

    # Ensure projects dir exists
    for problem in app_settings.configuration_problems():
        logger.warning("Configuration: %s", problem)

    Path(app_settings.projects_dir).mkdir(parents=True, exist_ok=True)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    # A test can cite several rules: the template needs them as a list
    templates.env.filters["rule_ids"] = lambda value: sorted(rule_ids_of({"business_rule": value or ""}))
    orchestrator = Orchestrator(state_manager, git_service, llm_client)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        """Startup checks (non-fatal on network errors)."""
        try:
            ok_gen, ctx_gen = await llm_client.check_context_window(
                app_settings.model_generator, app_settings.max_context_tokens
            )
            if not ok_gen and ctx_gen > 0:
                logger.warning(
                    "Generator model %s has context window %s < required %s",
                    app_settings.model_generator,
                    ctx_gen,
                    app_settings.max_context_tokens,
                )
            logger.info(
                "Generator model: %s (context window: %s)",
                app_settings.model_generator,
                ctx_gen if ctx_gen > 0 else "unknown",
            )
        except Exception as exc:
            logger.warning("Startup context check skipped: %s", exc)
        yield
        provider.shutdown()

    application = FastAPI(title="Test Generation Interface", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _raise_404(project_id: str) -> None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    async def _load_or_404(project_id: str) -> dict[str, Any]:
        try:
            return await state_manager.load(project_id)
        except FileNotFoundError:
            _raise_404(project_id)
        raise AssertionError("unreachable")

    # -----------------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------------

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        projects = await state_manager.list_projects()
        project_list = []
        for pid in projects:
            try:
                state = await state_manager.load(pid)
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            project_list.append(
                {
                    "id": pid,
                    "doc_path": state.get("doc_path", ""),
                    "created_at": state.get("created_at", ""),
                    "bloc_count": len(state.get("blocs", [])),
                }
            )
        return templates.TemplateResponse(
            request,
            "base.html",
            {
                "projects": project_list,
                "page": "home",
                "default_model_generator": app_settings.model_generator,
                "default_model_judge": app_settings.model_judge,
            },
        )

    @application.post("/upload")
    async def upload_doc(
        file: UploadFile = File(...),
        model_generator: str = Form(default=""),
        model_judge: str = Form(default=""),
    ) -> JSONResponse:
        model_gen = model_generator or app_settings.model_generator
        model_jdg = model_judge or app_settings.model_judge

        # Save uploaded file
        upload_dir = Path(app_settings.projects_dir) / "_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / (file.filename or "upload.txt")

        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        # Parse document
        try:
            doc_text = doc_parser.parse(file_path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to parse document: {exc}") from exc

        if not doc_text.strip():
            raise HTTPException(status_code=422, detail="Document appears to be empty")

        # Create project
        project_id = await state_manager.create(
            doc_path=str(file_path),
            doc_text=doc_text,
            model_generator=model_gen,
            model_judge=model_jdg,
        )

        # Init git repo
        await git_service.init(project_id, "init: project initialization")

        # Propose bloc split
        await orchestrator.split_and_propose(project_id)

        return JSONResponse({"project_id": project_id, "redirect": f"/projects/{project_id}"})

    @application.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_view(request: Request, project_id: str) -> HTMLResponse:
        state = await _load_or_404(project_id)
        return templates.TemplateResponse(
            request,
            "project.html",
            {"state": state, "project_id": project_id},
        )

    @application.get("/projects/{project_id}/stream")
    async def project_stream(project_id: str) -> StreamingResponse:
        """SSE endpoint for live project events."""
        queue = get_event_queue(project_id)

        async def event_generator() -> AsyncGenerator[str]:
            # Send initial connected event
            yield "data: " + json.dumps({"type": "connected", "data": {}}) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield "data: " + json.dumps(event) + "\n\n"
                except TimeoutError:
                    # Keep-alive ping
                    yield ": ping\n\n"
                except asyncio.CancelledError:
                    break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.post("/projects/{project_id}/validate-split")
    async def validate_split(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        await orchestrator.validate_split(project_id)
        return JSONResponse({"status": "ok"})

    @application.post("/projects/{project_id}/run")
    async def run_pipeline(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        # Fire and forget: pipeline runs in background
        task = asyncio.create_task(orchestrator.run_pipeline(project_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse({"status": "started"})

    @application.post("/projects/{project_id}/blocs/{bloc_id}/rerun")
    async def rerun_bloc(project_id: str, bloc_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        task = asyncio.create_task(orchestrator.rerun_bloc(project_id, bloc_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse({"status": "started", "bloc_id": bloc_id})

    @application.get("/projects/{project_id}/tests")
    async def get_tests(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        tests = await state_manager.get_all_tests(project_id)
        return JSONResponse({"tests": tests})

    @application.put("/projects/{project_id}/tests/{test_id}")
    async def update_test(project_id: str, test_id: str, request: Request) -> JSONResponse:
        await _load_or_404(project_id)
        body = await request.json()
        updated = await state_manager.update_test(project_id, test_id, body)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
        await git_service.commit(project_id, f"fix(test): human edit on {test_id}")
        return JSONResponse(updated)

    @application.put("/projects/{project_id}/blocs/{bloc_id}/rules/{rule_id}")
    async def update_rule(project_id: str, bloc_id: str, rule_id: str, request: Request) -> JSONResponse:
        """Edit a rule: wording, document reference, or reviewed flag."""
        await _load_or_404(project_id)
        body = await request.json()
        updated = await state_manager.update_rule(project_id, bloc_id, rule_id, body)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found in {bloc_id}")
        await git_service.commit(project_id, f"fix(rule): human edit on {bloc_id}/{rule_id}")
        return JSONResponse(updated)

    @application.get("/projects/{project_id}/rules")
    async def get_rules(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        return JSONResponse({"rules": await state_manager.get_all_rules(project_id)})

    @application.post("/projects/{project_id}/chat")
    async def chat(project_id: str, request: Request) -> JSONResponse:
        state = await _load_or_404(project_id)
        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="message is required")

        model = state.get("model_generator", app_settings.model_generator)
        response = await orchestrator.handle_chat(project_id, message, model)
        return JSONResponse({"response": response})

    @application.get("/projects/{project_id}/history")
    async def get_history(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        log = await git_service.log(project_id)
        return JSONResponse({"commits": log})

    @application.post("/projects/{project_id}/rollback")
    async def rollback(project_id: str, request: Request) -> JSONResponse:
        await _load_or_404(project_id)
        body = await request.json()
        commit_hash = body.get("hash", "").strip()
        if not commit_hash:
            raise HTTPException(status_code=422, detail="hash is required")

        ok = await git_service.rollback(project_id, commit_hash)
        if not ok:
            raise HTTPException(status_code=500, detail="Rollback failed")

        # Reload state after rollback
        state = await state_manager.load(project_id)
        return JSONResponse({"status": "ok", "state": state})

    @application.get("/projects/{project_id}/export")
    async def export_project(project_id: str) -> StreamingResponse:
        state = await _load_or_404(project_id)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write global state
            zf.writestr("state.json", json.dumps(state, indent=2, ensure_ascii=False))

            # Write per-bloc test files
            for bloc in state.get("blocs", []):
                bloc_tests = bloc.get("tests", [])
                if bloc_tests:
                    bloc_file = json.dumps(bloc_tests, indent=2, ensure_ascii=False)
                    zf.writestr(f"tests/{bloc['id']}.json", bloc_file)

            # Write all tests in one file
            all_tests = await state_manager.get_all_tests(project_id)
            zf.writestr("tests/all_tests.json", json.dumps(all_tests, indent=2, ensure_ascii=False))

        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=tests-{project_id[:8]}.zip"},
        )

    # -----------------------------------------------------------------------
    # HTMX partial endpoints
    # -----------------------------------------------------------------------

    @application.get("/projects/{project_id}/partials/blocs", response_class=HTMLResponse)
    async def partial_blocs(request: Request, project_id: str) -> HTMLResponse:
        state = await _load_or_404(project_id)
        return templates.TemplateResponse(
            request,
            "partials/blocs.html",
            {
                "blocs": state["blocs"],
                "project_id": project_id,
                "pass_score": app_settings.judge_pass_score,
                "bad_score": app_settings.judge_bad_score,
            },
        )

    @application.get("/projects/{project_id}/partials/tests", response_class=HTMLResponse)
    async def partial_tests(request: Request, project_id: str) -> HTMLResponse:
        await _load_or_404(project_id)
        all_tests = await state_manager.get_all_tests(project_id)
        all_rules = await state_manager.get_all_rules(project_id)
        return templates.TemplateResponse(
            request,
            "partials/tests.html",
            {
                "tests": all_tests,
                "project_id": project_id,
                "rules_count": len(all_rules),
                "rule_options": _rule_filter_options(all_tests),
            },
        )

    @application.get("/projects/{project_id}/partials/rules", response_class=HTMLResponse)
    async def partial_rules(request: Request, project_id: str) -> HTMLResponse:
        """Rules of the whole project, reviewable and editable."""
        await _load_or_404(project_id)
        all_rules = await state_manager.get_all_rules(project_id)
        all_tests = await state_manager.get_all_tests(project_id)
        tests_per_rule = _tests_per_rule(all_tests)
        return templates.TemplateResponse(
            request,
            "partials/rules.html",
            {
                "rules": all_rules,
                "project_id": project_id,
                "tests_per_rule": tests_per_rule,
                "tests_count": len(all_tests),
                "reviewed_count": sum(1 for r in all_rules if r.get("reviewed")),
                "traced_count": sum(1 for r in all_rules if r.get("source_ref")),
            },
        )

    @application.get("/projects/{project_id}/partials/history", response_class=HTMLResponse)
    async def partial_history(request: Request, project_id: str) -> HTMLResponse:
        await _load_or_404(project_id)
        commits = await git_service.log(project_id)
        return templates.TemplateResponse(
            request,
            "partials/history.html",
            {"commits": commits, "project_id": project_id},
        )

    FastAPIInstrumentor.instrument_app(application)
    HTTPXClientInstrumentor().instrument()

    return application


# Keep strong references to fire-and-forget tasks so they are not garbage collected.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()

# Module-level ASGI app for uvicorn (tgi.tgi:app)
app = create_app()


def main() -> None:
    """Launch the ASGI server via uvicorn."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run("tgi.tgi:app", host="0.0.0.0", port=8080)  # nosec B104  # bind all interfaces: server runs in a container


if __name__ == "__main__":
    main()
