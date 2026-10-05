"""Tests for the model table: models.json, masked everywhere outside this module."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from tgi.services import model_store

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


async def test_read_models_on_a_fresh_install_is_empty_without_error(config_dir: Path) -> None:
    models, warning = await model_store.read_models(config_dir)
    assert models == []
    assert warning is None


async def test_add_model_persists_and_is_readable(config_dir: Path) -> None:
    entry = await model_store.add_model(
        config_dir, {"name": "m1", "base_url": "https://x", "api_key": "sk-abcdefgh1234", "model": "gpt"}
    )
    assert entry["name"] == "m1"

    models, _ = await model_store.read_models(config_dir)
    assert models == [entry]


async def test_a_model_pins_its_thinking_level_and_stream(config_dir: Path) -> None:
    """The form posts strings: they must land normalized in models.json."""
    entry = await model_store.add_model(
        config_dir,
        {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g", "thinking": "medium", "stream": "false"},
    )
    assert entry["thinking"] == "medium"
    assert entry["stream"] is False

    models, _ = await model_store.read_models(config_dir)
    assert models[0]["thinking"] == "medium"
    assert models[0]["stream"] is False


def test_a_model_without_the_new_fields_keeps_the_global_defaults(config_dir: Path) -> None:
    """An entry written before the fields existed must not become invalid."""
    entry = model_store._validate_entry({"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g"})
    assert entry["thinking"] == ""
    assert entry["stream"] is None


def test_a_true_stream_string_is_normalized(config_dir: Path) -> None:
    entry = model_store._validate_entry(
        {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g", "stream": True}
    )
    assert entry["stream"] is True


async def test_add_model_rejects_an_unknown_thinking_level(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="niveau de thinking invalide"):
        await model_store.add_model(
            config_dir, {"name": "n", "base_url": "https://x", "api_key": "k", "model": "g", "thinking": "banana"}
        )


async def test_add_model_rejects_a_bad_stream_value(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="stream doit être"):
        await model_store.add_model(
            config_dir, {"name": "n", "base_url": "https://x", "api_key": "k", "model": "g", "stream": "maybe"}
        )


async def test_update_model_replaces_the_entry(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g"})
    entry = await model_store.update_model(
        config_dir,
        "m1",
        {"name": "m1", "base_url": "https://y", "api_key": "k2", "model": "g2", "thinking": "low", "stream": "false"},
    )
    assert entry["base_url"] == "https://y"
    models, _ = await model_store.read_models(config_dir)
    assert len(models) == 1
    assert models[0]["model"] == "g2"


async def test_update_model_keeps_the_key_when_it_comes_back_masked(config_dir: Path) -> None:
    """The edit form pre-fills the masked value: submitting it must not store the mask."""
    await model_store.add_model(
        config_dir, {"name": "m1", "base_url": "https://x", "api_key": "sk-abcdefgh1234", "model": "g"}
    )
    entry = await model_store.update_model(
        config_dir, "m1", {"name": "m1", "base_url": "https://x", "api_key": "sk-***1234", "model": "g"}
    )
    assert entry["api_key"] == "sk-abcdefgh1234"


async def test_update_model_keeps_the_key_when_left_empty(config_dir: Path) -> None:
    await model_store.add_model(
        config_dir, {"name": "m1", "base_url": "https://x", "api_key": "sk-abcdefgh1234", "model": "g"}
    )
    entry = await model_store.update_model(
        config_dir, "m1", {"name": "m1", "base_url": "https://x", "api_key": "", "model": "g"}
    )
    assert entry["api_key"] == "sk-abcdefgh1234"


async def test_update_model_can_rename_without_collision(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g"})
    entry = await model_store.update_model(
        config_dir, "m1", {"name": "m2", "base_url": "https://x", "api_key": "k", "model": "g"}
    )
    assert entry["name"] == "m2"
    models, _ = await model_store.read_models(config_dir)
    assert [m["name"] for m in models] == ["m2"]


async def test_update_model_rejects_a_rename_onto_an_existing_name(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g"})
    await model_store.add_model(config_dir, {"name": "m2", "base_url": "https://x", "api_key": "k", "model": "g"})
    with pytest.raises(model_store.ModelAlreadyExists):
        await model_store.update_model(
            config_dir, "m1", {"name": "m2", "base_url": "https://x", "api_key": "k", "model": "g"}
        )


async def test_update_model_on_an_unknown_name_raises(config_dir: Path) -> None:
    with pytest.raises(model_store.ModelNotFound):
        await model_store.update_model(
            config_dir, "nope", {"name": "n", "base_url": "https://x", "api_key": "k", "model": "g"}
        )


async def test_models_json_is_written_mode_0600(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "m1", "base_url": "https://x", "api_key": "k", "model": "g"})
    mode = (config_dir / model_store.MODELS_FILENAME).stat().st_mode
    assert stat.S_IMODE(mode) == stat.S_IRUSR | stat.S_IWUSR


async def test_add_model_rejects_a_duplicate_name(config_dir: Path) -> None:
    entry = {"name": "dup", "base_url": "https://x", "api_key": "k", "model": "g"}
    await model_store.add_model(config_dir, entry)
    with pytest.raises(model_store.ModelAlreadyExists):
        await model_store.add_model(config_dir, entry)


async def test_add_model_rejects_an_empty_name(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="champ vide: name"):
        await model_store.add_model(config_dir, {"name": "  ", "base_url": "https://x", "api_key": "k", "model": "g"})


async def test_add_model_rejects_an_empty_model(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="champ vide: model"):
        await model_store.add_model(config_dir, {"name": "n", "base_url": "https://x", "api_key": "k", "model": " "})


async def test_add_model_rejects_a_bad_scheme(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="base_url invalide"):
        await model_store.add_model(config_dir, {"name": "n", "base_url": "ftp://x", "api_key": "k", "model": "g"})


async def test_add_model_rejects_a_name_over_120_chars(config_dir: Path) -> None:
    with pytest.raises(model_store.InvalidModelEntry, match="trop long"):
        await model_store.add_model(
            config_dir, {"name": "x" * 121, "base_url": "https://x", "api_key": "k", "model": "g"}
        )


async def test_add_model_preserves_order(config_dir: Path) -> None:
    for name in ("a", "b", "c"):
        await model_store.add_model(config_dir, {"name": name, "base_url": "https://x", "api_key": "k", "model": "g"})
    models, _ = await model_store.read_models(config_dir)
    assert [m["name"] for m in models] == ["a", "b", "c"]


async def test_remove_model_deletes_the_entry(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "n", "base_url": "https://x", "api_key": "k", "model": "g"})
    await model_store.remove_model(config_dir, "n")
    models, _ = await model_store.read_models(config_dir)
    assert models == []


async def test_remove_model_raises_on_unknown_name(config_dir: Path) -> None:
    with pytest.raises(model_store.ModelNotFound):
        await model_store.remove_model(config_dir, "nope")


async def test_read_models_warns_on_unreadable_file(config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / model_store.MODELS_FILENAME).write_text("{ not json", encoding="utf-8")
    models, warning = await model_store.read_models(config_dir)
    assert models == []
    assert warning == "fichier de modèles illisible"


def test_mask_api_key_never_reveals_the_real_prefix() -> None:
    assert model_store.mask_api_key("sk-realsecret1234") == "sk-***1234"
    assert model_store.mask_api_key("short") == "sk-***"
    assert model_store.mask_api_key("watsonx-key-7890") == "sk-***7890"  # not a real sk- prefix either


def test_masked_copies_the_entry_without_mutating_it() -> None:
    entry = {"name": "n", "base_url": "https://x", "api_key": "sk-realsecret1234", "model": "g"}
    result = model_store.masked(entry)
    assert result["api_key"] == "sk-***1234"
    assert entry["api_key"] == "sk-realsecret1234"


async def test_concurrent_adds_lose_nothing(config_dir: Path) -> None:
    import asyncio

    async def _add(name: str) -> None:
        await model_store.add_model(config_dir, {"name": name, "base_url": "https://x", "api_key": "k", "model": "g"})

    async with asyncio.TaskGroup() as tg:
        for i in range(10):
            tg.create_task(_add(f"m{i}"))

    models, _ = await model_store.read_models(config_dir)
    assert len(models) == 10


async def test_find_model_returns_the_entry_with_its_real_key(config_dir: Path) -> None:
    await model_store.add_model(config_dir, {"name": "n", "base_url": "https://x", "api_key": "real", "model": "g"})
    found = await model_store.find_model(config_dir, "n")
    assert found is not None
    assert found["api_key"] == "real"


async def test_find_model_returns_none_when_absent(config_dir: Path) -> None:
    assert await model_store.find_model(config_dir, "nope") is None
