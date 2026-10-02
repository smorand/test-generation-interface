"""Functional suite for the lean interface: the 18 routes of SPEC-0001b.

The LLM is always simulated, never the network. Everything lives under tmp_path:
TGI_PROJECTS_DIR, TGI_CONFIG_DIR, TGI_LOGS.
"""

from __future__ import annotations

import asyncio
import errno
import json
import unicodedata
from typing import TYPE_CHECKING, Any

from openpyxl import load_workbook

from tests.functional.conftest import sha256, spec_markdown

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient

    from tests.functional.conftest import FakeRunLLM


# ---------------------------------------------------------------------------
# SC-002: deposit a specification, which creates a project
# ---------------------------------------------------------------------------


async def test_deposit_creates_a_self_contained_project(client: AsyncClient, projects_dir: Path) -> None:
    content = spec_markdown()
    response = await client.post(
        "/api/v1/projects", files={"file": ("specification_habilitations.md", content, "text/markdown")}
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["id"]) == 12
    assert all(c in "0123456789abcdef" for c in body["id"])
    assert body["source_filename"] == "specification_habilitations.md"
    assert (projects_dir / body["id"] / "project.json").is_file()
    assert (projects_dir / body["id"] / "source" / "specification_habilitations.md").is_file()
    assert not (projects_dir / "_uploads").exists()


async def test_deposit_launches_no_generation(
    client: AsyncClient, projects_dir: Path, fake_llm_run: FakeRunLLM
) -> None:
    response = await client.post("/api/v1/projects", files={"file": ("x.md", spec_markdown(), "text/markdown")})
    project_id = response.json()["id"]

    assert fake_llm_run.calls == []
    assert sorted(p.name for p in (projects_dir / project_id).iterdir()) == ["project.json", "source"]
    versions = await client.get(f"/api/v1/projects/{project_id}/versions")
    assert versions.json() == {"versions": []}


async def test_two_projects_of_the_same_filename_keep_separate_sources(client: AsyncClient, projects_dir: Path) -> None:
    first = await client.post("/api/v1/projects", files={"file": ("x.md", b"# s\n" + b"A" * 1024, "text/markdown")})
    second = await client.post("/api/v1/projects", files={"file": ("x.md", b"# s\n" + b"B" * 2048, "text/markdown")})

    id1, id2 = first.json()["id"], second.json()["id"]
    assert id1 != id2
    assert (projects_dir / id1 / "source" / "x.md").read_bytes().endswith(b"A" * 1024)
    assert (projects_dir / id2 / "source" / "x.md").read_bytes().endswith(b"B" * 2048)


async def test_an_empty_document_is_refused(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post("/api/v1/projects", files={"file": ("vide.md", b"", "text/markdown")})
    assert response.status_code == 400
    assert response.json() == {"detail": "document vide"}
    assert list(projects_dir.iterdir()) == []


async def test_an_unsupported_extension_is_refused(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post(
        "/api/v1/projects", files={"file": ("capture.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 300, "image/png")}
    )
    assert response.status_code == 415
    assert response.json() == {"detail": "format non supporté: .png"}
    assert list(projects_dir.iterdir()) == []


async def test_an_oversized_document_is_refused(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post(
        "/api/v1/projects", files={"file": ("gros.md", b"x" * (60 * 1024 * 1024), "text/markdown")}
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "document trop volumineux (max 50 Mo)"}
    assert list(projects_dir.iterdir()) == []


async def test_a_corrupted_docx_is_refused_as_illisible(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post(
        "/api/v1/projects",
        files={
            "file": (
                "spec.docx",
                b"PK\x03\x04" + b"\x00" * 500,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "document illisible"}
    assert list(projects_dir.iterdir()) == []


async def test_a_missing_file_part_is_422(client: AsyncClient) -> None:
    response = await client.post("/api/v1/projects", data={"name": "x"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


async def test_a_path_traversal_filename_is_reduced_to_its_basename(
    client: AsyncClient, projects_dir: Path, tmp_path: Path
) -> None:
    response = await client.post(
        "/api/v1/projects", files={"file": ("../../../etc/passwd.md", b"# spec\n" * 100, "text/markdown")}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["source_filename"] == "passwd.md"
    assert (projects_dir / body["id"] / "source" / "passwd.md").is_file()
    assert not (tmp_path / "etc").exists()

    windows_style = await client.post(
        "/api/v1/projects", files={"file": ("..\\..\\..\\etc\\passwd.md", b"# spec\n" * 100, "text/markdown")}
    )
    assert windows_style.json()["source_filename"] == "passwd.md"


async def test_a_unicode_filename_is_kept_as_is(client: AsyncClient, projects_dir: Path) -> None:
    unicode_name = "sp\u00e9cification_\u00e9t\u00e9_\U0001f4c4.md"
    response = await client.post("/api/v1/projects", files={"file": (unicode_name, b"# spec\n" * 100, "text/markdown")})
    assert response.status_code == 201
    stored = {p.name for p in (projects_dir / response.json()["id"] / "source").iterdir()}
    assert unicodedata.normalize("NFC", unicode_name) in stored


async def test_two_concurrent_deposits_get_distinct_ids(client: AsyncClient, projects_dir: Path) -> None:
    async def _deposit() -> str:
        r = await client.post("/api/v1/projects", files={"file": ("x.md", spec_markdown(), "text/markdown")})
        return str(r.json()["id"])

    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(_deposit())
        t2 = tg.create_task(_deposit())

    assert t1.result() != t2.result()
    assert len(list(projects_dir.iterdir())) == 2


async def test_a_full_disk_leaves_no_half_created_project(
    client: AsyncClient, projects_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tgi.services.state_manager as sm_module

    original_open = sm_module.aiofiles.open

    def _fake_open(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        if str(path).endswith(".md") and "source" in str(path) and "wb" in mode:
            raise OSError(errno.ENOSPC, "No space left on device")
        return original_open(path, mode, **kwargs)

    monkeypatch.setattr(sm_module.aiofiles, "open", _fake_open)

    response = await client.post("/api/v1/projects", files={"file": ("x.md", spec_markdown(), "text/markdown")})

    assert response.status_code == 507
    assert response.json() == {"detail": "disque plein, projet non créé"}
    assert list(projects_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# SC-003: redownload the deposited file
# ---------------------------------------------------------------------------


async def test_the_source_round_trips_byte_for_byte(
    client: AsyncClient, project_with_source: str, spec_md: bytes
) -> None:
    response = await client.get(f"/api/v1/projects/{project_with_source}/source")

    assert response.status_code == 200
    assert len(response.content) == len(spec_md)
    assert sha256(response.content) == sha256(spec_md)
    assert "specification_habilitations.md" in response.headers["content-disposition"]
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"


async def test_downloading_an_unknown_projects_source_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/ffffffffffff/source")
    assert response.status_code == 404
    assert response.json() == {"detail": "projet inconnu: ffffffffffff"}


async def test_a_manually_deleted_source_is_404_not_500(
    client: AsyncClient, project_with_source: str, projects_dir: Path
) -> None:
    (projects_dir / project_with_source / "source" / "specification_habilitations.md").unlink()

    response = await client.get(f"/api/v1/projects/{project_with_source}/source")
    assert response.status_code == 404
    assert response.json() == {"detail": "source absente"}

    listing = await client.get("/api/v1/projects")
    entry = next(p for p in listing.json()["projects"] if p["id"] == project_with_source)
    assert entry["status"] == "source_manquante"


async def test_a_project_accepts_only_one_source(
    client: AsyncClient, project_with_source: str, projects_dir: Path
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project_with_source}/source",
        files={"file": ("autre.md", b"# autre\n" * 10, "text/markdown")},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "le projet a déjà une source"}
    assert sorted(p.name for p in (projects_dir / project_with_source / "source").iterdir()) == [
        "specification_habilitations.md"
    ]


async def test_a_unicode_name_is_exposed_in_rfc5987(client: AsyncClient, projects_dir: Path) -> None:
    unicode_name = "sp\u00e9cification_\u00e9t\u00e9_\U0001f4c4.md"
    created = await client.post("/api/v1/projects", files={"file": (unicode_name, b"# s\n" * 50, "text/markdown")})
    pid = created.json()["id"]

    response = await client.get(f"/api/v1/projects/{pid}/source")
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert 'filename="specification_ete_.md"' in disposition


# ---------------------------------------------------------------------------
# SC-001: edit the prompts before generating
# ---------------------------------------------------------------------------


async def test_default_prompts_are_served(client: AsyncClient, project_with_source: str) -> None:
    from tgi.services.prompts import default_prompt

    response = await client.get(f"/api/v1/projects/{project_with_source}/prompts")
    assert response.status_code == 200
    assert response.json()["distiller"] == default_prompt("distiller")


async def test_an_edited_prompt_is_written_into_the_version_and_the_default_is_untouched(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    from tgi.services.prompts import default_prompt

    before = default_prompt("distiller")
    response = await client.post(
        f"/api/v1/projects/{project_with_source}/runs",
        json={"model": models_file["name"], "prompts": {"distiller": "Prompt édité pour la recette transverse."}},
    )
    assert response.status_code == 202
    version = response.json()["version"]
    assert version == "v1"

    stored = (projects_dir / project_with_source / "v1" / "prompts" / "distiller.md").read_text(encoding="utf-8")
    assert stored == "Prompt édité pour la recette transverse."
    assert default_prompt("distiller") == before  # the shipped file is untouched


async def test_an_unknown_prompt_key_is_refused(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project_with_source}/runs",
        json={"model": models_file["name"], "prompts": {"destiller": "x"}},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "prompt inconnu: destiller"}
    assert not (projects_dir / project_with_source / "v1").exists()


async def test_a_blank_prompt_is_refused_and_never_overwrites_the_default(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project_with_source}/runs",
        json={"model": models_file["name"], "prompts": {"distiller": "   "}},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "prompt vide: distiller"}
    assert not (projects_dir / project_with_source / "v1").exists()


async def test_a_path_traversal_prompt_key_writes_nothing_outside_the_version(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, tmp_path: Path
) -> None:
    first = await client.post(
        f"/api/v1/projects/{project_with_source}/runs",
        json={"model": models_file["name"], "prompts": {"../../../../etc/passwd": "x"}},
    )
    second = await client.post(
        f"/api/v1/projects/{project_with_source}/runs",
        json={"model": models_file["name"], "prompts": {"distiller/../../escape": "x"}},
    )

    assert first.status_code == 422
    assert second.status_code == 422
    assert list(tmp_path.rglob("passwd*")) == []
    assert list(tmp_path.rglob("escape*")) == []


async def test_running_a_project_that_does_not_exist_is_404(client: AsyncClient, models_file: dict[str, Any]) -> None:
    response = await client.post("/api/v1/projects/aaaaaaaaaaaa/runs", json={"model": models_file["name"]})
    assert response.status_code == 404
    assert response.json() == {"detail": "projet inconnu: aaaaaaaaaaaa"}


# ---------------------------------------------------------------------------
# SC-004: launch, follow, download
# ---------------------------------------------------------------------------


async def test_a_run_produces_progress_then_a_downloadable_workbook(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    response = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    assert response.status_code == 202
    version = response.json()["version"]
    assert version == "v1"

    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert detail.json()["status"] == "done"

    xlsx = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}/xlsx")
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    from io import BytesIO

    workbook = load_workbook(BytesIO(xlsx.content))
    assert workbook.sheetnames[:2] == ["Synthèse", "Traçabilité"]
    assert (projects_dir / project_with_source / "v1" / "testplan.xlsx").is_file()


async def test_without_any_model_configured_generation_is_refused(
    client: AsyncClient, project_with_source: str, projects_dir: Path
) -> None:
    response = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": "x"})
    assert response.status_code == 409
    assert response.json() == {"detail": "aucun modèle configuré"}
    assert not (projects_dir / project_with_source / "v1").exists()


async def test_an_unknown_model_name_is_refused(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str
) -> None:
    response = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": "nope"})
    assert response.status_code == 422
    assert response.json() == {"detail": "modèle inconnu: nope"}


async def test_an_unreachable_endpoint_fails_the_version_with_a_readable_message(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tgi.services.llm import LLMConnectionError

    class _Unreachable:
        async def chat(self, *args: Any, **kwargs: Any) -> str:
            raise LLMConnectionError("endpoint injoignable: http://127.0.0.1:1")

        async def chat_json(self, *args: Any, **kwargs: Any) -> Any:
            raise LLMConnectionError("endpoint injoignable: http://127.0.0.1:1")

    monkeypatch.setattr("tgi.tgi.build_llm_client", lambda entry: _Unreachable())

    response = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = response.json()["version"]

    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    assert detail.json()["status"] == "failed"
    assert detail.json()["error"] == "endpoint injoignable: http://127.0.0.1:1"

    xlsx = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}/xlsx")
    assert xlsx.status_code == 409
    assert xlsx.json() == {"detail": "version en échec"}


async def test_two_tabs_launching_the_same_project_create_only_one_version(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    gate = asyncio.Event()

    class _Blocked:
        async def chat(self, *args: Any, **kwargs: Any) -> str:
            await gate.wait()
            return "x"

        async def chat_json(self, *args: Any, **kwargs: Any) -> Any:
            await gate.wait()
            return {"context": "", "scenarios": [], "discards": []}

    import pytest as _pytest  # local import keeps module import light

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr("tgi.tgi.build_llm_client", lambda entry: _Blocked())
        try:
            async with asyncio.TaskGroup() as tg:
                t1 = tg.create_task(
                    client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
                )
                await asyncio.sleep(0.05)
                t2 = tg.create_task(
                    client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
                )
        finally:
            gate.set()
            await asyncio.sleep(0.05)

    statuses = {t1.result().status_code, t2.result().status_code}
    assert statuses == {202, 409}
    version_dirs = [d.name for d in (projects_dir / project_with_source).iterdir() if d.name.startswith("v")]
    assert version_dirs == ["v1"]


async def test_downloading_a_running_versions_workbook_is_409(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str
) -> None:
    gate = asyncio.Event()

    class _Blocked:
        async def chat(self, *args: Any, **kwargs: Any) -> str:
            await gate.wait()
            return "x"

        async def chat_json(self, *args: Any, **kwargs: Any) -> Any:
            await gate.wait()
            return {"context": "", "scenarios": [], "discards": []}

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr("tgi.tgi.build_llm_client", lambda entry: _Blocked())
        try:
            started = await client.post(
                f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]}
            )
            version = started.json()["version"]
            response = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}/xlsx")
            assert response.status_code == 409
            assert response.json() == {"detail": "génération en cours"}
        finally:
            gate.set()
            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# SC-005: versions pile up, never merge
# ---------------------------------------------------------------------------


async def test_relaunching_creates_the_next_version_without_touching_the_previous_one(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    async def _run_and_wait() -> str:
        started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
        version = started.json()["version"]
        for _ in range(200):
            detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
            if detail.json()["status"] != "running":
                break
            await asyncio.sleep(0.01)
        return str(version)

    v1 = await _run_and_wait()
    v1_fingerprint = (projects_dir / project_with_source / v1 / "state.json").read_bytes()
    v2 = await _run_and_wait()

    assert v1 == "v1"
    assert v2 == "v2"
    assert (projects_dir / project_with_source / v1 / "state.json").read_bytes() == v1_fingerprint

    listing = await client.get(f"/api/v1/projects/{project_with_source}/versions")
    ids = [v["id"] for v in listing.json()["versions"]]
    assert ids == ["v2", "v1"]  # newest first


async def test_a_corrupted_version_is_listed_but_does_not_block_a_new_one(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    broken = projects_dir / project_with_source / "v1"
    broken.mkdir()
    (broken / "state.json").write_text("{ not json", encoding="utf-8")

    listing = await client.get(f"/api/v1/projects/{project_with_source}/versions")
    assert listing.json()["versions"] == [{"id": "v1", "status": "corrompue"}]

    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    assert started.status_code == 202
    assert started.json()["version"] == "v2"


async def test_a_deep_link_to_a_missing_version_is_404(client: AsyncClient, project_with_source: str) -> None:
    response = await client.get(f"/api/v1/projects/{project_with_source}/versions/v9")
    assert response.status_code == 404
    assert response.json() == {"detail": "version inconnue: v9"}


# ---------------------------------------------------------------------------
# SC-006: delete a version
# ---------------------------------------------------------------------------


async def test_deleting_a_finished_version_removes_its_folder(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    response = await client.delete(f"/api/v1/projects/{project_with_source}/versions/{version}")
    assert response.status_code == 204
    assert not (projects_dir / project_with_source / version).exists()


async def test_deleting_the_only_version_leaves_the_project_with_its_source(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    await client.delete(f"/api/v1/projects/{project_with_source}/versions/{version}")

    listing = await client.get("/api/v1/projects")
    entry = next(p for p in listing.json()["projects"] if p["id"] == project_with_source)
    assert entry["status"] == "ok"
    assert entry["version_count"] == 0


async def test_deleting_a_running_version_is_refused(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str
) -> None:
    gate = asyncio.Event()

    class _Blocked:
        async def chat(self, *args: Any, **kwargs: Any) -> str:
            await gate.wait()
            return "x"

        async def chat_json(self, *args: Any, **kwargs: Any) -> Any:
            await gate.wait()
            return {"context": "", "scenarios": [], "discards": []}

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr("tgi.tgi.build_llm_client", lambda entry: _Blocked())
        try:
            started = await client.post(
                f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]}
            )
            version = started.json()["version"]
            response = await client.delete(f"/api/v1/projects/{project_with_source}/versions/{version}")
            assert response.status_code == 409
            assert response.json() == {"detail": "version en cours d'exécution"}
        finally:
            gate.set()
            await asyncio.sleep(0.05)


async def test_deleting_an_unknown_version_is_404(client: AsyncClient, project_with_source: str) -> None:
    response = await client.delete(f"/api/v1/projects/{project_with_source}/versions/v9")
    assert response.status_code == 404
    assert response.json() == {"detail": "version inconnue: v9"}


# ---------------------------------------------------------------------------
# SC-007: project list
# ---------------------------------------------------------------------------


async def test_an_empty_project_list_is_announced_on_the_home_page(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert "Aucun projet" in response.text


async def test_a_symlinked_entry_is_not_listed(
    client: AsyncClient, project_with_source: str, projects_dir: Path
) -> None:
    link = projects_dir / "zzzzzzzzzzzz"
    link.symlink_to(projects_dir / project_with_source, target_is_directory=True)

    response = await client.get("/api/v1/projects")
    ids = {p["id"] for p in response.json()["projects"]}
    assert "zzzzzzzzzzzz" not in ids


async def test_a_corrupted_project_json_is_listed_with_three_keys_only(client: AsyncClient, projects_dir: Path) -> None:
    broken = projects_dir / "0123456789ab"
    broken.mkdir()
    (broken / "project.json").write_text("{ not json", encoding="utf-8")

    response = await client.get("/api/v1/projects")
    entry = next(p for p in response.json()["projects"] if p["id"] == "0123456789ab")
    assert entry == {"id": "0123456789ab", "name": "0123456789ab", "status": "corrompu"}


async def test_an_old_format_project_without_project_json_is_ignored(client: AsyncClient, projects_dir: Path) -> None:
    old = projects_dir / "0123456789ab"
    old.mkdir()
    (old / "state.json").write_text("{}", encoding="utf-8")

    response = await client.get("/api/v1/projects")
    assert response.json()["projects"] == []


# ---------------------------------------------------------------------------
# SC-008: the model table
# ---------------------------------------------------------------------------


async def test_models_are_listed_added_and_removed(client: AsyncClient) -> None:
    empty = await client.get("/api/v1/models")
    assert empty.json() == {"models": []}

    created = await client.post(
        "/api/v1/models",
        json={"name": "m1", "base_url": "https://example.com", "api_key": "sk-abcdefgh1234", "model": "gpt-x"},
    )
    assert created.status_code == 201
    assert created.json()["api_key"] == "sk-***1234"

    listed = await client.get("/api/v1/models")
    assert listed.json()["models"][0]["api_key"] == "sk-***1234"
    assert listed.json()["models"][0]["name"] == "m1"

    removed = await client.delete("/api/v1/models/m1")
    assert removed.status_code == 204
    assert (await client.get("/api/v1/models")).json() == {"models": []}


async def test_adding_a_duplicate_model_name_is_409(client: AsyncClient) -> None:
    body = {"name": "dup", "base_url": "https://example.com", "api_key": "k", "model": "m"}
    await client.post("/api/v1/models", json=body)
    second = await client.post("/api/v1/models", json=body)
    assert second.status_code == 409
    assert second.json() == {"detail": "modèle déjà défini: dup"}


async def test_a_missing_base_url_is_the_frameworks_422(client: AsyncClient) -> None:
    response = await client.post("/api/v1/models", json={"name": "n", "api_key": "k", "model": "m"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.json()["detail"][0]["loc"] == ["body", "base_url"]


async def test_a_bad_scheme_base_url_is_our_own_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/models", json={"name": "n", "base_url": "ftp://x", "api_key": "k", "model": "m"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "base_url invalide: ftp://x"}


async def test_a_too_long_name_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/models", json={"name": "x" * 121, "base_url": "https://x", "api_key": "k", "model": "m"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "nom de modèle trop long (max 120)"}


async def test_removing_an_unknown_model_is_404(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/models/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "modèle inconnu: nope"}


async def test_the_api_key_never_appears_in_clear_on_the_parametres_page(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/models", json={"name": "n", "base_url": "https://x", "api_key": "sk-realsecret1234", "model": "m"}
    )
    page = await client.get("/parametres")
    assert "sk-realsecret1234" not in page.text
    assert "sk-***1234" in page.text


# ---------------------------------------------------------------------------
# SC-009: QC export
# ---------------------------------------------------------------------------


async def test_qc_export_produces_a_second_workbook(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    response = await client.post(f"/api/v1/projects/{project_with_source}/versions/{version}/qc")
    assert response.status_code == 201
    assert response.json()["path"] == f"{version}/qc.xlsx"
    assert (projects_dir / project_with_source / version / "qc.xlsx").is_file()

    download = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}/qc.xlsx")
    assert download.status_code == 200
    from io import BytesIO

    workbook = load_workbook(BytesIO(download.content))
    assert workbook["QC"]["A1"].value == "Subject"
    assert workbook["QC"]["B1"].value == "Test Name"


async def test_qc_export_on_a_version_with_no_test_is_409(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    state_path = projects_dir / project_with_source / version / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for scenario in state["scenarios"]:
        scenario["tests"] = []
    state_path.write_text(json.dumps(state), encoding="utf-8")

    response = await client.post(f"/api/v1/projects/{project_with_source}/versions/{version}/qc")
    assert response.status_code == 409
    assert response.json() == {"detail": "aucun test à exporter"}


async def test_an_unknown_requirement_prefix_produces_inconnu_and_a_warning(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, projects_dir: Path
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    state_path = projects_dir / project_with_source / version / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for scenario in state["scenarios"]:
        for test in scenario.get("tests") or []:
            test["requirement_refs"] = ["ZZ99.ZZ01"]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    response = await client.post(f"/api/v1/projects/{project_with_source}/versions/{version}/qc")
    assert response.status_code == 201
    assert any("pr\u00e9fixe d'exigence inconnu" in w for w in response.json()["warnings"])


# ---------------------------------------------------------------------------
# Security: path traversal on the 9 new routes and the 2 new query params
# ---------------------------------------------------------------------------


async def test_a_dotdot_project_id_via_percent_encoding_is_rejected_with_a_full_decoy(
    client: AsyncClient, projects_dir: Path, tmp_path: Path, config_dir: Path
) -> None:
    """E2E-094 style: a complete decoy at projects_dir root, so a missing check would leak it."""
    import datetime as _dt

    decoy = {
        "id": "..",
        "name": "ROOT-LEAK",
        "source_filename": "x.md",
        "created_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "next_version": 1,
    }
    (projects_dir / "project.json").write_text(json.dumps(decoy), encoding="utf-8")
    (projects_dir / "source").mkdir(exist_ok=True)
    (projects_dir / "source" / "x.md").write_text("ROOT-LEAK", encoding="utf-8")

    response = await client.get("/api/v1/projects/%2E%2E/source")

    assert response.status_code == 404
    assert response.json() == {"detail": "projet inconnu: .."}
    assert "ROOT-LEAK" not in response.text


async def test_a_dotdot_version_on_delete_never_reaches_rmtree(
    client: AsyncClient, project_with_source: str, projects_dir: Path
) -> None:
    before = set(projects_dir.rglob("*"))

    response = await client.delete(f"/api/v1/projects/{project_with_source}/versions/%2E%2E")

    assert response.status_code == 404
    assert response.json() == {"detail": "version inconnue: .."}
    assert projects_dir.exists()
    after = set(projects_dir.rglob("*"))
    assert before <= after  # nothing already there was removed


async def test_query_params_on_the_home_page_are_validated_too(
    client: AsyncClient, tmp_path: Path, projects_dir: Path
) -> None:
    (projects_dir / "project.json").write_text(json.dumps({"id": "..", "name": "PARENT-LEAK"}), encoding="utf-8")

    by_project = await client.get("/", params={"project": ".."})
    assert by_project.status_code == 404
    assert "projet inconnu: .." in by_project.text
    assert "PARENT-LEAK" not in by_project.text

    version_only = await client.get("/", params={"version": ".."})
    assert version_only.status_code == 404
    assert "projet inconnu: " in version_only.text


# ---------------------------------------------------------------------------
# FR-NEW-022, FR-NEW-052: the SSE stream itself
# ---------------------------------------------------------------------------


async def test_the_events_stream_replays_state_then_closes_on_done(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str
) -> None:
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]

    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    async with client.stream("GET", f"/api/v1/projects/{project_with_source}/versions/{version}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in response.aiter_text():
            body += chunk
            if "event: done" in body:
                break

    assert "event: progress" in body
    assert "event: done" in body
    assert f'"version": "{version}"' in body


async def test_the_events_stream_replays_an_error_for_a_failed_version(
    client: AsyncClient, models_file: dict[str, Any], project_with_source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tgi.services.llm import LLMConnectionError

    class _Unreachable:
        async def chat(self, *args: Any, **kwargs: Any) -> str:
            raise LLMConnectionError("endpoint injoignable: http://x")

        async def chat_json(self, *args: Any, **kwargs: Any) -> Any:
            raise LLMConnectionError("endpoint injoignable: http://x")

    monkeypatch.setattr("tgi.tgi.build_llm_client", lambda entry: _Unreachable())
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": models_file["name"]})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    async with client.stream("GET", f"/api/v1/projects/{project_with_source}/versions/{version}/events") as response:
        body = "".join([chunk async for chunk in response.aiter_text()])

    assert "event: error" in body
    assert "endpoint injoignable" in body


# ---------------------------------------------------------------------------
# FR-NEW-058: operation spans, FR-NEW-028: never the api key in clear
# ---------------------------------------------------------------------------


async def test_operations_open_their_spans_without_leaking_the_api_key(
    client: AsyncClient, app_settings: Any, project_with_source: str
) -> None:
    await client.post(
        "/api/v1/models",
        json={"name": "n", "base_url": "https://x", "api_key": "sk-test-0001", "model": "m"},
    )
    started = await client.post(f"/api/v1/projects/{project_with_source}/runs", json={"model": "n"})
    version = started.json()["version"]
    for _ in range(200):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] != "running":
            break
        await asyncio.sleep(0.01)

    otel_path = app_settings.log_dir / "test_tgi-otel.log"
    content = otel_path.read_text(encoding="utf-8")
    assert "sk-test-0001" not in content
    assert '"name": "project.create"' in content
    assert '"name": "version.run"' in content
    assert '"name": "models.write"' in content
