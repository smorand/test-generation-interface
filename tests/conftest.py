"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tgi.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings.projects_dir to an isolated temp directory."""
    target = tmp_path / "projects"
    target.mkdir(parents=True, exist_ok=True)
    from tgi.config import settings

    monkeypatch.setattr(settings, "projects_dir", str(target))
    return target


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings instance pointing logs and projects at temp dirs."""
    return Settings(
        app_name="test_tgi",
        projects_dir=str(tmp_path / "projects"),
        logs=str(tmp_path / "logs"),
        llm_api_key="test-key",
    )


class FakeLLMClient:
    """Stub LLM client returning canned responses, no network."""

    def __init__(self, chat_json_result: Any = None, chat_result: str = "") -> None:
        self._chat_json_result = chat_json_result if chat_json_result is not None else {}
        self._chat_result = chat_result
        self.calls: list[dict[str, Any]] = []

    async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        self.calls.append({"kind": "chat", "model": model})
        return self._chat_result

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        self.calls.append({"kind": "chat_json", "model": model})
        return self._chat_json_result

    async def check_context_window(self, model_id: str, required_tokens: int) -> tuple[bool, int]:
        return True, 0


@pytest.fixture
def fake_llm() -> Iterator[FakeLLMClient]:
    """Provide a fresh fake LLM client."""
    yield FakeLLMClient()


@pytest.fixture(autouse=True)
def _fresh_locks() -> Iterator[None]:
    """Each test runs on its own event loop, so it needs its own locks.

    An asyncio.Lock binds to the loop that first awaits it. Without this, a lock kept in a
    module level registry leaks into the next test and raises "bound to a different event
    loop", which made failures depend on test order.
    """
    from tgi import locks

    locks.reset()
    yield
    locks.reset()
