"""Shared fixtures for the functional suite.

The settings singleton is monkeypatched, not the environment variable: StateManager reads
`tgi.config.settings` at call time, so setting TGI_PROJECTS_DIR after import would leave it
pointing at ./projects while a fresh Settings() reads the temp path.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace

from tgi.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _reset_tracer() -> None:
    """Reset the global tracer provider between tests."""
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="test_tgi",
        projects_dir=str(tmp_path / "projects"),
        config_dir=tmp_path / "config",
        logs=str(tmp_path / "logs"),
        llm_api_key="test-key",
    )


@pytest.fixture
def projects_dir(app_settings: Settings) -> Path:
    from pathlib import Path as _Path

    return _Path(app_settings.projects_dir)


@pytest.fixture
def config_dir(app_settings: Settings) -> Path:
    return app_settings.config_dir


class FakeRunLLM:
    """A fake LLMClient for a full run: one scenario, a handful of tests, counted calls."""

    def __init__(self, **answers: Any) -> None:
        self.answers = {
            "distiller": {
                "context": "Contexte simulé.",
                "scenarios": [
                    {
                        "title": "Déléguer temporairement",
                        "container": "F03.EU05.CU01",
                        "requirement_refs": ["F03.EU05.CU01.RM01", "F03.EU05.CU01.RM02"],
                        "kind": "nominal",
                    }
                ],
                "discards": [],
            },
            "scenario_generator": {
                "tests": [
                    {
                        "name": "cas nominal",
                        "description": "d",
                        "requirement_refs": ["F03.EU05.CU01.RM01", "F03.EU05.CU01.RM02"],
                        "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
                    }
                ]
            },
            "coverage": {"updated": [], "added": [], "untestable": []},
        }
        self.answers.update(answers)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        self.calls.append({"kind": "chat", "model": model})
        return "reponse simulee"

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        purpose = str(kwargs.get("purpose", ""))
        self.calls.append({"kind": "chat_json", "purpose": purpose, "model": model})
        answer = self.answers.get(purpose, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def check_context_window(self, model_id: str, required_tokens: int) -> tuple[bool, int]:
        return True, 0


@pytest.fixture
def fake_llm_run() -> FakeRunLLM:
    """Shared montage, per the test plan's conftest: 1 scenario, tests, counted calls."""
    return FakeRunLLM()


@pytest.fixture
def app(app_settings: Settings, monkeypatch: pytest.MonkeyPatch, fake_llm_run: FakeRunLLM) -> FastAPI:
    """The real application, with the LLM replaced by a deterministic fake.

    StateManager and model_store both read the module level `tgi.config.settings`
    singleton at call time rather than the Settings instance passed to create_app, so
    the singleton has to be patched too, or the real ./projects would be touched.
    """
    from tgi.config import settings as global_settings

    monkeypatch.setattr(global_settings, "projects_dir", app_settings.projects_dir)
    monkeypatch.setattr(global_settings, "config_dir", app_settings.config_dir)
    monkeypatch.setattr("tgi.tgi.build_llm_client", lambda entry: fake_llm_run)

    from tgi.tgi import create_app

    return create_app(app_settings=app_settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


SPEC_TITLE = "F03.EU05.CU01 Déléguer temporairement"
SPEC_REFS = ["F03.EU05.CU01.RM01", "F03.EU05.CU01.RM02", "F03.EU05.CU01.EM01", "F03.EU05.CU01.M01"]


def spec_markdown(min_bytes: int = 12288) -> bytes:
    """A specification document carrying the fixed title and references the test plan names.

    Padded to at least min_bytes with harmless prose, so size based tests have a known floor.
    """
    header = (
        f"### {SPEC_TITLE}\n\n"
        f"{SPEC_REFS[0]} : Le système permet une délégation temporaire.\n"
        f"{SPEC_REFS[1]} : La délégation porte une date de fin.\n"
        f"{SPEC_REFS[2]} : L'écran affiche le formulaire de délégation.\n"
        f"{SPEC_REFS[3]} : Le bouton Valider est actif une fois le formulaire complet.\n\n"
    )
    padding = "Paragraphe de remplissage sans valeur de test. " * 400
    content = (header + padding).encode("utf-8")
    if len(content) < min_bytes:
        content += b" " * (min_bytes - len(content))
    return content


@pytest.fixture
def spec_md() -> bytes:
    return spec_markdown()


@pytest.fixture
async def project_with_source(client: AsyncClient, spec_md: bytes) -> str:
    """Deposit the shared specification, returning the new project's id."""
    response = await client.post(
        "/api/v1/projects",
        files={"file": ("specification_habilitations.md", spec_md, "text/markdown")},
    )
    assert response.status_code == 201, response.text
    project_id: str = response.json()["id"]
    return project_id


@pytest.fixture
async def models_file(config_dir: Path) -> dict[str, Any]:
    """A models.json with one entry, matching the test plan's shared montage."""
    from tgi.services import model_store

    entry = {
        "name": "watsonx-mistral-large",
        "base_url": "https://eu-de.ml.cloud.ibm.com",
        "api_key": "sk-test-0001",
        "model": "mistralai/mistral-large",
    }
    await model_store.add_model(config_dir, entry)
    return entry


@pytest.fixture
def no_models(config_dir: Path) -> Path:
    """TGI_CONFIG_DIR on an empty directory: no models.json at all."""
    return config_dir


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
