"""The three prompts shipped with the tool, and the only valid keys for an edit.

Read fresh on every call rather than cached, because a version's own copy must never
be confused with the defaults these functions return (FR-NEW-016, FR-NEW-018).
"""

from __future__ import annotations

from pathlib import Path

PROMPT_KEYS: tuple[str, ...] = ("distiller", "scenario_generator", "coverage", "similarity_judge")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def is_known_prompt_key(key: str) -> bool:
    """Whether a key may be edited, per the whitelist of FR-NEW-019."""
    return key in PROMPT_KEYS


def default_prompt(key: str) -> str:
    """The prompt shipped with the tool for this key, read from disk."""
    return (_PROMPTS_DIR / f"{key}.md").read_text(encoding="utf-8")


def default_prompts() -> dict[str, str]:
    """All three default prompts, keyed as the API and the version state are."""
    return {key: default_prompt(key) for key in PROMPT_KEYS}
