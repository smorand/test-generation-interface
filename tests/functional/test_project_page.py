"""HTTP-level coverage for the Versions table's live row and the prompts accordion.

Browser-interaction scenarios (SSE event handling in the DOM, accordion click toggling,
submit payload inspection) require a browser driver not available in this test
environment; see E2E-NEW-002/003/007/008/010/015/016/017/019 in
specs/SPEC-0003_.../spec.md for their specification.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient


async def _run_version(client: AsyncClient, project_id: str, models_file: dict[str, Any]) -> str:
    response = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"model": models_file["name"], "prompts": {}},
    )
    assert response.status_code == 202, response.text
    version: str = response.json()["version"]
    return version


async def test_live_row_bound_no_standalone_tile(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any]
) -> None:
    """E2E-NEW-001: the running version's row carries the Alpine bindings, no standalone tile."""
    version = await _run_version(client, project_with_source, models_file)

    response = await client.get(f"/?project={project_with_source}&version={version}")

    assert response.status_code == 200
    body = response.text
    assert f"/api/v1/projects/{project_with_source}/versions/{version}/events" in body
    assert 'x-text="status"' in body
    assert 'x-text="percent"' in body
    assert f">{version}</h3>" not in body


async def test_other_rows_stay_static(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any]
) -> None:
    """E2E-NEW-004 / E2E-NEW-003 (cross-cutting): only the selected row is live-bound."""
    v1 = await _run_version(client, project_with_source, models_file)
    await client.get(f"/api/v1/projects/{project_with_source}/versions/{v1}")
    import asyncio

    for _ in range(50):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{v1}")
        if detail.json()["status"] == "done":
            break
        await asyncio.sleep(0.02)

    v2 = await _run_version(client, project_with_source, models_file)

    response = await client.get(f"/?project={project_with_source}&version={v2}")
    assert response.status_code == 200
    body = response.text

    rows = body.split("<tbody>")[1].split("</tbody>")[0]
    v1_row = next(r for r in rows.split("<tr>") if f"version={v1}" in r)
    v2_row = next(r for r in rows.split("<tr>") if f"version={v2}" in r)

    assert "x-text" not in v1_row
    assert "x-text" in v2_row
    assert "done" in v1_row


async def test_xlsx_link_carries_download_icon(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any]
) -> None:
    """E2E-NEW-005: the icon precedes the xlsx link's text."""
    version = await _run_version(client, project_with_source, models_file)
    import asyncio

    for _ in range(50):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] == "done":
            break
        await asyncio.sleep(0.02)

    response = await client.get(f"/?project={project_with_source}")
    assert response.status_code == 200
    body = response.text

    cell = body.split(f"versions/{version}/xlsx")[0][-400:]
    assert '<svg aria-hidden="true" class="tgi-xlsx-icon"' in cell


async def test_accordion_collapsed_by_default(client: AsyncClient, project_with_source: str) -> None:
    """E2E-NEW-006 / E2E-NEW-014: collapsed regardless of pre-filled prompt content."""
    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    body = response.text
    assert "promptsOpen: false" in body
    assert '<li class="bx--accordion__item"' in body
    assert 'id="distiller-prompt"' in body


async def test_accordion_has_similarity_judge_entry(client: AsyncClient, project_with_source: str) -> None:
    """FR-NEW-088: similarity_judge is a 4th collapsible entry alongside the 3 existing ones."""
    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    body = response.text
    assert 'id="distiller-prompt"' in body
    assert 'id="scenario-prompt"' in body
    assert 'id="coverage-prompt"' in body
    assert 'id="similarity-judge-prompt"' in body
    assert 'name="similarity_judge"' in body


async def test_no_version_selected_fully_static(client: AsyncClient, project_with_source: str) -> None:
    """E2E-NEW-011: no version param -> no EventSource, no x-text anywhere."""
    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    body = response.text
    versions_section = body.split('<h3 class="bx--type-productive-heading-02 tgi-heading">Versions</h3>')[1]
    assert "EventSource" not in versions_section
    assert "x-text=" not in versions_section


async def test_version_state_absent_from_table_does_not_crash(
    client: AsyncClient,
    project_with_source: str,
    models_file: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E-NEW-012: version_state loadable but missing from list_versions() -> 200, no crash."""
    from tgi.services import state_manager as state_manager_module

    version = await _run_version(client, project_with_source, models_file)
    import asyncio

    for _ in range(50):
        detail = await client.get(f"/api/v1/projects/{project_with_source}/versions/{version}")
        if detail.json()["status"] == "done":
            break
        await asyncio.sleep(0.02)

    original_list_versions = state_manager_module.StateManager.list_versions

    async def list_versions_without_it(self: Any, project_id: str) -> Any:
        versions = await original_list_versions(self, project_id)
        return [v for v in versions if v["id"] != version]

    monkeypatch.setattr(state_manager_module.StateManager, "list_versions", list_versions_without_it)

    response = await client.get(f"/?project={project_with_source}&version={version}")

    assert response.status_code == 200
    body = response.text
    assert f"/versions/{version}/events" in body


async def test_tgi_progress_class_fully_absent(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any]
) -> None:
    """E2E-NEW-013: regression guard for FR-NEW-001, running or not."""
    version = await _run_version(client, project_with_source, models_file)

    running_response = await client.get(f"/?project={project_with_source}&version={version}")
    none_response = await client.get(f"/?project={project_with_source}")

    assert 'class="tgi-progress"' not in running_response.text
    assert 'class="tgi-progress"' not in none_response.text


async def test_submit_handler_untouched_by_accordion(client: AsyncClient, project_with_source: str) -> None:
    """FR-NEW-010 (static half): the FormData read and JSON body shape are unchanged."""
    response = await client.get(f"/?project={project_with_source}")

    body = response.text
    assert 'name="distiller"' in body
    assert 'name="scenario_generator"' in body
    assert 'name="coverage"' in body
    assert "fd.get('distiller')" in body
    assert "fd.get('scenario_generator')" in body
    assert "fd.get('coverage')" in body


async def _force_status(projects_dir: Path, project_id: str, version: str, **overrides: Any) -> None:
    state_path = projects_dir / project_id / version / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(overrides)
    state_path.write_text(json.dumps(state), encoding="utf-8")


async def _wait_until_done(client: AsyncClient, project_id: str, version: str) -> None:
    import asyncio

    for _ in range(50):
        detail = await client.get(f"/api/v1/projects/{project_id}/versions/{version}")
        if detail.json()["status"] == "done":
            break
        await asyncio.sleep(0.02)


async def test_reload_without_version_shows_live_progress_for_the_running_version(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any], projects_dir: Path
) -> None:
    """BT-001 / BUG-001: GET /?project=P1 with no &version= must still live-bind the running row."""
    version = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, version)
    await _force_status(projects_dir, project_with_source, version, status="running")

    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    body = response.text
    assert "EventSource" in body
    assert 'x-text="percent"' in body


async def test_default_selection_targets_the_running_versions_own_events_endpoint(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any], projects_dir: Path
) -> None:
    """BT-010 / BR-001: the EventSource URL names the running version's own id."""
    version = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, version)
    await _force_status(projects_dir, project_with_source, version, status="running")

    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    assert f"/api/v1/projects/{project_with_source}/versions/{version}/events" in response.text


async def test_non_live_failed_row_shows_its_error_inline(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any], projects_dir: Path
) -> None:
    """BT-012 / BR-003: a failed row that is not the live row shows the error inline."""
    v1 = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, v1)
    v2 = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, v2)
    await _force_status(projects_dir, project_with_source, v2, status="failed", error="disque plein")

    response = await client.get(f"/?project={project_with_source}&version={v1}")

    assert response.status_code == 200
    assert "failed \u2014 disque plein" in response.text


async def test_nothing_running_still_renders_fully_static(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any]
) -> None:
    """BT-013 / BR-004: no running version -> no default selection, SC-004 unaffected."""
    version = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, version)

    response = await client.get(f"/?project={project_with_source}")

    assert response.status_code == 200
    versions_section = response.text.split('<h3 class="bx--type-productive-heading-02 tgi-heading">Versions</h3>')[1]
    assert "EventSource" not in versions_section
    assert "x-text=" not in versions_section


async def test_explicit_version_still_wins_over_the_running_default(
    client: AsyncClient, project_with_source: str, models_file: dict[str, Any], projects_dir: Path
) -> None:
    """BT-020: an explicit &version= always overrides the running default."""
    v1 = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, v1)
    v2 = await _run_version(client, project_with_source, models_file)
    await _wait_until_done(client, project_with_source, v2)
    await _force_status(projects_dir, project_with_source, v2, status="running")

    response = await client.get(f"/?project={project_with_source}&version={v1}")

    assert response.status_code == 200
    assert f"/api/v1/projects/{project_with_source}/versions/{v1}/events" in response.text
    assert f"/api/v1/projects/{project_with_source}/versions/{v2}/events" not in response.text
