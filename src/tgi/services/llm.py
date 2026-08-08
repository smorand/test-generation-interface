"""LLM client for any OpenAI compatible endpoint."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from tgi.config import settings
from tgi.tracing import trace_span

logger = logging.getLogger(__name__)

# Strip ```json ... ``` or ``` ... ``` markdown wrappers from LLM output
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class LLMJSONError(RuntimeError):
    """Raised when the model fails to return valid JSON after all retries.

    This is an expected, recoverable outcome (a weak model returning prose),
    not a bug. Callers should log it as a warning and mark the unit rerunnable,
    not dump a traceback.
    """


class JSONShapeError(ValueError):
    """Raised when the parsed JSON is valid but has the wrong shape.

    Small models often return the right information in the wrong structure
    (a list instead of an object, for instance). Subclassing ValueError makes
    chat_json treat it like a parse failure, so it retries with a targeted hint.
    """


class TruncatedAnswerError(ValueError):
    """Raised when the model ran out of output budget before answering.

    Reasoning models can spend the whole budget thinking, so the reply is cut
    off mid thought and contains no JSON. Subclassing ValueError lets chat_json
    retry with an instruction to answer directly.
    """


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON output.

    Returns the last fenced block: a model that reasons before answering emits
    its final payload last.
    """
    matches = _CODE_FENCE_RE.findall(text)
    if matches:
        return str(matches[-1]).strip()
    return text.strip()


def _all_balanced(text: str, open_ch: str, close_ch: str) -> list[str]:
    """Return every top-level balanced {..}/[..] substring, in order.

    Tracks nesting depth so a complete JSON value embedded in surrounding prose
    is recovered, including several candidates in one reply.
    """
    found: list[str] = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(text[start : i + 1])
                start = -1
    return found


def _type_label(expected: type | tuple[type, ...]) -> str:
    """Human-readable name for an expected JSON type, used in retry hints."""
    names: dict[type, str] = {dict: "object", list: "array"}
    if isinstance(expected, tuple):
        return " or ".join(names.get(t, t.__name__) for t in expected)
    return names.get(expected, expected.__name__)


def extract_json(raw: str) -> Any:
    """Parse JSON from an LLM response, tolerating prose, fences and reasoning.

    Candidates are tried last first, because a model that thinks out loud emits
    its final answer at the end while earlier braces are often drafts or an echo
    of the prompt. Raises json.JSONDecodeError if nothing parses.
    """
    cleaned = strip_code_fences(raw)
    candidates: list[str] = [cleaned]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        candidates.extend(reversed(_all_balanced(cleaned, open_ch, close_ch)))

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("no JSON found", cleaned, 0)


def _failure_kind(exc: Exception) -> str:
    """Short label describing why an answer was rejected, for logs."""
    if isinstance(exc, TruncatedAnswerError):
        return "truncation"
    if isinstance(exc, JSONShapeError):
        return "shape"
    return "parse"


def _parse_answer(
    raw: str,
    *,
    truncated: bool,
    expected_type: type | tuple[type, ...] | None,
) -> Any:
    """Parse and shape check one answer.

    A truncated reply is reported as such even when a fragment happened to parse:
    the recovered value is part of an unfinished answer, so asking the model to
    fix its JSON or its shape would miss the real cause (no output budget left).
    """
    try:
        parsed = extract_json(raw)
    except json.JSONDecodeError:
        if truncated:
            raise TruncatedAnswerError(
                "answer was cut off by the output token limit before any JSON was produced"
            ) from None
        raise
    if expected_type is not None and not isinstance(parsed, expected_type):
        if truncated:
            raise TruncatedAnswerError("answer was cut off by the output token limit, only a fragment was recovered")
        raise JSONShapeError(f"expected a JSON {_type_label(expected_type)}, got {type(parsed).__name__}")
    return parsed


def _correction_prompt(
    user_content: str,
    *,
    exc: Exception,
    raw: str,
    shape_hint: str | None,
    truncated: bool,
) -> str:
    """Build the retry prompt aimed at the actual failure."""
    hint = f"\n{shape_hint}" if shape_hint else ""
    if truncated:
        # Do not echo a half finished thought back: it would eat the budget again.
        return (
            f"{user_content}\n\n"
            f"IMPORTANT: your previous answer was cut off because you spent the whole "
            f"output budget reasoning. Do NOT reason, do NOT explain, do NOT repeat the "
            f"instructions. Answer immediately with the JSON only.{hint}"
        )
    # Feed the model its own faulty reply so it can correct it, not just repeat
    # the original request. Truncate to keep the correction prompt bounded.
    faulty = raw.strip()[:2000]
    return (
        f"{user_content}\n\n"
        f"IMPORTANT: your previous answer was rejected ({exc}). "
        f"Here is what you returned:\n"
        f"<<<\n{faulty}\n>>>{hint}\n"
        f"Return ONLY the corrected JSON, no prose, no markdown fences, nothing else."
    )


# Documented switch for hybrid reasoning models served by vLLM or SGLang.
_THINKING_SWITCH_PARAM = "chat_template_kwargs"
_NO_THINKING_BODY: dict[str, Any] = {_THINKING_SWITCH_PARAM: {"enable_thinking": False}}


def _reasoning_text(message: Any) -> str:
    """Reasoning trace of a reply, whatever the server calls it.

    vLLM renamed the field from reasoning_content to reasoning, and SGLang and the
    hosted Qwen API kept reasoning_content, so a client reading only one of them
    silently sees nothing on half the stacks.
    """
    for field in ("reasoning", "reasoning_content"):
        value = getattr(message, field, None)
        if value:
            return str(value)
    return ""


def _is_unsupported_param_error(exc: Exception) -> bool:
    """True when the endpoint rejected the switch we sent.

    Gateways word this differently (litellm says "does not support parameters",
    Bedrock says "Extra inputs are not permitted"), so the reliable signal is the
    parameter name coming back in the error rather than any particular phrasing.
    """
    return _THINKING_SWITCH_PARAM in str(exc).lower()


def _tls_verification() -> bool | str:
    """What httpx should verify against: a bundle, the system store, or nothing."""
    if not settings.llm_verify_ssl:
        logger.warning(
            "TLS certificate verification is DISABLED for %s (TGI_LLM_VERIFY_SSL=false): "
            "traffic can be intercepted, prefer TGI_LLM_CA_BUNDLE",
            settings.llm_base_url,
        )
        return False
    if settings.llm_ca_bundle:
        logger.info("Verifying TLS against %s", settings.llm_ca_bundle)
        return settings.llm_ca_bundle
    return True


def _build_http_client() -> httpx.AsyncClient | None:
    """Transport for the OpenAI client, or None to keep the SDK default.

    Only built when TLS needs custom handling, so the SDK keeps its own defaults in
    the common case. The generous read timeout matches the calls this pipeline makes:
    a single generation answer can take minutes.
    """
    verify = _tls_verification()
    if verify is True:
        return None
    return httpx.AsyncClient(verify=verify, timeout=httpx.Timeout(600.0, connect=15.0))


class LLMClient:
    """Async OpenAI compatible client with JSON extraction and retry logic."""

    __slots__ = ("_client", "_model_cache", "_thinking_switch_supported")

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            http_client=_build_http_client(),
        )
        self._model_cache: dict[str, Any] | None = None
        # Assume the switch is accepted until an endpoint proves otherwise.
        self._thinking_switch_supported = True

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Send a fresh-context chat request. Returns the raw content string."""
        text, _ = await self._chat_raw(
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text

    async def _chat_raw(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> tuple[str, str | None]:
        """Send a chat request, returning (text, finish_reason).

        finish_reason lets the caller tell a real answer apart from a reply the
        model never finished, which is the usual failure mode of reasoning models
        on a tight output budget.
        """
        budget = max_tokens if max_tokens is not None else settings.max_output_tokens
        send_switch = settings.disable_thinking and self._thinking_switch_supported
        extra_body = dict(_NO_THINKING_BODY) if send_switch else None
        with trace_span(
            "llm.chat",
            {"model": model, "max_tokens": budget, "thinking_disabled": bool(send_switch)},
        ):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temperature,
                    max_tokens=budget,
                    extra_body=extra_body,
                )
            except Exception as exc:
                if not send_switch or not _is_unsupported_param_error(exc):
                    raise
                # This endpoint validates parameters and refuses the switch. Stop
                # sending it instead of failing every call from now on.
                logger.warning(
                    "Endpoint rejects the thinking switch, disabling it for this process: %s",
                    str(exc)[:200],
                )
                self._thinking_switch_supported = False
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temperature,
                    max_tokens=budget,
                )
        choice = response.choices[0]
        msg = choice.message
        content = msg.content or ""
        reasoning = _reasoning_text(msg)
        if reasoning:
            # Reasoning is never the answer, but knowing it happened explains both
            # the latency and the truncations.
            logger.debug("Model %s returned %d characters of reasoning", model, len(reasoning))
        if not content and reasoning:
            # Last resort for gateways that expose no separate answer field. The
            # value still has to parse as the expected JSON to be accepted, so a
            # chain of thought cannot silently pass as the answer.
            logger.warning(
                "Model %s returned an empty answer with %d characters of reasoning, falling back to it",
                model,
                len(reasoning),
            )
            content = reasoning
        finish_reason: str | None = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            logger.warning(
                "Model %s hit the %d token output budget before finishing its answer",
                model,
                budget,
            )
        return content, finish_reason

    async def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        retries: int | None = None,
        expected_type: type | tuple[type, ...] | None = None,
        shape_hint: str | None = None,
        purpose: str = "unknown",
    ) -> Any:
        """Send request, parse JSON response, retrying on non-JSON or ill-shaped output.

        On each failure the model's own faulty reply is fed back with an explicit
        correction instruction, which is far more effective than only repeating
        the request. Prose wrapping a JSON object/array is tolerated via
        extract_json. When expected_type is given, a valid JSON of the wrong type
        (a list where an object is required) is also retried, using shape_hint to
        tell the model the exact structure wanted. After all attempts, raises
        LLMJSONError (expected, not a bug).
        """
        max_attempts = retries if retries is not None else settings.llm_json_retries
        max_attempts = max(1, max_attempts)
        last_error: Exception | None = None
        current_user_content = user_content

        for attempt in range(max_attempts):
            raw = ""
            truncated = False
            # One span per attempt, so retries, truncations and shape failures are
            # measurable per role instead of being invisible in the logs.
            with trace_span(
                "llm.json_attempt",
                {"model": model, "purpose": purpose, "attempt": attempt + 1, "max_attempts": max_attempts},
            ) as span:
                try:
                    raw, finish_reason = await self._chat_raw(
                        model=model,
                        system_prompt=system_prompt,
                        user_content=current_user_content,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    truncated = finish_reason == "length"
                    span.set_attribute("finish_reason", finish_reason or "")
                    parsed = _parse_answer(raw, truncated=truncated, expected_type=expected_type)
                    span.set_attribute("outcome", "ok")
                    return parsed
                except (json.JSONDecodeError, ValueError) as exc:
                    last_error = exc
                    span.set_attribute("outcome", _failure_kind(exc))
                    logger.warning(
                        "JSON %s failed on attempt %d/%d for model %s: %s",
                        _failure_kind(exc),
                        attempt + 1,
                        max_attempts,
                        model,
                        exc,
                    )
                    if attempt < max_attempts - 1:
                        current_user_content = _correction_prompt(
                            user_content,
                            exc=exc,
                            raw=raw,
                            shape_hint=shape_hint,
                            truncated=truncated,
                        )
                except Exception as exc:
                    # Transport / API error: retry silently up to the limit.
                    last_error = exc
                    span.set_attribute("outcome", "api_error")
                    logger.warning(
                        "LLM call failed on attempt %d/%d for model %s: %s",
                        attempt + 1,
                        max_attempts,
                        model,
                        exc,
                    )

        raise LLMJSONError(
            f"model {model} returned no valid JSON after {max_attempts} attempts (last error: {last_error})"
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models through the OpenAI compatible /models route.

        Goes through the same OpenAI client as inference rather than a hand rolled
        request, so base url, credentials, timeouts and retries stay in one place.
        Non standard fields such as context_window survive via model_extra.
        """
        if self._model_cache is not None:
            return list(self._model_cache.values())

        with trace_span("api.list_models", {"endpoint": f"{settings.llm_base_url}/models", "method": "GET"}):
            page = await self._client.models.list()

        models: list[dict[str, Any]] = []
        for entry in page.data:
            dump = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
            extra = getattr(entry, "model_extra", None)
            if extra:
                dump.update(extra)
            models.append(dump)
        self._model_cache = {str(m.get("id", "")): m for m in models}
        return models

    async def check_context_window(self, model_id: str, required_tokens: int) -> tuple[bool, int]:
        """
        Return (ok, context_window) where ok is True if model supports required_tokens.
        Falls back to True if model info is not available (avoids blocking startup).
        """
        try:
            models = await self.list_models()
            for m in models:
                if m.get("id") == model_id:
                    ctx = m.get("context_window") or m.get("max_tokens") or m.get("context_length") or 0
                    if isinstance(ctx, int) and ctx > 0:
                        return ctx >= required_tokens, ctx
            logger.warning("Model %s not found in /models response, skipping context check", model_id)
            return True, 0
        except Exception as exc:
            logger.warning("Could not check context window for %s: %s", model_id, exc)
            return True, 0


# Singleton
llm_client = LLMClient()
