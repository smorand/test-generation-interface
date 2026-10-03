"""SPEC-0002: create-project modal and content-hash dedup.

Scope: every E2E test of Section 12 that is reachable through the HTTP API or the
server-rendered HTML. The four purely client-side DOM/JS behaviors (E2E-004, E2E-005's
modal-closes assertion, E2E-012, E2E-021) need a real browser and are verified in Phase 5
against the running dev server, not here.
"""

from __future__ import annotations

import asyncio
import errno
import json
from typing import TYPE_CHECKING

from tests.functional.conftest import sha256

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# SC-001 / FR-NEW-001, FR-NEW-002, FR-NEW-003
# ---------------------------------------------------------------------------


async def test_e2e_001_renamed_heading_and_hint_render(client: AsyncClient) -> None:
    response = await client.get("/")
    body = response.text
    assert "Charger un projet" in body
    assert "cliquer sur un projet pour le charger" in body
    assert ">Projets<" not in body


async def test_e2e_019_nouveau_projet_heading_not_outside_modal(client: AsyncClient) -> None:
    body = (await client.get("/")).text
    before_modal = body.split('id="create-project-modal"')[0]
    assert ">Nouveau projet<" not in before_modal


async def test_e2e_020_projets_heading_string_absent(client: AsyncClient) -> None:
    body = (await client.get("/")).text
    assert ">Projets<" not in body


async def test_fr_new_003_create_button_exact_identifiers(client: AsyncClient) -> None:
    body = (await client.get("/")).text
    assert 'id="create-project-btn"' in body
    assert 'class="bx--btn bx--btn--primary"' in body
    assert '<span aria-hidden="true">+</span> Créer un projet' in body


async def test_fr_new_004_018_modal_exact_identifiers(client: AsyncClient) -> None:
    body = (await client.get("/")).text
    assert 'id="create-project-modal"' in body
    assert "bx--modal" in body
    modal_start = body.index('id="create-project-modal"')
    modal_slice = body[modal_start : modal_start + 5000]
    assert "<input" in modal_slice
    assert 'type="file"' in modal_slice
    assert 'name="file"' in modal_slice
    assert 'accept=".docx,.pdf,.txt,.md"' in modal_slice
    assert "required" in modal_slice
    assert "Déposer et analyser" in modal_slice


# ---------------------------------------------------------------------------
# SC-003 / FR-NEW-007, FR-NEW-009: new, non-duplicate upload
# ---------------------------------------------------------------------------


async def test_e2e_002_new_unique_upload_creates_a_project(client: AsyncClient, projects_dir: Path) -> None:
    content = b"spec v1 content"
    response = await client.post("/api/v1/projects", files={"file": ("spec.md", content, "text/markdown")})

    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    project_json = json.loads((projects_dir / body["id"] / "project.json").read_text())
    assert project_json["source_hash"] == sha256(content)


async def test_e2e_023_persisted_source_hash_matches_exactly(client: AsyncClient, projects_dir: Path) -> None:
    content = b"exact bytes"
    response = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    project_json = json.loads((projects_dir / response.json()["id"] / "project.json").read_text())

    assert project_json["source_hash"] == sha256(content)
    assert len(project_json["source_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in project_json["source_hash"])


# ---------------------------------------------------------------------------
# SC-004 / FR-NEW-008, FR-NEW-011, FR-NEW-013: duplicate upload
# ---------------------------------------------------------------------------


async def test_e2e_003_byte_identical_reupload_is_a_duplicate(client: AsyncClient, projects_dir: Path) -> None:
    content = b"spec v1 content"
    first = await client.post("/api/v1/projects", files={"file": ("spec.md", content, "text/markdown")})
    p1 = first.json()["id"]

    second = await client.post("/api/v1/projects", files={"file": ("spec-renamed.md", content, "text/markdown")})

    assert second.status_code == 200
    body = second.json()
    assert body == {
        "id": p1,
        "name": first.json()["name"],
        "source_filename": first.json()["source_filename"],
        "created_at": first.json()["created_at"],
        "duplicate": True,
    }
    assert len(list(projects_dir.iterdir())) == 1


async def test_e2e_024_duplicate_match_writes_nothing_to_disk(client: AsyncClient, projects_dir: Path) -> None:
    content = b"watched content"
    first = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    p1 = first.json()["id"]
    project_json_path = projects_dir / p1 / "project.json"
    mtime_before = project_json_path.stat().st_mtime_ns

    await client.post("/api/v1/projects", files={"file": ("y.md", content, "text/markdown")})

    assert project_json_path.stat().st_mtime_ns == mtime_before
    assert len(list(projects_dir.iterdir())) == 1


async def test_e2e_duplicate_warning_rendered_on_index(client: AsyncClient) -> None:
    content = b"warn me content"
    created = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    project_id = created.json()["id"]

    response = await client.get(f"/?project={project_id}&duplicate=true")

    assert "Fichier d\u00e9j\u00e0 existant dans un projet" in response.text


# ---------------------------------------------------------------------------
# SC-007 / FR-NEW-008: matched project's source has vanished
# ---------------------------------------------------------------------------


async def test_e2e_duplicate_still_reported_when_matched_source_vanished(
    client: AsyncClient, projects_dir: Path
) -> None:
    content = b"vanished content"
    created = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    p1 = created.json()["id"]
    (projects_dir / p1 / "source" / "x.md").unlink()

    response = await client.post("/api/v1/projects", files={"file": ("y.md", content, "text/markdown")})

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["id"] == p1
    assert len(list(projects_dir.iterdir())) == 1


# ---------------------------------------------------------------------------
# SC-008 / FR-NEW-010: concurrent identical uploads
# ---------------------------------------------------------------------------


async def test_e2e_006_concurrent_identical_uploads_create_exactly_one_project(
    client: AsyncClient, projects_dir: Path
) -> None:
    content = b"race content"

    async def _deposit(filename: str) -> dict[str, object]:
        r = await client.post("/api/v1/projects", files={"file": (filename, content, "text/markdown")})
        return {"status": r.status_code, "body": r.json()}

    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(_deposit("a.md"))
        t2 = tg.create_task(_deposit("b.md"))

    results = [t1.result(), t2.result()]
    statuses = sorted(r["status"] for r in results)
    assert statuses == [200, 201]

    created = next(r for r in results if r["status"] == 201)
    duplicated = next(r for r in results if r["status"] == 200)
    assert created["body"]["duplicate"] is False
    assert duplicated["body"]["duplicate"] is True
    assert duplicated["body"]["id"] == created["body"]["id"]
    assert len(list(projects_dir.iterdir())) == 1


# ---------------------------------------------------------------------------
# E2E-007 / FR-NEW-020: add_source unaffected by dedup
# ---------------------------------------------------------------------------


async def test_e2e_007_add_source_unaffected_by_dedup(client: AsyncClient, projects_dir: Path) -> None:
    content = b"shared content for add-source"
    p1 = (
        await client.post("/api/v1/projects", files={"file": ("p1.md", b"p1 unique content", "text/markdown")})
    ).json()
    p2 = (await client.post("/api/v1/projects", files={"file": ("p2.md", content, "text/markdown")})).json()
    for f in (projects_dir / p1["id"] / "source").iterdir():
        f.unlink()

    response = await client.post(
        f"/api/v1/projects/{p1['id']}/source", files={"file": ("p1.md", content, "text/markdown")}
    )

    assert response.status_code == 201
    assert "duplicate" not in response.json()
    project_json = json.loads((projects_dir / p1["id"] / "project.json").read_text())
    assert project_json["source_hash"] == sha256(b"p1 unique content")
    assert p2["id"] != p1["id"]


# ---------------------------------------------------------------------------
# E2E-008..011 / FR-NEW-019: validation runs, and fails, before hashing
# ---------------------------------------------------------------------------


async def test_e2e_008_wrong_extension_rejected_before_hashing(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post("/api/v1/projects", files={"file": ("x.exe", b"anything", "application/octet-stream")})
    assert response.status_code == 415
    assert response.json() == {"detail": "format non support\u00e9: .exe"}
    assert list(projects_dir.iterdir()) == []


async def test_e2e_009_oversized_file_rejected(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post(
        "/api/v1/projects", files={"file": ("gros.md", b"x" * (50 * 1024 * 1024 + 1), "text/markdown")}
    )
    assert response.status_code == 413
    assert list(projects_dir.iterdir()) == []


async def test_e2e_010_empty_file_rejected(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post("/api/v1/projects", files={"file": ("empty.md", b"", "text/markdown")})
    assert response.status_code == 400
    assert response.json() == {"detail": "document vide"}
    assert list(projects_dir.iterdir()) == []


async def test_e2e_011_unreadable_document_rejected_before_hashing(client: AsyncClient, projects_dir: Path) -> None:
    response = await client.post(
        "/api/v1/projects", files={"file": ("broken.docx", b"not a real docx", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "document illisible"}
    assert list(projects_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# E2E-013 / FR-NEW-016: corrupted project skipped by the dedup lookup
# ---------------------------------------------------------------------------


async def test_e2e_013_corrupted_project_skipped_by_dedup_lookup(client: AsyncClient, projects_dir: Path) -> None:
    corrupted_dir = projects_dir / "abcdefabcdef"
    corrupted_dir.mkdir(parents=True)
    (corrupted_dir / "project.json").write_text("{not json", encoding="utf-8")

    response = await client.post("/api/v1/projects", files={"file": ("n.md", b"new content", "text/markdown")})

    assert response.status_code == 201
    assert response.json()["duplicate"] is False


# ---------------------------------------------------------------------------
# E2E-014 / FR-NEW-015: a pre-existing project with no source_hash is never matched
# ---------------------------------------------------------------------------


async def test_e2e_014_project_without_source_hash_never_matched(client: AsyncClient, projects_dir: Path) -> None:
    legacy = await client.post("/api/v1/projects", files={"file": ("legacy.md", b"legacy content", "text/markdown")})
    p0_id = legacy.json()["id"]
    project_json_path = projects_dir / p0_id / "project.json"
    project = json.loads(project_json_path.read_text())
    del project["source_hash"]
    project_json_path.write_text(json.dumps(project), encoding="utf-8")

    response = await client.post("/api/v1/projects", files={"file": ("new.md", b"legacy content", "text/markdown")})

    assert response.status_code == 201
    assert response.json()["duplicate"] is False
    assert len(list(projects_dir.iterdir())) == 2


# ---------------------------------------------------------------------------
# E2E-015/016 / FR-NEW-014: duplicate warning absent without the exact parameter
# ---------------------------------------------------------------------------


async def test_e2e_015_duplicate_warning_absent_when_param_missing(client: AsyncClient) -> None:
    created = await client.post("/api/v1/projects", files={"file": ("x.md", b"plain content", "text/markdown")})
    response = await client.get(f"/?project={created.json()['id']}")
    assert "Fichier d\u00e9j\u00e0 existant dans un projet" not in response.text


async def test_e2e_016_duplicate_warning_absent_for_non_true_values(client: AsyncClient) -> None:
    created = await client.post("/api/v1/projects", files={"file": ("x.md", b"plain content 2", "text/markdown")})
    pid = created.json()["id"]

    for value in ("false", "1"):
        response = await client.get(f"/?project={pid}&duplicate={value}")
        assert "Fichier d\u00e9j\u00e0 existant dans un projet" not in response.text


# ---------------------------------------------------------------------------
# E2E-017 / FR-NEW-017: multiple pre-existing matches resolve to earliest created_at
# ---------------------------------------------------------------------------


async def test_e2e_017_multiple_matches_resolve_to_earliest_created_at(client: AsyncClient, projects_dir: Path) -> None:
    content = b"dup content"
    digest = sha256(content)

    pb = (await client.post("/api/v1/projects", files={"file": ("b.md", b"pb unique", "text/markdown")})).json()
    pa = (await client.post("/api/v1/projects", files={"file": ("a.md", b"pa unique", "text/markdown")})).json()

    for pid, created_at in ((pb["id"], "2020-01-02T00:00:00Z"), (pa["id"], "2020-01-01T00:00:00Z")):
        path = projects_dir / pid / "project.json"
        project = json.loads(path.read_text())
        project["source_hash"] = digest
        project["created_at"] = created_at
        path.write_text(json.dumps(project), encoding="utf-8")

    response = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})

    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is True
    assert body["id"] == pa["id"]


# ---------------------------------------------------------------------------
# E2E-018 / disk-full during creation is unaffected by the dedup addition
# ---------------------------------------------------------------------------


async def test_e2e_018_disk_full_releases_the_dedup_lock(
    client: AsyncClient, projects_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tgi.services.state_manager as sm_module

    original_mkdir = sm_module.Path.mkdir
    call_count = 0

    def _fake_mkdir(self: sm_module.Path, *args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError(errno.ENOSPC, "no space")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(sm_module.Path, "mkdir", _fake_mkdir)

    content = b"enospc content"
    failing = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    assert failing.status_code == 507
    assert list(projects_dir.iterdir()) == []

    sm_module.Path.mkdir = original_mkdir
    retry = await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    assert retry.status_code == 201
    assert retry.json()["duplicate"] is False


# ---------------------------------------------------------------------------
# E2E-022 / invalid project with duplicate=true still 404s
# ---------------------------------------------------------------------------


async def test_e2e_022_invalid_project_with_duplicate_true_still_404s(client: AsyncClient) -> None:
    response = await client.get("/?project=doesnotexist&duplicate=true")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# E2E-025 / project count: +1 on new, +0 on duplicate
# ---------------------------------------------------------------------------


async def test_e2e_025_project_count_increases_by_one_then_stays(client: AsyncClient) -> None:
    before = (await client.get("/api/v1/projects")).json()["projects"]
    n = len(before)

    content = b"count me content"
    await client.post("/api/v1/projects", files={"file": ("x.md", content, "text/markdown")})
    after_new = (await client.get("/api/v1/projects")).json()["projects"]
    assert len(after_new) == n + 1

    await client.post("/api/v1/projects", files={"file": ("y.md", content, "text/markdown")})
    after_duplicate = (await client.get("/api/v1/projects")).json()["projects"]
    assert len(after_duplicate) == n + 1
