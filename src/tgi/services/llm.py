"""LLM client for ICA API (OpenAI-compatible)."""

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


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON output."""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


class LLMClient:
    """Async ICA/OpenAI client with JSON extraction and retry logic."""

    __slots__ = ("_client", "_model_cache")

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.ica_api_key,
            base_url=settings.ica_base_url,
        )
        self._model_cache: dict[str, Any] | None = None

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Send a fresh-context chat request. Returns the raw content string."""
        with trace_span("llm.chat", {"model": model, "max_tokens": max_tokens}):
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        msg = response.choices[0].message
        # Gemma 4 (and other reasoning models via ICA) may return content=None
        # and put the actual reply in reasoning_content (thinking blocks).
        content = msg.content
        if not content:
            content = getattr(msg, "reasoning_content", None) or ""
        return content

    async def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        retries: int = 3,
    ) -> Any:
        """Send request, parse JSON response. Retries up to `retries` times on parse failure."""
        last_error: Exception | None = None
        current_user_content = user_content

        for attempt in range(retries):
            try:
                raw = await self.chat(
                    model=model,
                    system_prompt=system_prompt,
                    user_content=current_user_content,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                cleaned = strip_code_fences(raw)
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "JSON parse failed on attempt %d/%d: %s",
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt < retries - 1:
                    current_user_content = (
                        f"{user_content}\n\n"
                        f"IMPORTANT: Your previous response was not valid JSON. "
                        f"Fix your JSON. Return ONLY valid JSON, nothing else. "
                        f"Error: {exc}"
                    )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed on attempt %d/%d: %s",
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt >= retries - 1:
                    break

        raise RuntimeError(f"LLM call failed after {retries} attempts. Last error: {last_error}")

    async def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models from the ICA endpoint."""
        if self._model_cache is not None:
            return list(self._model_cache.values())

        with trace_span("api.list_models", {"endpoint": f"{settings.ica_base_url}/models", "method": "GET"}):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.ica_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.ica_api_key}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()

        models: list[dict[str, Any]] = data.get("data", data) if isinstance(data, dict) else data
        self._model_cache = {m.get("id", ""): m for m in models if isinstance(m, dict)}
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
