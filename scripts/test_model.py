"""Smoke test: verify the configured LLM endpoint works.

Usage:
    uv run scripts/test_model.py
"""

import asyncio
import json

from tgi.config import settings
from tgi.services.llm import llm_client, LLMJSONError


async def main() -> int:
    print(f"endpoint   : {settings.llm_base_url}")
    print(f"model      : {settings.model_generator}")
    print(f"max_tokens : {settings.max_output_tokens}")
    print(f"thinking   : disabled={settings.disable_thinking}")
    print(f"verify_ssl : {settings.llm_verify_ssl}")
    print()

    errors = 0

    # 1. Plain chat
    print("--- 1. Plain chat ---")
    try:
        reply = await llm_client.chat(
            model=settings.model_generator,
            system_prompt="You are a helpful assistant. Answer in one short sentence.",
            user_content="What is 2 + 2? Reply in French.",
            temperature=0.1,
        )
        print(f"OK: {reply!r}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        errors += 1

    print()

    # 2. JSON chat
    print("--- 2. JSON chat ---")
    try:
        result = await llm_client.chat_json(
            model=settings.model_generator,
            system_prompt="You are a JSON-only assistant. Return ONLY valid JSON, no markdown fences.",
            user_content='Return {"greeting": "hello", "number": 42}',
            temperature=0.0,
            expected_type=dict,
            purpose="smoke-test",
        )
        print(f"OK: {json.dumps(result, indent=2)}")
    except LLMJSONError as exc:
        print(f"LLMJSONError: {exc}")
        errors += 1
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        errors += 1

    print()

    # 3. List models (optional)
    print("--- 3. List models ---")
    try:
        models = await llm_client.list_models()
        ids = [m.get("id", "?") for m in models]
        print(f"OK: {len(models)} model(s) — {ids[:10]}")
    except Exception as exc:
        print(f"SKIP (optional): {type(exc).__name__}")

    print()
    if errors:
        print(f"FAILURES: {errors}")
    else:
        print("All checks passed.")
    return errors


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))