"""Functional tests for the FastAPI app via ASGI transport (no network)."""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace

from tgi.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import Receive, Scope, Send


@pytest.fixture(autouse=True)
def _reset_tracer() -> None:
    """Reset global tracer provider between tests."""
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="test_tgi",
        projects_dir=str(tmp_path / "projects"),
        logs=str(tmp_path / "logs"),
        llm_api_key="test-key",
    )


@pytest.fixture
async def client(app_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    # Point the singletons at the temp projects dir
    from tgi.config import settings as global_settings
    from tgi.services import llm as llm_module
    from tgi.services.state_manager import state_manager

    monkeypatch.setattr(global_settings, "projects_dir", app_settings.projects_dir)

    async def _fake_check(self: object, model_id: str, required_tokens: int) -> tuple[bool, int]:
        return True, 0

    async def _fake_chat(self: object, **kwargs: object) -> str:
        return "reponse simulee du QA agent"

    monkeypatch.setattr(llm_module.LLMClient, "check_context_window", _fake_check)
    monkeypatch.setattr(llm_module.LLMClient, "chat", _fake_chat)

    # Sanity: state manager sees the patched dir
    assert state_manager

    from tgi.tgi import create_app

    application = create_app(app_settings=app_settings)
    transport = ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _upload_sample(client: AsyncClient) -> str:
    content = b"# Section Un\nUne regle metier importante.\n\n# Section Deux\nUne autre regle."
    files = {"file": ("spec.txt", content, "text/plain")}
    resp = await client.post("/upload", files=files)
    assert resp.status_code == 200
    return resp.json()["project_id"]


async def test_index_empty(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_upload_and_project_view(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.get(f"/projects/{pid}")
    assert resp.status_code == 200

    resp_tests = await client.get(f"/projects/{pid}/tests")
    assert resp_tests.status_code == 200
    assert resp_tests.json() == {"tests": []}


async def test_upload_empty_document_422(client: AsyncClient) -> None:
    files = {"file": ("empty.txt", b"   ", "text/plain")}
    resp = await client.post("/upload", files=files)
    assert resp.status_code == 422


async def test_project_not_found_404(client: AsyncClient) -> None:
    resp = await client.get("/projects/unknown-id")
    assert resp.status_code == 404


async def test_history_endpoint(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.get(f"/projects/{pid}/history")
    assert resp.status_code == 200
    commits = resp.json()["commits"]
    assert len(commits) >= 1


async def test_validate_map(client: AsyncClient) -> None:
    project_id = await _project_with_scenarios(client)
    assert (await client.post(f"/projects/{project_id}/validate-map")).status_code == 200

    from tgi.services.state_manager import state_manager

    assert (await state_manager.load(project_id))["validated"] is True


async def test_chat_uses_mocked_llm(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/chat", json={"message": "simple demande"})
    assert resp.status_code == 200
    assert "reponse simulee" in resp.json()["response"]


async def test_chat_empty_message_422(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/chat", json={"message": "  "})
    assert resp.status_code == 422


async def test_export_returns_zip(client: AsyncClient) -> None:
    project_id = await _project_with_scenarios(client)
    resp = await client.get(f"/projects/{project_id}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = archive.namelist()
    # The four artefacts of the pipeline, in reading order
    for expected in (
        "1-document.md",
        "2-distilled.json",
        "3-scenarios.json",
        "3-requirements.json",
        "4-tests.json",
        "4-tests.xlsx",
    ):
        assert expected in names


async def test_rollback_missing_hash_422(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/rollback", json={})
    assert resp.status_code == 422


async def test_run_and_rerun_start(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The routes hand the work to a background task and answer immediately."""
    from tgi.agents.orchestrator import Orchestrator

    started: list[str] = []

    async def fake_run(self: Orchestrator, project_id: str) -> None:
        started.append(f"run:{project_id}")

    async def fake_rerun(self: Orchestrator, project_id: str, scenario_id: str) -> None:
        started.append(f"rerun:{scenario_id}")

    monkeypatch.setattr(Orchestrator, "run_pipeline", fake_run)
    monkeypatch.setattr(Orchestrator, "rerun_scenario", fake_rerun)

    project_id = await _project_with_scenarios(client)
    assert (await client.post(f"/projects/{project_id}/run")).status_code == 200
    assert (await client.post(f"/projects/{project_id}/scenarios/SC-001/rerun")).status_code == 200
    await asyncio.sleep(0.05)
    assert started == [f"run:{project_id}", "rerun:SC-001"]


async def test_update_test_flow(client: AsyncClient) -> None:
    project_id = await _project_with_scenarios(client)
    resp = await client.put(
        f"/projects/{project_id}/tests/TEST-0101",
        json={"status": "validated", "name": "creation revue"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "validated"

    tests = (await client.get(f"/projects/{project_id}/tests")).json()["tests"]
    assert [x["name"] for x in tests if x["id"] == "TEST-0101"] == ["creation revue"]
    assert (await client.put(f"/projects/{project_id}/tests/PAS-LA", json={"status": "x"})).status_code == 404


async def test_rollback_success(client: AsyncClient) -> None:
    from tgi.services.git_service import git_service
    from tgi.services.state_manager import state_manager

    pid = await _upload_sample(client)
    first_hash = await git_service.current_hash(pid)
    assert first_hash is not None

    # Make a new commit
    state = await state_manager.load(pid)
    state["validated"] = True
    await state_manager.save(pid, state)
    await git_service.commit(pid, "feat: change")

    resp = await client.post(f"/projects/{pid}/rollback", json={"hash": first_hash})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_partials_tests_and_history(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp_tests = await client.get(f"/projects/{pid}/partials/tests")
    assert resp_tests.status_code == 200
    resp_hist = await client.get(f"/projects/{pid}/partials/history")
    assert resp_hist.status_code == 200


async def _project_with_scenarios(client: AsyncClient) -> str:
    """A project already distilled and generated, shaped like a real one."""
    from tgi.services.state_manager import state_manager

    project_id = await _upload_sample(client)
    state = await state_manager.load(project_id)
    state["context"] = "Application de gestion des habilitations."
    state["containers"] = {"VAL01.CU01": "Créer une habilitation", "VAL01.CU02": "Révoquer"}
    state["axes"] = {"VAL": {"leaf_prefixes": ["RM"], "leaf_depth": 2, "count": 3}}
    state["requirements"] = [
        {
            "ref": "VAL01.CU01.RM01",
            "kind": "RM",
            "axis": "VAL",
            "parent": "VAL01.CU01",
            "statement": "Le systeme cree une habilitation",
        },
        {
            "ref": "VAL01.CU01.RM02",
            "kind": "RM",
            "axis": "VAL",
            "parent": "VAL01.CU01",
            "statement": "Sans test pour le moment",
        },
        {
            "ref": "VAL01.CU02.RM01",
            "kind": "EM",
            "axis": "VAL",
            "parent": "VAL01.CU02",
            "statement": "La revocation est journalisee",
        },
    ]
    state["discards"] = [
        {"what": "Historique des versions", "reason": "sans_valeur_test", "refs": [], "decision": "proposed"}
    ]
    state["scenarios"] = [
        {
            "id": "SC-001",
            "title": "Creer une habilitation",
            "container": "VAL01.CU01",
            "kind": "nominal",
            "status": "done",
            "actors": ["RRC"],
            "preconditions": "etre authentifie",
            "requirement_refs": ["VAL01.CU01.RM01", "VAL01.CU01.RM02"],
            "uncovered_refs": ["VAL01.CU01.RM02"],
            "untestable": [],
            "tests": [
                {
                    "id": "TEST-0101",
                    "scenario_id": "SC-001",
                    "name": "creation nominale",
                    "description": "d",
                    "requirement_refs": ["VAL01.CU01.RM01"],
                    "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
                    "data_rows": [],
                    "status": "draft",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
        },
        {
            "id": "SC-002",
            "title": "Revoquer une habilitation",
            "container": "VAL01.CU02",
            "kind": "erreur",
            "status": "done",
            "derived": True,
            "actors": [],
            "preconditions": "",
            "requirement_refs": ["VAL01.CU02.RM01"],
            "uncovered_refs": [],
            "untestable": [],
            "tests": [
                {
                    "id": "TEST-0201",
                    "scenario_id": "SC-002",
                    "name": "revocation journalisee",
                    "description": "d",
                    "requirement_refs": ["VAL01.CU02.RM01"],
                    "steps": [{"order": 1, "description": "revoquer", "expected_result": "journal"}],
                    "data_rows": [{"cas": "sans droit", "attendu": "refus"}],
                    "status": "validated",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
        },
    ]
    state["distilled_at"] = "2026-01-01T00:00:00Z"
    await state_manager.save(project_id, state)
    return project_id


async def test_rule_edit_is_scoped_to_its_bloc(client: AsyncClient) -> None:
    """R1 exists in every bloc: the pair (bloc, rule) is the identity."""
    project_id = await _project_with_scenarios(client)
    missing = await client.put(f"/projects/{project_id}/blocs/bloc-99/rules/R1", json={"reviewed": True})
    assert missing.status_code == 404
    unknown = await client.put(f"/projects/{project_id}/blocs/bloc-1/rules/R404", json={"reviewed": True})
    assert unknown.status_code == 404


async def test_tests_partial_filters_and_paginates_server_side(client: AsyncClient) -> None:
    """A test card is about 5 kB of HTML: filtering and paging must happen server side."""
    project_id = await _project_with_scenarios(client)
    html = (await client.get(f"/projects/{project_id}/partials/tests")).text
    assert "TEST-0101" in html and "TEST-0201" in html
    assert 'value="SC-001"' in html and 'value="VAL01.CU01.RM01"' in html
    # The JSON payload lives in a single quoted attribute, otherwise it closes it early
    assert "x-data='testEditor(" in html
    assert 'x-data="testEditor(' not in html

    by_scenario = (await client.get(f"/projects/{project_id}/partials/tests?scenario=SC-002")).text
    assert "TEST-0201" in by_scenario and "TEST-0101" not in by_scenario

    by_requirement = (await client.get(f"/projects/{project_id}/partials/tests?requirement=VAL01.CU01.RM01")).text
    assert "TEST-0101" in by_requirement and "TEST-0201" not in by_requirement

    by_status = (await client.get(f"/projects/{project_id}/partials/tests?status=validated")).text
    assert "TEST-0201" in by_status and "TEST-0101" not in by_status

    paged = (await client.get(f"/projects/{project_id}/partials/tests?per_page=1")).text
    assert "1 à 1 sur 2" in paged and "page 1/2" in paged

    clamped = (await client.get(f"/projects/{project_id}/partials/tests?per_page=1&page=99")).text
    assert "page 2/2" in clamped  # never an empty page

    none = (await client.get(f"/projects/{project_id}/partials/tests?q=zzzintrouvable")).text
    assert "Aucun test ne correspond au filtre" in none


async def test_progress_partial_reports_the_run(client: AsyncClient) -> None:
    from tgi.services.state_manager import state_manager

    project_id = await _project_with_scenarios(client)
    state = await state_manager.load(project_id)
    state["scenarios"].append(
        {
            "id": "SC-003",
            "title": "en attente",
            "container": "",
            "status": "pending",
            "requirement_refs": [],
            "tests": [],
        }
    )
    await state_manager.save(project_id, state)

    html = (await client.get(f"/projects/{project_id}/partials/progress")).text
    assert "2/3" in html
    assert "scénarios" in html
    assert "en attente 1" in html
    assert "2 tests" in html
    assert "exigences couvertes" in html


async def test_export_contains_the_reviewable_workbook(client: AsyncClient) -> None:
    from openpyxl import load_workbook

    project_id = await _project_with_scenarios(client)
    resp = await client.get(f"/projects/{project_id}/export")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        workbook = load_workbook(io.BytesIO(archive.read("4-tests.xlsx")))

    assert workbook.sheetnames[0].startswith("Synth")
    assert "Traçabilité" in workbook.sheetnames
    assert "VAL01" in workbook.sheetnames
    assert "Écarts" in workbook.sheetnames

    # The traceability sheet is the proof nothing was forgotten
    trace = workbook["Traçabilité"]
    assert [c.value for c in trace[1]][:5] == [
        "Référence exigence",
        "Type",
        "Cas d'utilisation",
        "Énoncé",
        "Statut",
    ]
    statuses = {row[0]: row[4] for row in trace.iter_rows(min_row=2, values_only=True)}
    assert statuses["VAL01.CU01.RM01"] == "covered"
    assert statuses["VAL01.CU01.RM02"] == "missing"

    tests_sheet = workbook["VAL01"]
    assert tests_sheet.freeze_panes == "A2"
    assert tests_sheet.auto_filter.ref is not None
    assert not tests_sheet.merged_cells.ranges
    # A parameterised test carries its cases as rows, not as extra tests
    assert any(row[6] == "jeu de données" for row in tests_sheet.iter_rows(min_row=2, values_only=True))


async def test_fragments_are_compressed(client: AsyncClient) -> None:
    """The scenario tree weighs 122 kB on a real project and gzips far smaller."""
    project_id = await _project_with_scenarios(client)

    plain = await client.get(f"/projects/{project_id}/partials/requirements", headers={"Accept-Encoding": "identity"})
    zipped = await client.get(f"/projects/{project_id}/partials/requirements", headers={"Accept-Encoding": "gzip"})
    assert plain.status_code == zipped.status_code == 200
    assert zipped.headers.get("content-encoding") == "gzip"
    assert int(zipped.headers["content-length"]) < len(plain.content)
    assert "requirements-panel" in zipped.text


async def test_the_event_stream_is_never_compressed() -> None:
    """gzip buffers a stream, so live progress would arrive in bursts.

    Driven at the ASGI layer: opening a real SSE connection would never close.
    """
    from tgi.tgi import ConditionalGZipMiddleware

    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"x" * 5000})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run(path: str) -> list[tuple[bytes, bytes]]:
        headers: list[tuple[bytes, bytes]] = []

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers.extend(message["headers"])

        scope: Scope = {
            "type": "http",
            "path": path,
            "method": "GET",
            "headers": [(b"accept-encoding", b"gzip")],
        }
        await ConditionalGZipMiddleware(app)(scope, receive, send)
        return headers

    stream_headers = await run("/projects/abc/stream")
    assert not any(name == b"content-encoding" for name, _ in stream_headers)

    fragment_headers = await run("/projects/abc/partials/rules")
    assert (b"content-encoding", b"gzip") in fragment_headers


async def test_filter_dropdowns_are_ordered_numerically(client: AsyncClient) -> None:
    """RM10 used to sit between RM1 and RM2 in the filter lists."""
    from tgi.services.state_manager import state_manager

    project_id = await _project_with_scenarios(client)
    state = await state_manager.load(project_id)
    state["scenarios"][0]["tests"][0]["requirement_refs"] = [
        "VAL01.CU01.RM10",
        "VAL01.CU01.RM9",
        "VAL01.CU01.RM2",
    ]
    await state_manager.save(project_id, state)

    html = (await client.get(f"/projects/{project_id}/partials/tests")).text
    block = re.findall(r'name="requirement"(.*?)</select>', html, re.S)[0]
    assert re.findall(r'value="(VAL01\.CU01\.RM\d+)"', block) == [
        "VAL01.CU01.RM2",
        "VAL01.CU01.RM9",
        "VAL01.CU01.RM10",
    ]
