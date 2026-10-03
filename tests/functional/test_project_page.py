"""HTTP-level coverage for the Versions table's live row and the prompts accordion.

Browser-interaction scenarios (SSE event handling in the DOM, accordion click toggling,
submit payload inspection) require a browser driver not available in this test
environment; see E2E-NEW-002/003/007/008/010/015/016/017/019 in
specs/SPEC-0003_.../spec.md for their specification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
