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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from tgi.agents.orchestrator import Orchestrator
from tgi.config import Settings, settings
from tgi.coverage_report import coverage_summary, requirement_rows
from tgi.deliverable import build_tree, filter_requirements, filter_scenarios, kind_options, natural_key
from tgi.events import subscribe
from tgi.grammar import references_in
from tgi.logging_config import setup_logging
from tgi.progress import compute_progress
from tgi.services.doc_parser import doc_parser
from tgi.services.git_service import git_service
from tgi.services.llm import llm_client
from tgi.services.state_manager import state_manager
from tgi.tracing import configure_tracing
from tgi.workbook import build_workbook

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Guard rail on the page weight: a test card is about 5 kB of HTML.
_MAX_PER_PAGE = 200
# A volume target beyond this is a mistake, not an intention
_MAX_TESTS_PER_SCENARIO = 20

_MODULE_DIR = Path(__file__).parent
_STATIC_DIR = _MODULE_DIR / "static"
_TEMPLATES_DIR = _MODULE_DIR / "templates"


def _paginate(items: list[Any], page: int, per_page: int) -> tuple[list[Any], dict[str, Any]]:
    """Slice a list and describe the pagination.

    Server side because a test card renders about 5 kB of HTML: two thousand tests
    would be a nine megabyte page.
    """
    per_page = max(1, min(per_page, _MAX_PER_PAGE))
    total = len(items)
    pages = max(1, -(-total // per_page))
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "start": start + 1 if total else 0,
        "end": min(start + per_page, total),
        "has_previous": page > 1,
        "has_next": page < pages,
    }


def _filter_tests(
    tests: list[dict[str, Any]],
    query: str = "",
    requirement: str = "",
    scenario: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    """Server side filter on the flat test list.

    One test card renders about 5 kB of HTML, so browser side filtering is not an option.
    """
    selected = tests
    if requirement:
        wanted = requirement.upper()
        selected = [t for t in selected if wanted in {str(r).upper() for r in t.get("requirement_refs") or []}]
    if scenario:
        selected = [t for t in selected if str(t.get("scenario_id")) == scenario]
    if status:
        selected = [t for t in selected if str(t.get("status")) == status]
    terms = [term for term in query.lower().split() if term]
    if terms:

        def haystack(test: dict[str, Any]) -> str:
            steps = " ".join(
                f"{step.get('description', '')} {step.get('expected_result', '')}" for step in test.get("steps") or []
            )
            return " ".join(
                [
                    str(test.get("id", "")),
                    str(test.get("name", "")),
                    str(test.get("description", "")),
                    " ".join(str(ref) for ref in test.get("requirement_refs") or []),
                    steps,
                ]
            ).lower()

        selected = [t for t in selected if all(term in haystack(t) for term in terms)]
    return selected


def _is_container(state: dict[str, Any], ref: str) -> bool:
    """True when the reference names a use case of the document, per the inferred grammar."""
    return ref in (state.get("containers") or {})


class ConditionalGZipMiddleware:
    """Compress responses, except the SSE stream.

    Measured on a real project: the rules tree is 1.53 MB for 850 rules and gzips to
    69 kB, a factor of 22, because the markup repeats. Compressing the event stream
    instead buffers it, so live progress would arrive in bursts: that path is excluded.
    """

    __slots__ = ("_app", "_gzip")

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        self._app = app
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).endswith("/stream"):
            await self._app(scope, receive, send)
            return
        await self._gzip(scope, receive, send)


def _why_generation_is_refused(state: dict[str, Any]) -> str:
    """Explain, in the words shown to the user, why generation cannot start now.

    Returns an empty string when it can. The three refusals are ordered as the pipeline is:
    the document must have been read, a human must have accepted the map, and a run already
    under way must not be doubled.
    """
    if not state.get("distilled_at"):
        return "La lecture du document n'est pas terminée, la carte est encore vide."
    if not state.get("validated"):
        return "La carte doit être validée avant de générer, c'est là que les corrections sont gratuites."
    scenarios = state.get("scenarios") or []
    if any(scenario.get("status") == "running" for scenario in scenarios):
        return "Une génération est déjà en cours."
    return ""


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
    # Rules a test also covers, to show shared coverage without double counting
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
    application.add_middleware(ConditionalGZipMiddleware)

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
                    "scenario_count": len(state.get("scenarios", [])),
                    "tests_count": sum(len(s.get("tests") or []) for s in state.get("scenarios", [])),
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
                "default_tests_per_scenario": app_settings.tests_per_scenario,
            },
        )

    @application.post("/upload")
    async def upload_doc(
        file: UploadFile = File(...),
        model_generator: str = Form(default=""),
        model_judge: str = Form(default=""),
        tests_per_scenario: int = Form(default=0),
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
            tests_per_scenario=max(1, min(tests_per_scenario, _MAX_TESTS_PER_SCENARIO)) if tests_per_scenario else None,
        )

        # Init git repo
        await git_service.init(project_id, "init: project initialization")

        # Phase one reads the whole document, which takes seconds to a minute: run it in
        # the background so the browser gets its project page immediately.
        task = asyncio.create_task(orchestrator.distil(project_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

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
        """SSE endpoint for live project events.

        Each connection subscribes with its own queue. A single shared queue handed every
        event to whichever client happened to call get() first, so a second tab silently
        stole the completion event from the tab being watched.
        """

        async def event_generator() -> AsyncGenerator[str]:
            with subscribe(project_id) as queue:
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

    @application.post("/projects/{project_id}/validate-map")
    async def validate_map(project_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        await orchestrator.validate_map(project_id)
        return JSONResponse({"status": "ok"})

    @application.post("/projects/{project_id}/redistil")
    async def redistil(project_id: str) -> JSONResponse:
        """Read the document again, for instance after changing the model."""
        await _load_or_404(project_id)
        task = asyncio.create_task(orchestrator.distil(project_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse({"status": "started"})

    @application.post("/projects/{project_id}/run")
    async def run_pipeline(project_id: str) -> JSONResponse:
        state = await _load_or_404(project_id)
        refusal = _why_generation_is_refused(state)
        if refusal:
            # Without this guard, clicking during distillation ran the pipeline over zero
            # scenarios, declared it complete and committed an empty deliverable.
            return JSONResponse({"status": "refused", "reason": refusal}, status_code=409)
        # Fire and forget: pipeline runs in background
        task = asyncio.create_task(orchestrator.run_pipeline(project_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse({"status": "started"})

    @application.post("/projects/{project_id}/scenarios/{scenario_id}/rerun")
    async def rerun_scenario(project_id: str, scenario_id: str) -> JSONResponse:
        await _load_or_404(project_id)
        task = asyncio.create_task(orchestrator.rerun_scenario(project_id, scenario_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse({"status": "started", "scenario_id": scenario_id})

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

    @application.put("/projects/{project_id}/requirements/{ref}")
    async def update_requirement(project_id: str, ref: str, request: Request) -> JSONResponse:
        """Edit a requirement: its wording, or the fact a human has reviewed it."""
        await _load_or_404(project_id)
        body = await request.json()
        updated = await state_manager.update_requirement(project_id, ref, body)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Requirement {ref} not found")
        await git_service.commit(project_id, f"fix(requirement): human edit on {ref}")
        return JSONResponse(updated)

    @application.get("/projects/{project_id}/requirements")
    async def get_requirements(project_id: str) -> JSONResponse:
        state = await _load_or_404(project_id)
        return JSONResponse({"requirements": requirement_rows(state)})

    @application.post("/projects/{project_id}/discards/{index}")
    async def decide_discard(project_id: str, index: int, request: Request) -> JSONResponse:
        """Arbitrate a proposed discard: accepting it takes it out of the corpus of truth."""
        await _load_or_404(project_id)
        body = await request.json()
        decided = await state_manager.decide_discard(project_id, index, str(body.get("decision", "")))
        if not decided:
            raise HTTPException(status_code=404, detail="Discard not found or unknown decision")
        await git_service.commit(project_id, f"decide: discard {index} {decided['decision']}")
        return JSONResponse(decided)

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
            # Artefact 1: the document as markdown, what was actually read
            zf.writestr("1-document.md", state.get("doc_text", ""))

            # Artefact 2: the distilled corpus, the substrate every later phase used
            distilled = {
                "context": state.get("context", ""),
                "axes": state.get("axes", {}),
                "containers": state.get("containers", {}),
                "requirements": state.get("requirements", []),
                "discards": state.get("discards", []),
            }
            zf.writestr("2-distilled.json", json.dumps(distilled, indent=2, ensure_ascii=False))

            # Artefact 3: scenarios and requirements
            zf.writestr(
                "3-scenarios.json",
                json.dumps(state.get("scenarios", []), indent=2, ensure_ascii=False),
            )
            zf.writestr(
                "3-requirements.json",
                json.dumps(requirement_rows(state), indent=2, ensure_ascii=False),
            )

            # Artefact 4: the tests, flat for tooling and as a workbook for review
            all_tests = await state_manager.get_all_tests(project_id)
            zf.writestr("4-tests.json", json.dumps(all_tests, indent=2, ensure_ascii=False))
            zf.writestr("4-tests.xlsx", build_workbook(state))

            zf.writestr("state.json", json.dumps(state, indent=2, ensure_ascii=False))

        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=tests-{project_id[:8]}.zip"},
        )

    # -----------------------------------------------------------------------
    # HTMX partial endpoints
    # -----------------------------------------------------------------------

    @application.get("/projects/{project_id}/partials/map", response_class=HTMLResponse)
    async def partial_map(request: Request, project_id: str) -> HTMLResponse:
        """The distilled document a human validates before any expensive generation."""
        state = await _load_or_404(project_id)
        declared = {ref for ref in references_in(state.get("doc_text", "")) if _is_container(state, ref)}
        mapped = {str(s.get("container")) for s in state.get("scenarios") or [] if s.get("container")}
        return templates.TemplateResponse(
            request,
            "partials/map.html",
            {
                "project_id": project_id,
                "context": state.get("context") or "",
                "axes": state.get("axes") or {},
                "containers": state.get("containers") or {},
                "scenarios": state.get("scenarios") or [],
                "requirements_count": len(state.get("requirements") or []),
                # Reading the document again replaces the scenarios, and the tests hang off
                # them: the count is what makes the warning specific instead of scary.
                "tests_count": sum(
                    len(scenario.get("tests") or [])
                    for scenario in state.get("scenarios") or []
                    if isinstance(scenario, dict)
                ),
                "discards": list(enumerate(state.get("discards") or [])),
                "untitled": sorted(
                    (ref for ref, title in (state.get("containers") or {}).items() if not title), key=natural_key
                ),
                "missing_containers": sorted(declared - mapped, key=natural_key),
                "validated": bool(state.get("validated")),
                "distilled": bool(state.get("distilled_at")),
            },
        )

    @application.get("/projects/{project_id}/partials/scenarios", response_class=HTMLResponse)
    async def partial_scenarios(request: Request, project_id: str, q: str = "", gaps: bool = False) -> HTMLResponse:
        """The scenario axis: functionality, use case, scenario, then its tests on demand."""
        state = await _load_or_404(project_id)
        selected = filter_scenarios([s for s in state.get("scenarios") or [] if isinstance(s, dict)], q, gaps)
        return templates.TemplateResponse(
            request,
            "partials/scenarios.html",
            {
                "project_id": project_id,
                "tree": build_tree({**state, "scenarios": selected}),
                "summary": coverage_summary(state),
                "q": q,
                "gaps": gaps,
            },
        )

    @application.get(
        "/projects/{project_id}/scenarios/{scenario_id}/tests",
        response_class=HTMLResponse,
    )
    async def partial_scenario_tests(request: Request, project_id: str, scenario_id: str) -> HTMLResponse:
        """Tests of one scenario, loaded when the scenario is expanded."""
        state = await _load_or_404(project_id)
        scenario = next((s for s in state.get("scenarios") or [] if str(s.get("id")) == scenario_id), None)
        if scenario is None:
            raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
        statements = {str(r.get("ref")): str(r.get("statement", "")) for r in state.get("requirements") or []}
        return templates.TemplateResponse(
            request,
            "partials/scenario_tests.html",
            {
                "project_id": project_id,
                "scenario": scenario,
                "tests": scenario.get("tests") or [],
                "statements": statements,
            },
        )

    @application.get("/projects/{project_id}/partials/requirements", response_class=HTMLResponse)
    async def partial_requirements(
        request: Request,
        project_id: str,
        q: str = "",
        status: str = "",
        kind: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> HTMLResponse:
        """The requirement axis: the traceability matrix, filtered and paged server side."""
        state = await _load_or_404(project_id)
        rows = requirement_rows(state)
        matching = filter_requirements(rows, q, status, kind)
        page_items, pagination = _paginate(matching, page, per_page)
        return templates.TemplateResponse(
            request,
            "partials/requirements.html",
            {
                "project_id": project_id,
                "rows": page_items,
                "total": len(rows),
                "matching": len(matching),
                "summary": coverage_summary(state),
                "containers": state.get("containers") or {},
                # A requirement the document cites and never states is a finding about the
                # document, not a blank cell to shrug at
                "unstated": sum(1 for row in rows if not row["statement"].strip()),
                "kind_options": kind_options(rows),
                "pagination": pagination,
                "q": q,
                "status": status,
                "kind": kind,
            },
        )

    @application.get("/projects/{project_id}/partials/tests", response_class=HTMLResponse)
    async def partial_tests(
        request: Request,
        project_id: str,
        q: str = "",
        requirement: str = "",
        scenario: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> HTMLResponse:
        """Flat searchable list. Filtered and paginated server side, see _paginate."""
        state = await _load_or_404(project_id)
        all_tests = await state_manager.get_all_tests(project_id)
        matching = _filter_tests(all_tests, q, requirement, scenario, status)
        page_items, pagination = _paginate(matching, page, per_page)
        scenarios = [s for s in state.get("scenarios") or [] if isinstance(s, dict)]
        return templates.TemplateResponse(
            request,
            "partials/tests.html",
            {
                "tests": page_items,
                "project_id": project_id,
                "tests_total": len(all_tests),
                "matching_total": len(matching),
                "scenario_options": [(str(s.get("id")), str(s.get("title", ""))[:70]) for s in scenarios],
                "requirement_options": sorted(
                    {ref for test in all_tests for ref in test.get("requirement_refs") or []}, key=natural_key
                ),
                "pagination": pagination,
                "q": q,
                "requirement": requirement,
                "scenario": scenario,
                "status": status,
            },
        )

    @application.get("/projects/{project_id}/partials/progress", response_class=HTMLResponse)
    async def partial_progress(request: Request, project_id: str) -> HTMLResponse:
        """Where the run stands, visible from every tab."""
        state = await _load_or_404(project_id)
        return templates.TemplateResponse(
            request,
            "partials/progress.html",
            {"progress": compute_progress(state), "project_id": project_id},
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
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

# Module-level ASGI app for uvicorn (tgi.tgi:app)
app = create_app()


def main() -> None:
    """Launch the ASGI server via uvicorn."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run("tgi.tgi:app", host="0.0.0.0", port=8080)  # nosec B104  # bind all interfaces: server runs in a container


if __name__ == "__main__":
    main()
