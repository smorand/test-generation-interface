"""Shared fixtures for the functional suite.

The settings singleton is monkeypatched, not the environment variable. Both
`StateManager.project_dir` and `GitService.repo_dir` read `tgi.config.settings`
at call time, so setting TGI_PROJECTS_DIR after import leaves them pointing at
./projects while a fresh Settings() reads the temp path: the decoys a traversal
test plants relative to tmp_path would never be reached, and the test would pass
against vulnerable code.
"""

from __future__ import annotations

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
        logs=str(tmp_path / "logs"),
        llm_api_key="test-key",
    )


@pytest.fixture
def app(app_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """The real application, exposed so a test can enumerate its routes.

    E2E-006 drives every route that takes a project_id rather than a hand-written list,
    which is what makes it go red when a route is added without validation.
    """
    from tgi.config import settings as global_settings
    from tgi.services import llm as llm_module

    monkeypatch.setattr(global_settings, "projects_dir", app_settings.projects_dir)

    async def _fake_check(self: object, model_id: str, required_tokens: int) -> tuple[bool, int]:
        return True, 0

    async def _fake_chat(self: object, **kwargs: object) -> str:
        return "reponse simulee du QA agent"

    async def _fake_chat_json(self: object, **kwargs: object) -> Any:
        # An upload starts a distillation in the background. Without this, the functional
        # suite called the real endpoint, and the answer landed on top of the state a test
        # had just prepared.
        return {"context": "contexte simule", "scenarios": [], "discards": []}

    monkeypatch.setattr(llm_module.LLMClient, "check_context_window", _fake_check)
    monkeypatch.setattr(llm_module.LLMClient, "chat", _fake_chat)
    monkeypatch.setattr(llm_module.LLMClient, "chat_json", _fake_chat_json)

    from tgi.tgi import create_app

    return create_app(app_settings=app_settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
