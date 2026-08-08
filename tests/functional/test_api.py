"""Functional tests for the FastAPI app via ASGI transport (no network)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace

from tgi.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
        ica_api_key="test-key",
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


async def test_validate_split(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/validate-split")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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
    pid = await _upload_sample(client)
    resp = await client.get(f"/projects/{pid}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "state.json" in names
    assert "tests/all_tests.json" in names


async def test_partials_blocs(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.get(f"/projects/{pid}/partials/blocs")
    assert resp.status_code == 200


async def test_rollback_missing_hash_422(client: AsyncClient) -> None:
    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/rollback", json={})
    assert resp.status_code == 422


async def test_run_and_rerun_start(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.agents import orchestrator as orch_module

    async def _noop_pipeline(self: object, project_id: str) -> None:
        return None

    async def _noop_rerun(self: object, project_id: str, bloc_id: str) -> None:
        return None

    monkeypatch.setattr(orch_module.Orchestrator, "run_pipeline", _noop_pipeline)
    monkeypatch.setattr(orch_module.Orchestrator, "rerun_bloc", _noop_rerun)

    pid = await _upload_sample(client)
    resp = await client.post(f"/projects/{pid}/run")
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}

    resp2 = await client.post(f"/projects/{pid}/blocs/bloc-1/rerun")
    assert resp2.status_code == 200
    assert resp2.json()["bloc_id"] == "bloc-1"


async def test_update_test_flow(client: AsyncClient) -> None:
    from tgi.services.state_manager import state_manager

    pid = await _upload_sample(client)
    # Seed a test into the first bloc
    state = await state_manager.load(pid)
    state["blocs"][0]["tests"] = [{"id": "TEST-001", "status": "draft"}]
    await state_manager.save(pid, state)

    resp = await client.put(f"/projects/{pid}/tests/TEST-001", json={"status": "validated"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "validated"

    missing = await client.put(f"/projects/{pid}/tests/NOPE", json={"status": "x"})
    assert missing.status_code == 404


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


async def test_blocs_partial_colour_codes_scores(client: AsyncClient) -> None:
    """The blocs partial must show the score and the right colour per outcome."""
    from tgi.services.state_manager import state_manager

    project_id = await _upload_sample(client)
    state = await state_manager.load(project_id)
    state["blocs"] = [
        {
            "id": "b-green",
            "title": "Passe",
            "chunk": "c",
            "rules": [{"id": "R1", "description": "d"}],
            "tests": [],
            "status": "done",
            "score": 97,
            "judge_passes": 1,
            "best_version": 1,
            "judge_history": [{"version": 1, "score": 97, "tests_count": 3}],
        },
        {
            "id": "b-yellow",
            "title": "Revue",
            "chunk": "c",
            "rules": [{"id": "R1", "description": "d"}],
            "tests": [],
            "status": "needs_human",
            "score": 60,
            "judge_passes": 3,
            "best_version": 2,
            "judge_history": [
                {"version": 1, "score": 40, "tests_count": 2},
                {"version": 2, "score": 60, "tests_count": 4},
            ],
        },
        {
            "id": "b-red",
            "title": "Faible",
            "chunk": "c",
            "rules": [{"id": "R1", "description": "d"}],
            "tests": [],
            "status": "needs_human",
            "score": 12,
            "judge_passes": 3,
            "judge_history": [],
        },
        {
            "id": "b-unscored",
            "title": "Non evalue",
            "chunk": "c",
            "rules": [{"id": "R1", "description": "d"}],
            "tests": [],
            "status": "needs_human",
            "score": None,
            "judge_passes": 3,
            "judge_history": [],
        },
        {
            "id": "b-norules",
            "title": "Sans regle",
            "chunk": "c",
            "rules": [],
            "tests": [],
            "status": "done",
            "score": None,
            "judge_passes": 0,
            "judge_history": [],
        },
        {
            "id": "b-error",
            "title": "Casse",
            "chunk": "c",
            "rules": [],
            "tests": [],
            "status": "error",
            "error": "Le modele n'a pas renvoye de JSON exploitable.",
            "judge_passes": 0,
        },
    ]
    await state_manager.save(project_id, state)

    resp = await client.get(f"/projects/{project_id}/partials/blocs")
    assert resp.status_code == 200
    html = resp.text

    # Green: passed the threshold, score shown
    assert "badge-green" in html
    assert "Terminé, score 97%" in html
    # Yellow: kept but flagged, best version reported
    assert "badge-orange" in html
    assert "Revue humaine, score 60%" in html
    assert "version retenue v2" in html
    # Red: score below the bad threshold
    assert "badge-red" in html
    assert "Couverture faible, score 12%" in html
    # Unscored judge and rule-less bloc must not claim a percentage
    assert "score non évalué" in html
    assert "Aucune règle métier" in html
    # Error stays rerunnable
    assert "renvoye de JSON exploitable" in html  # apostrophes are HTML escaped
    assert html.count("↺ Rejouer") == 6
    # The score bar reflects the configured threshold
    assert f"seuil {app_settings_pass_score()}%" in html


def app_settings_pass_score() -> int:
    from tgi.config import Settings

    return Settings().judge_pass_score
