"""Tests for the LLM client: fence stripping, JSON parsing, retry logic."""

from __future__ import annotations

from typing import Any

import pytest

from tgi.services.llm import LLMClient, strip_code_fences


def test_strip_code_fences_json() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_plain_fence() -> None:
    raw = '```\n{"a": 1}\n```'
    assert strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_no_fence() -> None:
    raw = '  {"a": 1}  '
    assert strip_code_fences(raw) == '{"a": 1}'


class _FakeMessage:
    def __init__(self, content: str | None, reasoning: str | None = None) -> None:
        self.content = content
        if reasoning is not None:
            self.reasoning_content = reasoning


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self._index = 0

    async def create(self, **kwargs: Any) -> _FakeResponse:
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp


class _FakeChat:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.completions = _FakeCompletions(responses)


class _FakeOpenAI:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.chat = _FakeChat(responses)


def _make_client(messages: list[_FakeMessage]) -> LLMClient:
    client = LLMClient()
    client._client = _FakeOpenAI([_FakeResponse(m) for m in messages])  # type: ignore[assignment]
    return client


async def test_chat_returns_content() -> None:
    client = _make_client([_FakeMessage("hello")])
    result = await client.chat(model="m", system_prompt="s", user_content="u")
    assert result == "hello"


async def test_chat_falls_back_to_reasoning_content() -> None:
    client = _make_client([_FakeMessage(None, reasoning="thought")])
    result = await client.chat(model="m", system_prompt="s", user_content="u")
    assert result == "thought"


async def test_chat_json_parses() -> None:
    client = _make_client([_FakeMessage('```json\n{"rules": [1, 2]}\n```')])
    result = await client.chat_json(model="m", system_prompt="s", user_content="u")
    assert result == {"rules": [1, 2]}


async def test_chat_json_retries_then_succeeds() -> None:
    client = _make_client(
        [
            _FakeMessage("not json"),
            _FakeMessage('{"ok": true}'),
        ]
    )
    result = await client.chat_json(model="m", system_prompt="s", user_content="u", retries=3)
    assert result == {"ok": True}


async def test_chat_json_exhausts_retries() -> None:
    client = _make_client([_FakeMessage("still not json")])
    with pytest.raises(RuntimeError, match="failed after"):
        await client.chat_json(model="m", system_prompt="s", user_content="u", retries=2)


async def test_list_models_uses_cache() -> None:
    client = LLMClient()
    client._model_cache = {"a": {"id": "a"}}  # type: ignore[assignment]
    models = await client.list_models()
    assert models == [{"id": "a"}]


async def test_check_context_window_falls_back_true() -> None:
    client = LLMClient()
    client._model_cache = {}  # type: ignore[assignment]
    ok, ctx = await client.check_context_window("missing-model", 128000)
    assert ok is True
    assert ctx == 0


async def test_check_context_window_found() -> None:
    client = LLMClient()
    client._model_cache = {"m1": {"id": "m1", "context_window": 200000}}  # type: ignore[assignment]
    ok, ctx = await client.check_context_window("m1", 128000)
    assert ok is True
    assert ctx == 200000
