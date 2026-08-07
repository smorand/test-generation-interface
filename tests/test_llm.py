"""Tests for the LLM client: fence stripping, JSON parsing, retry logic."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tgi.services.llm import LLMClient, LLMJSONError, extract_json, strip_code_fences


def test_strip_code_fences_json() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_plain_fence() -> None:
    raw = '```\n{"a": 1}\n```'
    assert strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_no_fence() -> None:
    raw = '  {"a": 1}  '
    assert strip_code_fences(raw) == '{"a": 1}'


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fence() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_object_embedded_in_prose() -> None:
    raw = 'Here is your answer:\n{"rules": [{"id": "R1"}]}\nHope it helps!'
    assert extract_json(raw) == {"rules": [{"id": "R1"}]}


def test_extract_json_array_embedded_in_prose() -> None:
    raw = "Sure! [1, 2, 3] done."
    assert extract_json(raw) == [1, 2, 3]


def test_extract_json_nested_object() -> None:
    raw = 'blah {"a": {"b": [1, {"c": 2}]}} trailing'
    assert extract_json(raw) == {"a": {"b": [1, {"c": 2}]}}


def test_extract_json_pure_prose_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("Expert Functional Analyst. Extract all rules from the text.")


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


async def test_chat_json_recovers_json_embedded_in_prose_no_retry() -> None:
    # A single response with JSON wrapped in prose must parse without retrying.
    client = _make_client([_FakeMessage('Voici le JSON: {"rules": []} merci')])
    result = await client.chat_json(model="m", system_prompt="s", user_content="u")
    assert result == {"rules": []}


async def test_chat_json_reinjects_faulty_reply() -> None:
    # Capture the user_content of each call to prove the faulty reply is fed back.
    seen: list[str] = []
    responses = [_FakeResponse(_FakeMessage("garbage prose one")), _FakeResponse(_FakeMessage('{"ok": true}'))]

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            messages = kwargs["messages"]
            seen.append(messages[-1]["content"])
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _CapturingCompletions(responses)
    client._client = fake  # type: ignore[assignment]

    result = await client.chat_json(model="m", system_prompt="s", user_content="ORIGINAL", retries=3)
    assert result == {"ok": True}
    assert len(seen) == 2
    # Second attempt must contain the correction and the faulty reply.
    assert "garbage prose one" in seen[1]
    assert "NOT valid JSON" in seen[1]
    assert "ORIGINAL" in seen[1]


async def test_chat_json_exhausts_retries_raises_llmjsonerror() -> None:
    client = _make_client([_FakeMessage("still not json")])
    with pytest.raises(LLMJSONError, match="no valid JSON after 2 attempts"):
        await client.chat_json(model="m", system_prompt="s", user_content="u", retries=2)
    # LLMJSONError must remain a RuntimeError so existing handlers keep working.
    assert issubclass(LLMJSONError, RuntimeError)


async def test_chat_json_default_retries_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "llm_json_retries", 5)
    calls = {"n": 0}

    class _CountingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            calls["n"] += 1
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _CountingCompletions([_FakeResponse(_FakeMessage("nope"))])
    client._client = fake  # type: ignore[assignment]

    with pytest.raises(LLMJSONError):
        await client.chat_json(model="m", system_prompt="s", user_content="u")
    assert calls["n"] == 5


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
