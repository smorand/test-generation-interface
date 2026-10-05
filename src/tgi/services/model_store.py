"""The model table: base_url, api_key, model name, thinking level and streaming,
edited from the interface.

Lives in ``<config_dir>/models.json`` rather than an environment variable, because an
exploitant provisions the directory once (FR-NEW-026) while the testeuse adds and
removes endpoints herself (FR-NEW-027). The api_key never leaves this module in clear:
every caller outside it sees ``masked()``'s output (FR-NEW-028).

The two optional fields override the global .env defaults for that model only, so a
reasoning model can think while a fast one answers directly, and a gateway that buffers
can be run without streaming while the others stream:

- ``thinking``: "" (follow TGI_DISABLE_THINKING), "off" (answer directly, the
  vLLM/SGLang switch), or "low"/"medium"/"high" (the standard reasoning_effort).
- ``stream``: null (follow TGI_LLM_STREAM), true or false.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import Any

import aiofiles

from tgi.locks import lock_for
from tgi.tracing import trace_span

logger = logging.getLogger(__name__)

MODELS_FILENAME = "models.json"
_MAX_NAME_LENGTH = 120
# Below this length the real prefix would show through a fixed slice, so the mask
# collapses to a constant instead (FR-NEW-054).
_MIN_LENGTH_FOR_SUFFIX = 8

# The reasoning levels a model entry can pin, beyond the global default. "" means
# "no override": the .env decides. "off" is the vLLM/SGLang switch, the others are
# the standard reasoning_effort values an OpenAI compatible endpoint understands.
THINKING_LEVELS = ("", "off", "low", "medium", "high")


class InvalidModelEntry(ValueError):
    """A model entry fails its own schema: empty name, empty model, or a bad base_url."""

    __slots__ = ()


class ModelAlreadyExists(ValueError):
    """A model of this name is already in the table."""

    __slots__ = ()


class ModelNotFound(KeyError):
    """No model of this name is in the table."""

    __slots__ = ()


def mask_api_key(key: str) -> str:
    """Never the real prefix: the literal sk-*** marks "masked", it does not describe the key."""
    if len(key) >= _MIN_LENGTH_FOR_SUFFIX:
        return f"sk-***{key[-4:]}"
    return "sk-***"


def masked(entry: dict[str, Any]) -> dict[str, Any]:
    """A copy of the entry safe to put in a response, a page, or a trace."""
    return {**entry, "api_key": mask_api_key(str(entry.get("api_key", "")))}


def _models_path(config_dir: Path) -> Path:
    return Path(config_dir) / MODELS_FILENAME


async def read_models(config_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Every configured entry, or an empty list with a warning when the file cannot be read.

    Absent is not an error: a fresh install has no models.json until the first entry is
    added, and that is exactly the "no model configured" case FR-NEW-029 refuses on.
    """
    path = _models_path(config_dir)
    if not path.exists():
        return [], None
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        payload = json.loads(content)
        models = payload.get("models")
        if not isinstance(models, list):
            raise ValueError("models is not a list")
        return [dict(m) for m in models if isinstance(m, dict)], None
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("Fichier de modèles illisible: %s", path)
        return [], "fichier de modèles illisible"


async def _write_models(config_dir: Path, models: list[dict[str, Any]]) -> None:
    """Write models.json atomically, mode 0o600: the file holds clear text api keys."""
    with trace_span("models.write", {"count": len(models)}):
        config_dir = Path(config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        path = _models_path(config_dir)
        tmp_path = path.with_name(f"{path.name}.tmp")
        payload = json.dumps({"models": models}, indent=2, ensure_ascii=False)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(payload)
        tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        tmp_path.replace(path)


def _validate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    name = str(entry.get("name", "")).strip()
    model = str(entry.get("model", "")).strip()
    base_url = str(entry.get("base_url", ""))
    api_key = str(entry.get("api_key", ""))
    thinking = str(entry.get("thinking") or "").strip().lower()
    if thinking not in THINKING_LEVELS:
        raise InvalidModelEntry(f"niveau de thinking invalide: {thinking} (off, low, medium, high)")
    stream = _normalize_stream(entry.get("stream"))
    if not name:
        raise InvalidModelEntry("champ vide: name")
    if len(name) > _MAX_NAME_LENGTH:
        raise InvalidModelEntry("nom de modèle trop long (max 120)")
    if not model:
        raise InvalidModelEntry("champ vide: model")
    if not base_url.lower().startswith(("http://", "https://")):
        raise InvalidModelEntry(f"base_url invalide: {base_url}")
    return {
        "name": name,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "thinking": thinking,
        "stream": stream,
    }


def _normalize_stream(value: Any) -> bool | None:
    """A checkbox comes back as "true"/"false" strings, a JSON body as a bool or nothing."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "on"):
        return True
    if text in ("false", "0", "off"):
        return False
    raise InvalidModelEntry(f"stream doit être true ou false: {value}")


async def add_model(config_dir: Path, raw_entry: dict[str, Any]) -> dict[str, Any]:
    """Validate, then append, under the models lock so concurrent adds never lose one."""
    entry = _validate_entry(raw_entry)
    async with lock_for("models"):
        models, _ = await read_models(config_dir)
        if any(m.get("name") == entry["name"] for m in models):
            raise ModelAlreadyExists(entry["name"])
        models.append(entry)
        await _write_models(config_dir, models)
    return entry


async def remove_model(config_dir: Path, name: str) -> None:
    """Remove by name, under the same lock as add_model."""
    async with lock_for("models"):
        models, _ = await read_models(config_dir)
        remaining = [m for m in models if m.get("name") != name]
        if len(remaining) == len(models):
            raise ModelNotFound(name)
        await _write_models(config_dir, remaining)


async def update_model(config_dir: Path, name: str, raw_entry: dict[str, Any]) -> dict[str, Any]:
    """Replace one entry under the models lock, keeping the key when it was left masked.

    The edit form pre-fills the api_key input with the masked value, so submitting it
    unchanged (or empty) must not wipe the real key: the mask marks "not re-entered".
    A rename is allowed, as long as no other entry already carries the new name.
    """
    async with lock_for("models"):
        models, _ = await read_models(config_dir)
        index = next((i for i, m in enumerate(models) if m.get("name") == name), None)
        if index is None:
            raise ModelNotFound(name)
        entry = dict(raw_entry)
        api_key = str(entry.get("api_key", ""))
        if not api_key or api_key.startswith("sk-***"):
            entry["api_key"] = str(models[index].get("api_key", ""))
        validated = _validate_entry(entry)
        if validated["name"] != name and any(m.get("name") == validated["name"] for m in models):
            raise ModelAlreadyExists(validated["name"])
        models[index] = validated
        await _write_models(config_dir, models)
    return validated


async def find_model(config_dir: Path, name: str) -> dict[str, Any] | None:
    """The one entry a run needs, with its api_key in clear: callers keep it in memory only."""
    models, _ = await read_models(config_dir)
    return next((m for m in models if m.get("name") == name), None)
