"""FastAPI application factory: the 18 routes of the lean interface.

Two pages (the work, the parameters), a project is a self-contained folder, a version is
a numbered execution inside it. See AGENTS.md and specs/SPEC-0001b for the contract.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import tempfile
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote

import aiofiles
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel

from tgi.agents.orchestrator import Orchestrator, run_lock
from tgi.build import build_id
from tgi.config import Settings, settings
from tgi.coverage_report import coverage_summary
from tgi.events import subscribe
from tgi.locks import lock_for
from tgi.logging_config import setup_logging
from tgi.progress import sse_progress_payload
from tgi.qc_export import build_qc_workbook
from tgi.services import model_store
from tgi.services.doc_parser import doc_parser
from tgi.services.llm import build_llm_client
from tgi.services.paths import (
    InvalidIdentifier,
    safe_basename,
    validated_project_id,
    validated_version,
)
from tgi.services.prompts import default_prompts, is_known_prompt_key
from tgi.services.state_manager import (
    QC_FILENAME,
    WORKBOOK_FILENAME,
    ProjectCorrupted,
    StateManager,
    VersionCorrupted,
)
from tgi.tracing import configure_tracing, trace_span

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# An unauthenticated service that writes an unbounded file is a disk saturation. 50 MiB
# leaves a factor of seven over the reference specification document.
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_ALLOWED_EXTENSIONS = {".md", ".txt", ".docx", ".pdf"}
_MEDIA_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ASCII_MAX_CODEPOINT = 128

_MODULE_DIR = Path(__file__).parent
_STATIC_DIR = _MODULE_DIR / "static"
_TEMPLATES_DIR = _MODULE_DIR / "templates"

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _route_template(request: Request) -> str:
    """The route's pattern, not the concrete path: request.url.path carries the payload."""
    return str(getattr(request.scope.get("route"), "path", "<unmatched>"))


def _identifier_shape(raw: str) -> str:
    """Describe a rejected identifier without echoing it (7.5: never log the value)."""
    classes = {"a" if c.isalpha() else "9" if c.isdigit() else "." if c == "." else "-" for c in raw}
    return f"len={len(raw)} classes={''.join(sorted(classes))}"


def _valid_project_id(request: Request, project_id: str) -> str:
    """Refuse a project id at the boundary, before it can compose a path (FR-NEW-040)."""
    try:
        return validated_project_id(project_id)
    except InvalidIdentifier:
        logger.warning(
            "rejected project identifier on %s (%s)", _route_template(request), _identifier_shape(project_id)
        )
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}") from None


def _valid_version(request: Request, version: str) -> str:
    try:
        return validated_version(version)
    except InvalidIdentifier:
        logger.warning("rejected version identifier on %s (%s)", _route_template(request), _identifier_shape(version))
        raise HTTPException(status_code=404, detail=f"version inconnue: {version}") from None


ValidProjectId = Annotated[str, Depends(_valid_project_id)]
ValidVersion = Annotated[str, Depends(_valid_version)]


def _ascii_fallback(filename: str) -> str:
    """NFKD then strip anything non ASCII: the repli of FR-NEW-003 and FR-NEW-008."""
    decomposed = unicodedata.normalize("NFKD", filename)
    stripped = "".join(c for c in decomposed if ord(c) < _ASCII_MAX_CODEPOINT)
    return stripped or "document"


def _content_disposition(filename: str) -> str:
    """RFC 5987 for the real name, an ASCII repli for clients that only read filename=."""
    return f"attachment; filename=\"{_ascii_fallback(filename)}\"; filename*=UTF-8''{quote(filename)}"


def _media_type_for(filename: str) -> str:
    return _MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


class ConditionalGZipMiddleware:
    """Compress responses, except the SSE stream, which must arrive as it is produced."""

    __slots__ = ("_app", "_gzip")

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        self._app = app
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).endswith("/events"):
            await self._app(scope, receive, send)
            return
        await self._gzip(scope, receive, send)


def _sse_frame(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _ensure_document_readable(content: bytes, ext: str) -> None:
    """Confirm the document parses before anything is written to disk (FR-NEW-059)."""
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        await asyncio.to_thread(doc_parser.parse, tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="document illisible") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


def _validate_upload(filename: str, content: bytes) -> str:
    """The ordered refusals of FR-NEW-059, up to the point a write is attempted."""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"format non supporté: {ext}")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="document trop volumineux (max 50 Mo)")
    if not content:
        raise HTTPException(status_code=400, detail="document vide")
    return ext


class RunCreate(BaseModel):
    model: str
    prompts: dict[str, str] = {}


class ModelCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str


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

    Path(app_settings.projects_dir).mkdir(parents=True, exist_ok=True)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["build"] = build_id()

    manager = StateManager()
    orchestrator = Orchestrator(manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        """Mark any version left running by a previous process as failed (FR-NEW-053)."""
        base = Path(app_settings.projects_dir)
        if base.exists():
            for project_dir in base.iterdir():
                if not project_dir.is_dir():
                    continue
                for version_dir in project_dir.glob("v[1-9]*"):
                    state_path = version_dir / "state.json"
                    try:
                        raw = await asyncio.to_thread(state_path.read_text, "utf-8")
                        state = json.loads(raw)
                    except (OSError, ValueError):
                        continue
                    if state.get("status") == "running":
                        state["status"] = "failed"
                        state["error"] = "exécution interrompue par un redémarrage"
                        await asyncio.to_thread(
                            state_path.write_text, json.dumps(state, indent=2, ensure_ascii=False), "utf-8"
                        )
        yield
        provider.shutdown()

    application = FastAPI(title="Test Generation Interface", lifespan=lifespan)
    application.add_middleware(ConditionalGZipMiddleware)
    application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _load_project_or_404(project_id: str) -> dict[str, Any]:
        try:
            return await manager.load_project(project_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}") from None
        except ProjectCorrupted:
            raise HTTPException(status_code=409, detail=f"projet corrompu: {project_id}") from None

    async def _load_version_or_404(project_id: str, version: str) -> dict[str, Any]:
        try:
            return await manager.load_version(project_id, version)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"version inconnue: {version}") from None
        except VersionCorrupted:
            raise HTTPException(status_code=409, detail=f"version corrompue: {version}") from None

    # -----------------------------------------------------------------------
    # Pages
    # -----------------------------------------------------------------------

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request, project: str = "", version: str = "", duplicate: str = "") -> HTMLResponse:
        selected_project: dict[str, Any] | None = None
        selected_version_state: dict[str, Any] | None = None
        pid = ""

        if version and not project:
            return HTMLResponse("<html><body>projet inconnu: </body></html>", status_code=404)

        if project:
            try:
                pid = validated_project_id(project)
                selected_project = await manager.load_project(pid)
            except (InvalidIdentifier, FileNotFoundError, ProjectCorrupted):
                return HTMLResponse(f"<html><body>projet inconnu: {project}</body></html>", status_code=404)

            if version:
                try:
                    vid = validated_version(version)
                    selected_version_state = await manager.load_version(pid, vid)
                except (InvalidIdentifier, FileNotFoundError, VersionCorrupted):
                    return HTMLResponse(f"<html><body>version inconnue: {version}</body></html>", status_code=404)

        projects = await manager.list_projects()
        models, models_warning = await model_store.read_models(app_settings.config_dir)
        versions = await manager.list_versions(pid) if selected_project else []
        prompts = default_prompts() if selected_project else {}

        return templates.TemplateResponse(
            request,
            "project.html",
            {
                "projects": projects,
                "models": models,
                "models_warning": models_warning,
                "project": selected_project,
                "versions": versions,
                "version_state": selected_version_state,
                "prompts": prompts,
                "tests_per_scenario": app_settings.tests_per_scenario,
                "duplicate": duplicate == "true",
            },
        )

    @application.get("/parametres", response_class=HTMLResponse)
    async def parametres(request: Request) -> HTMLResponse:
        models, warning = await model_store.read_models(app_settings.config_dir)
        return templates.TemplateResponse(
            request,
            "parametres.html",
            {"models": [model_store.masked(m) for m in models], "warning": warning},
        )

    # -----------------------------------------------------------------------
    # Projects
    # -----------------------------------------------------------------------

    @application.get("/api/v1/projects")
    async def list_projects() -> JSONResponse:
        return JSONResponse({"projects": await manager.list_projects()})

    @application.post("/api/v1/projects", status_code=201)
    async def create_project(file: UploadFile = File(...)) -> JSONResponse:
        filename = file.filename or "document"
        content = await file.read()
        _validate_upload(filename, content)
        ext = Path(filename).suffix.lower()
        await _ensure_document_readable(content, ext)
        safe_name = safe_basename(filename)
        source_hash = hashlib.sha256(content).hexdigest()

        async with lock_for(f"source-hash:{source_hash}"):
            existing = await manager.find_by_source_hash(source_hash)
            if existing is not None:
                return JSONResponse(
                    status_code=200,
                    content={
                        "id": existing["id"],
                        "name": existing["name"],
                        "source_filename": existing["source_filename"],
                        "created_at": existing["created_at"],
                        "duplicate": True,
                    },
                )

            try:
                with trace_span("project.create", {}):
                    project = await manager.create_project(safe_name, content, source_hash=source_hash)
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise HTTPException(status_code=507, detail="disque plein, projet non créé") from exc
                raise

        return JSONResponse(
            status_code=201,
            content={
                "id": project["id"],
                "name": project["name"],
                "source_filename": project["source_filename"],
                "created_at": project["created_at"],
                "duplicate": False,
            },
        )

    @application.get("/api/v1/projects/{project_id}/source")
    async def get_source(project_id: ValidProjectId) -> Response:
        project = await _load_project_or_404(project_id)
        path = manager.existing_source(project_id, project)
        if path is None:
            raise HTTPException(status_code=404, detail="source absente")
        content = await asyncio.to_thread(path.read_bytes)
        filename = str(project["source_filename"])
        return Response(
            content=content,
            media_type=_media_type_for(filename),
            headers={"content-disposition": _content_disposition(filename)},
        )

    @application.post("/api/v1/projects/{project_id}/source", status_code=201)
    async def add_source(project_id: ValidProjectId, file: UploadFile = File(...)) -> JSONResponse:
        project = await _load_project_or_404(project_id)
        if manager.existing_source(project_id, project) is not None:
            raise HTTPException(status_code=409, detail="le projet a déjà une source")

        filename = file.filename or "document"
        content = await file.read()
        _validate_upload(filename, content)
        ext = Path(filename).suffix.lower()
        await _ensure_document_readable(content, ext)
        safe_name = safe_basename(filename)

        await manager.add_source(project_id, safe_name, content)
        updated = await manager.load_project(project_id)
        return JSONResponse(
            status_code=201,
            content={
                "id": updated["id"],
                "name": updated["name"],
                "source_filename": updated["source_filename"],
                "created_at": updated["created_at"],
            },
        )

    @application.get("/api/v1/projects/{project_id}/prompts")
    async def get_prompts(project_id: ValidProjectId) -> JSONResponse:
        await _load_project_or_404(project_id)
        return JSONResponse(default_prompts())

    # -----------------------------------------------------------------------
    # Runs and versions
    # -----------------------------------------------------------------------

    @application.post("/api/v1/projects/{project_id}/runs", status_code=202)
    async def create_run(project_id: ValidProjectId, body: RunCreate) -> JSONResponse:
        project = await _load_project_or_404(project_id)

        models, _ = await model_store.read_models(app_settings.config_dir)
        if not models:
            raise HTTPException(status_code=409, detail="aucun modèle configuré")
        chosen = next((m for m in models if m.get("name") == body.model), None)
        if chosen is None:
            raise HTTPException(status_code=422, detail=f"modèle inconnu: {body.model}")

        prompts = default_prompts()
        for key, value in (body.prompts or {}).items():
            if not is_known_prompt_key(key):
                raise HTTPException(status_code=422, detail=f"prompt inconnu: {key}")
            if not value.strip():
                raise HTTPException(status_code=422, detail=f"prompt vide: {key}")
            prompts[key] = value

        source_path = manager.existing_source(project_id, project)
        if source_path is None:
            raise HTTPException(status_code=404, detail="source absente")

        lock = run_lock(project_id)
        if lock.locked():
            raise HTTPException(status_code=409, detail="génération déjà en cours")
        await lock.acquire()
        try:
            version = await manager.create_version(project_id, chosen["name"], prompts)
        except Exception:
            lock.release()
            raise

        with trace_span("version.run", {"project_id": project_id, "version": version}):
            pass

        text = await asyncio.to_thread(doc_parser.parse, source_path)
        llm = build_llm_client(chosen)
        model_name = str(chosen["model"])

        async def _background() -> None:
            try:
                await orchestrator.run(project_id, version, model_name, llm, text)
            finally:
                lock.release()

        task = asyncio.create_task(_background())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        return JSONResponse(status_code=202, content={"version": version})

    @application.get("/api/v1/projects/{project_id}/versions")
    async def list_versions(project_id: ValidProjectId) -> JSONResponse:
        await _load_project_or_404(project_id)
        return JSONResponse({"versions": await manager.list_versions(project_id)})

    @application.get("/api/v1/projects/{project_id}/versions/{version}")
    async def get_version(project_id: ValidProjectId, version: ValidVersion) -> JSONResponse:
        await _load_project_or_404(project_id)
        state = await _load_version_or_404(project_id, version)
        prompts = await manager.read_prompts(project_id, version)
        return JSONResponse(
            {
                "id": state.get("id", version),
                "status": state.get("status"),
                "model": state.get("model"),
                "created_at": state.get("created_at"),
                "error": state.get("error"),
                "prompts": prompts,
            }
        )

    @application.get("/api/v1/projects/{project_id}/versions/{version}/events")
    async def version_events(project_id: ValidProjectId, version: ValidVersion) -> StreamingResponse:
        await _load_project_or_404(project_id)
        state = await _load_version_or_404(project_id, version)

        async def event_generator() -> AsyncGenerator[str]:
            status = state.get("status")
            yield _sse_frame("progress", sse_progress_payload(version, state))
            if status == "done":
                yield _sse_frame("done", {"version": version, "tests": coverage_summary(state)["tests"]})
                return
            if status == "failed":
                yield _sse_frame("error", {"version": version, "error": state.get("error") or ""})
                return

            with subscribe(f"{project_id}:{version}") as queue:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    except asyncio.CancelledError:
                        break
                    yield _sse_frame(str(event["type"]), dict(event["data"]))
                    if event["type"] in {"done", "error"}:
                        break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.get("/api/v1/projects/{project_id}/versions/{version}/xlsx")
    async def download_xlsx(project_id: ValidProjectId, version: ValidVersion) -> Response:
        project = await _load_project_or_404(project_id)
        state = await _load_version_or_404(project_id, version)
        if state.get("status") == "running":
            raise HTTPException(status_code=409, detail="génération en cours")
        if state.get("status") == "failed":
            raise HTTPException(status_code=409, detail="version en échec")
        path = manager.version_dir(project_id, version) / WORKBOOK_FILENAME
        content = await asyncio.to_thread(path.read_bytes)
        filename = f"{project.get('name', project_id)}_{version}.xlsx"
        return Response(
            content=content,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": _content_disposition(filename)},
        )

    @application.post("/api/v1/projects/{project_id}/versions/{version}/qc", status_code=201)
    async def create_qc(project_id: ValidProjectId, version: ValidVersion) -> JSONResponse:
        await _load_project_or_404(project_id)
        state = await _load_version_or_404(project_id, version)
        if state.get("status") == "running":
            raise HTTPException(status_code=409, detail="génération en cours")
        if state.get("status") == "failed":
            raise HTTPException(status_code=409, detail="version en échec")
        tests_count = sum(len(s.get("tests") or []) for s in state.get("scenarios") or [])
        if tests_count == 0:
            raise HTTPException(status_code=409, detail="aucun test à exporter")

        with trace_span("qc.export", {"project_id": project_id, "version": version}):
            content, warnings = build_qc_workbook(state)
            path = manager.version_dir(project_id, version) / QC_FILENAME
            async with aiofiles.open(path, "wb") as f:
                await f.write(content)

        return JSONResponse(status_code=201, content={"path": f"{version}/qc.xlsx", "warnings": warnings})

    @application.get("/api/v1/projects/{project_id}/versions/{version}/qc.xlsx")
    async def download_qc(project_id: ValidProjectId, version: ValidVersion) -> Response:
        await _load_project_or_404(project_id)
        await _load_version_or_404(project_id, version)
        path = manager.version_dir(project_id, version) / QC_FILENAME
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"export QC absent: {version}")
        content = await asyncio.to_thread(path.read_bytes)
        return Response(content=content, media_type=_XLSX_MEDIA_TYPE)

    @application.delete("/api/v1/projects/{project_id}/versions/{version}", status_code=204)
    async def delete_version(project_id: ValidProjectId, version: ValidVersion) -> Response:
        await _load_project_or_404(project_id)
        try:
            state = await manager.load_version(project_id, version)
            status = state.get("status")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"version inconnue: {version}") from None
        except VersionCorrupted:
            status = "corrompue"

        if status == "running":
            raise HTTPException(status_code=409, detail="version en cours d'exécution")

        with trace_span("version.delete", {"project_id": project_id, "version": version}):
            try:
                await manager.delete_version(project_id, version)
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"version inconnue: {version}") from None

        return Response(status_code=204)

    # -----------------------------------------------------------------------
    # Models
    # -----------------------------------------------------------------------

    @application.get("/api/v1/models")
    async def list_models_route() -> JSONResponse:
        models, warning = await model_store.read_models(app_settings.config_dir)
        body: dict[str, Any] = {"models": [model_store.masked(m) for m in models]}
        if warning:
            body["warning"] = warning
        return JSONResponse(body)

    @application.post("/api/v1/models", status_code=201)
    async def add_model_route(body: ModelCreate) -> JSONResponse:
        try:
            entry = await model_store.add_model(app_settings.config_dir, body.model_dump())
        except model_store.ModelAlreadyExists:
            raise HTTPException(status_code=409, detail=f"modèle déjà défini: {body.name}") from None
        except model_store.InvalidModelEntry as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=model_store.masked(entry))

    @application.delete("/api/v1/models/{name}", status_code=204)
    async def delete_model_route(name: str) -> Response:
        try:
            await model_store.remove_model(app_settings.config_dir, name)
        except model_store.ModelNotFound:
            raise HTTPException(status_code=404, detail=f"modèle inconnu: {name}") from None
        return Response(status_code=204)

    FastAPIInstrumentor.instrument_app(application)
    HTTPXClientInstrumentor().instrument()

    return application


# Module-level ASGI app for uvicorn (tgi.tgi:app)
app = create_app()


def port_is_free(host: str, port: int) -> bool:
    """Whether the launcher can take this port."""
    import socket  # noqa: PLC0415

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
        return True


def main() -> None:
    """Launch the ASGI server via uvicorn."""
    import uvicorn  # noqa: PLC0415

    if not port_is_free(settings.host, settings.port):
        logger.error(
            "Le port %d est déjà utilisé par un autre programme, le serveur ne peut pas démarrer. "
            "Ajoutez une ligne TGI_PORT=%d dans le fichier .env, puis relancez.",
            settings.port,
            settings.port + 1,
        )
        raise SystemExit(1)

    logger.info("Ouvrez http://%s:%d dans votre navigateur", settings.host, settings.port)
    uvicorn.run("tgi.tgi:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
