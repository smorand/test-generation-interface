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
