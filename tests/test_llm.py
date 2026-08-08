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


def test_extract_json_prefers_the_last_object() -> None:
    # A reasoning model echoes the prompt template, drafts, then answers last.
    raw = (
        'Instructions were: `{"rules": [{"id": "R1", "description": "..."}, ...]}`\n'
        'Draft: {"rules": []}\n'
        'Final answer:\n{"rules": [{"id": "R1", "description": "la vraie regle"}]}'
    )
    assert extract_json(raw) == {"rules": [{"id": "R1", "description": "la vraie regle"}]}


def test_strip_code_fences_returns_last_fence() -> None:
    raw = '```json\n{"draft": true}\n```\nthen after thinking:\n```json\n{"final": true}\n```'
    assert strip_code_fences(raw) == '{"final": true}'


class _FakeMessage:
    def __init__(self, content: str | None, reasoning: str | None = None) -> None:
        self.content = content
        if reasoning is not None:
            self.reasoning_content = reasoning


class _FakeChoice:
    def __init__(self, message: _FakeMessage, finish_reason: str = "stop") -> None:
        self.message = message
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, message: _FakeMessage, finish_reason: str = "stop") -> None:
        self.choices = [_FakeChoice(message, finish_reason)]


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
    assert "rejected" in seen[1]
    assert "ORIGINAL" in seen[1]


async def test_chat_json_exhausts_retries_raises_llmjsonerror() -> None:
    client = _make_client([_FakeMessage("still not json")])
    with pytest.raises(LLMJSONError, match="no valid JSON after 2 attempts"):
        await client.chat_json(model="m", system_prompt="s", user_content="u", retries=2)
    # LLMJSONError must remain a RuntimeError so existing handlers keep working.
    assert issubclass(LLMJSONError, RuntimeError)


async def test_chat_json_retries_when_shape_is_wrong() -> None:
    # Valid JSON of the wrong type must be retried, then accepted once fixed.
    seen: list[str] = []
    responses = [_FakeResponse(_FakeMessage("[1, 2, 3]")), _FakeResponse(_FakeMessage('{"ok": true}'))]

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs["messages"][-1]["content"])
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _CapturingCompletions(responses)
    client._client = fake  # type: ignore[assignment]

    result = await client.chat_json(
        model="m",
        system_prompt="s",
        user_content="u",
        retries=3,
        expected_type=dict,
        shape_hint="Return a JSON object with keys a and b",
    )
    assert result == {"ok": True}
    assert "expected a JSON object, got list" in seen[1]
    assert "Return a JSON object with keys a and b" in seen[1]


async def test_chat_json_wrong_shape_exhausts_retries() -> None:
    client = _make_client([_FakeMessage('["always a list"]')])
    with pytest.raises(LLMJSONError, match="no valid JSON after 2 attempts"):
        await client.chat_json(model="m", system_prompt="s", user_content="u", retries=2, expected_type=dict)


async def test_chat_json_accepts_either_shape() -> None:
    client = _make_client([_FakeMessage('["a list is fine"]')])
    result = await client.chat_json(model="m", system_prompt="s", user_content="u", expected_type=(dict, list))
    assert result == ["a list is fine"]


async def test_chat_uses_configured_output_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "max_output_tokens", 12345)
    seen: list[int] = []

    class _RecordingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs["max_tokens"])
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _RecordingCompletions([_FakeResponse(_FakeMessage("hi"))])
    client._client = fake  # type: ignore[assignment]

    await client.chat(model="m", system_prompt="s", user_content="u")
    assert seen == [12345]


async def test_chat_json_truncated_answer_asks_for_direct_reply() -> None:
    """A reasoning model cut off mid thought must be told to skip the reasoning."""
    seen: list[str] = []
    responses = [
        # Budget exhausted while thinking: no JSON at all.
        _FakeResponse(_FakeMessage(None, reasoning="Let me think step by step about R1, R2"), "length"),
        _FakeResponse(_FakeMessage('{"rules": []}')),
    ]

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs["messages"][-1]["content"])
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _CapturingCompletions(responses)
    client._client = fake  # type: ignore[assignment]

    result = await client.chat_json(model="m", system_prompt="s", user_content="u", retries=3)
    assert result == {"rules": []}
    # The retry must demand a direct answer, and must not echo the truncated thought.
    assert "cut off" in seen[1]
    assert "Do NOT reason" in seen[1]
    assert "step by step" not in seen[1]


async def test_chat_json_truncated_but_json_present_is_accepted() -> None:
    # Truncation only matters when it prevented a parseable answer.
    client = _make_client([_FakeMessage('{"ok": true}')])
    client._client.chat.completions._responses[0].choices[0].finish_reason = "length"  # type: ignore[attr-defined]
    assert await client.chat_json(model="m", system_prompt="s", user_content="u") == {"ok": True}


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


async def test_truncation_wins_over_shape_error() -> None:
    """A cut off answer must be reported as truncation, not as a shape problem.

    Telling the model to fix its shape is useless when the real cause is that it
    ran out of budget mid answer and only an inner fragment was recovered.
    """
    seen: list[str] = []
    responses = [
        # Cut off while writing the object: only the inner array survives.
        _FakeResponse(_FakeMessage('{"covered_rules": ["R1", "R2"'), "length"),
        _FakeResponse(_FakeMessage('{"covered_rules": ["R1"]}')),
    ]

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs["messages"][-1]["content"])
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _CapturingCompletions(responses)
    client._client = fake  # type: ignore[assignment]

    result = await client.chat_json(
        model="m",
        system_prompt="s",
        user_content="u",
        retries=3,
        expected_type=dict,
        shape_hint="Return a JSON object",
    )
    assert result == {"covered_rules": ["R1"]}
    assert "cut off" in seen[1]
    assert "Do NOT reason" in seen[1]


async def test_thinking_switch_is_sent_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hybrid reasoning models (Qwen3.6) think by default: the switch must be sent."""
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "disable_thinking", True)
    seen: list[Any] = []

    class _RecordingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs.get("extra_body"))
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _RecordingCompletions([_FakeResponse(_FakeMessage("hi"))])
    client._client = fake  # type: ignore[assignment]

    await client.chat(model="m", system_prompt="s", user_content="u")
    assert seen == [{"chat_template_kwargs": {"enable_thinking": False}}]


async def test_thinking_switch_omitted_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "disable_thinking", False)
    seen: list[Any] = []

    class _RecordingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs.get("extra_body"))
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _RecordingCompletions([_FakeResponse(_FakeMessage("hi"))])
    client._client = fake  # type: ignore[assignment]

    await client.chat(model="m", system_prompt="s", user_content="u")
    assert seen == [None]


async def test_thinking_switch_dropped_once_endpoint_rejects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gateway that validates parameters must not break every call."""
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "disable_thinking", True)
    seen: list[Any] = []

    class _RejectingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            seen.append(kwargs.get("extra_body"))
            if kwargs.get("extra_body") is not None:
                raise RuntimeError(
                    '400 - BedrockException: {"message":"chat_template_kwargs: Extra inputs are not permitted"}'
                )
            return await super().create(**kwargs)

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _RejectingCompletions([_FakeResponse(_FakeMessage("ok"))])
    client._client = fake  # type: ignore[assignment]

    # First call retries without the switch and succeeds
    assert await client.chat(model="m", system_prompt="s", user_content="u") == "ok"
    assert seen == [{"chat_template_kwargs": {"enable_thinking": False}}, None]

    # The switch is not attempted again
    await client.chat(model="m", system_prompt="s", user_content="u")
    assert seen[-1] is None
    assert len(seen) == 3


async def test_other_api_errors_still_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.services import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "disable_thinking", True)

    class _FailingCompletions(_FakeCompletions):
        async def create(self, **kwargs: Any) -> _FakeResponse:
            raise RuntimeError("503 service unavailable")

    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _FailingCompletions([])
    client._client = fake  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="503"):
        await client.chat(model="m", system_prompt="s", user_content="u")


class _MessageWithReasoning:
    """Message exposing the new vLLM field name instead of the old one."""

    def __init__(self, content: str | None, reasoning: str | None = None) -> None:
        self.content = content
        if reasoning is not None:
            self.reasoning = reasoning


async def test_chat_reads_the_new_vllm_reasoning_field() -> None:
    """vLLM renamed reasoning_content to reasoning: reading only the old name is blind."""
    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _FakeCompletions(
        [_FakeResponse(_MessageWithReasoning(None, reasoning='{"rules": []}'))]  # type: ignore[arg-type]
    )
    client._client = fake  # type: ignore[assignment]
    assert await client.chat(model="m", system_prompt="s", user_content="u") == '{"rules": []}'


async def test_chat_prefers_content_over_reasoning() -> None:
    """The answer is content; reasoning must never override it."""
    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _FakeCompletions(
        [_FakeResponse(_MessageWithReasoning('{"answer": true}', reasoning="let me think about it"))]  # type: ignore[arg-type]
    )
    client._client = fake  # type: ignore[assignment]
    assert await client.chat(model="m", system_prompt="s", user_content="u") == '{"answer": true}'


async def test_chat_json_ignores_reasoning_prose_and_retries() -> None:
    """A chain of thought must not pass as the answer: it has to parse first."""
    responses = [
        _FakeResponse(_MessageWithReasoning(None, reasoning="First I will list the rules, then...")),  # type: ignore[arg-type]
        _FakeResponse(_FakeMessage('{"rules": [1]}')),
    ]
    client = LLMClient()
    fake = _FakeOpenAI([])
    fake.chat.completions = _FakeCompletions(responses)
    client._client = fake  # type: ignore[assignment]
    assert await client.chat_json(model="m", system_prompt="s", user_content="u", retries=3) == {"rules": [1]}
