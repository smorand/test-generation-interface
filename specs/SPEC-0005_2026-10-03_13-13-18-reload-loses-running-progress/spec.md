# Project page loses all live visibility after a reload — Bug Specification

> Generated on: 2026-10-03
> Id: SPEC-0005
> Nature: BUG
> Depth: S
> Depth evidence: 1 bounded context (project page serving), 3 files touched, no schema change, 4 requirements
> Status: Draft
> Verdict: no authority
> From backlog: n/a
> Security: n/a
> CVSS: n/a
> Affected: n/a
> Fixed in: n/a
> Defect class: absent
> Severity: Medium

## 1. Defect

### BUG-001: Reloading without `&version=` loses progress, completion and error visibility

- **Observed behavior:** `index()` (`src/tgi/tgi.py:267-306`) sets `version_state` only `if
  version:` (`tgi.py:283`). Absent, `version_state` stays `None`, so the running version's row
  falls into the static branch (`project.html:244`, `<td>{{ v.status }}</td>`) — no Alpine scope,
  no `EventSource`, never updates. Matches the screenshot: the `running` row shows the bare word
  with no `— N%` (the live template at `project.html:237` prints `running — 0%` the instant Alpine
  initializes, so its absence proves the static branch rendered).
- **Expected per authority:** none. SPEC-0003
  (`specs/archived/SPEC-0003_2026-10-03_01-45-48-versions-progress-inline-prompts-accordion/spec.md`)
  specifies this exact static rendering for `GET /?project=P1` with no `version` (SC-004,
  `spec.md:154-159`; FR-NEW-002, `:190-198`, scoped to "WHEN `version_state` is set"; FR-NEW-003,
  `:199-203`). It never addresses what happens when `version` is absent but a version is actually
  running — the gap this specification closes.
- **Reproduction:** a project has one version with `state.json["status"] == "running"`.
  `GET /?project=<id>` with no `version` — the URL reached from the project list, a bookmark, back/
  forward, or a plain refresh of such a URL. Expected: live percent, flips to `done`/`failed`.
  Actual: bare status word forever, percent never appears, nothing updates until the user manually
  retypes `&version=<id>`.
- **Root cause:** `tgi.py:283` (`if version:`) has no fallback defaulting `version` to the
  project's running one, so `version_state` stays `None` and `project.html:237-242` never
  activates.
- **Contributing factor:** `StateManager.list_versions` (`src/tgi/services/state_manager.py:391-414`)
  never returns an `error` field (only `id`, `status`, `model`, `created_at`, `:406-411`), so even a
  user who later revisits a now-`failed` version without selecting it live sees only the bare word
  `failed`, never why.
- **Impact:** anyone navigating to a project URL without `&version=` while a run is in flight. At most one version runs per project (`run_lock(project_id)`, `src/tgi/agents/orchestrator.py:50`, 409 `"génération déjà en cours"` otherwise, `tgi.py:441-442`), so the running version is always unambiguous. No data loss; the only workaround is knowing the exact id.
- **Rollback plan:** revert the `tgi.py` selection logic, the `state_manager.py` field, and the template branch; nothing persisted differently, no migration.

## 2. Expected Behavior

#### BR-001 [EARS-E]: Default-select the running version when none is requested
> WHEN `GET /` is requested with a `project` identifying an existing project and no `version` query
> parameter, AND that project has a version whose `status` is `"running"`, THE system SHALL select
> that version as `version_state`, exactly as if `&version=<that id>` had been passed.

- **Source:** decided here, BDEC-001 (SPEC-0003 never covers this precondition).
- **Inputs:** `project` query parameter; `StateManager.list_versions`.
- **Outputs:** `version_state` populated via `StateManager.load_version`, so the row and the
  `EventSource` live-bind exactly as SPEC-0003 FR-NEW-002 already specifies.
- **Business Rules:** at most one `"running"` version per project (`run_lock`, cited above), so
  selection is never ambiguous. An explicit `version` parameter always wins; this rule applies only
  to its absence.
- **Exact names:** `version_state` (existing template variable, `tgi.py:302`); no new route or
  query parameter.

#### BR-002 [EARS-U]: `list_versions` carries the persisted error
> THE `StateManager.list_versions` method SHALL include an `error` field in every returned entry,
> set to the version's persisted `state["error"]` when present, and to an empty string otherwise.

- **Source:** decided here, BDEC-002.
- **Inputs:** `state.get("error")` per version directory (written by `Orchestrator._fail`,
  `orchestrator.py:79`).
- **Outputs:** each `list_versions` entry gains `"error": str`.
- **Business Rules:** additive only — `id`/`status`/`model`/`created_at` unchanged. The corrupted
  branch (`state_manager.py:402-404`, `{"id": ..., "status": "corrompue"}`) SHALL NOT gain an
  `error` key.
- **Exact names:** dict key `"error"`, same spelling as `project.html:211` and `tgi.py:487`.

#### BR-003 [EARS-E]: A non-live failed row shows its error
> WHEN a Versions table row is not the live-bound row (`version_state` absent, or `v.id !=
> version_state.id`) AND that row's `status` is `"failed"`, THE system SHALL render `failed —
> <error>` in that row's status cell, using the `error` field BR-002 adds.

- **Source:** decided here, BDEC-003.
- **Inputs:** `v.status`, `v.error` (BR-002) in the `versions` loop (`project.html:230-253`).
- **Outputs:** the static status cell (`project.html:244`) prints `failed — <message>` instead of
  the bare word, matching SPEC-0003 FR-NEW-005's live-row format exactly (`project.html:241`).
  `"done"`/`"running"` rows unaffected (`"running"` without live binding is BR-004's scope).
- **Exact names:** literal separator `" — "` (space, em dash, space), same as the live row.

#### BR-004 [EARS-UB]: No default selection when nothing is running
> THE system SHALL NOT select any `version_state` by default when the project has no `"running"`
> version — `version` remains the only selector, and SPEC-0003 SC-004's static rendering SHALL
> stay exactly as it is today for that precondition.

- **Source:** decided here, BDEC-001 — the boundary stopping BR-001 from widening into "default to
  the most recent version," which SC-004's postcondition ("no Alpine `x-text` binding anywhere")
  forbids when nothing is running.
- **Priority:** Must-have — non regression anchor for
  `tests/functional/test_project_page.py::test_no_version_selected_fully_static`.

## 3. Edge Cases

| Case | Expected behavior | Requirement |
|------|-------------------|-------------|
| No version exists yet | No default selection | BR-004 |
| One `done` version, none running | No default selection | BR-004 |
| `running` version exists, user also passed `&version=<other>` | Explicit parameter wins | BR-001 |
| A version directory is corrupted | Excluded from the running lookup; no `error` key added | BR-002 |
| Failed version explicitly selected live | Unaffected — SPEC-0003 FR-NEW-005 already live-renders it | n/a |
| `running` version has no `error` yet | `error` is `""`, no visible change | BR-002 |

## 4. Tests

### 4.1 End to end reproduction (mandatory)

#### BT-001: Reloading without `&version=` shows live progress for the running version
- **Reproduces:** BUG-001 | **Driver:** HTTP client (`httpx.AsyncClient`, `test_project_page.py` pattern)
- **Fails today because:** `tgi.py:283` only sets `version_state` `if version:`.
- Given a completed run whose `state.json["status"]` is overwritten to `"running"` on disk (pattern of `test_api.py:751-755`) / When `GET /?project=<id>` with no `version` / Then `200`, Versions section contains `EventSource` and `x-text="percent"` for that row (today: absent).

### 4.2 New behavior

#### BT-010: BR-001 — the `EventSource` targets the running version's own id
- **Validates:** BR-001 — Given one `"running"` version / When `GET /?project=<id>` no `version` / Then body contains `/api/v1/projects/<id>/versions/<running id>/events`.

#### BT-011: BR-002 — `list_versions` returns the persisted error
- **Validates:** BR-002 — Given `state.json == {"status": "failed", "error": "modèle indisponible"}` / When `StateManager.list_versions(project_id)` / Then that entry has `"error": "modèle indisponible"`; a sibling `"done"` entry has `"error": ""`.

#### BT-012: BR-003 — a non-live failed row shows its error inline
- **Validates:** BR-003 — Given `v1` done, `v2` failed with `error == "disque plein"` / When `GET /?project=<id>&version=v1` (`v2` not live) / Then `v2`'s status cell text is exactly `failed — disque plein`.

#### BT-013: BR-004 — nothing running still renders fully static
- **Validates:** BR-004 — Given one `"done"` version, none `"running"` / When `GET /?project=<id>` no `version` / Then Versions section contains neither `EventSource` nor `x-text=`.

### 4.3 Non regression

#### BT-020: An explicit `version` still wins over the running default
- **Protects:** BR-001's explicit-selection rule — Given `v2` running, `v1` done / When `GET /?project=<id>&version=v1` / Then `version_state.id == "v1"`.

#### BT-021: SPEC-0003's live-row binding is unaffected
- **Protects:** SPEC-0003 FR-NEW-002/004/005 — Given a `"running"` version explicitly selected / When `GET /?project=<id>&version=<id>` / Then the live row's markup is unchanged (`x-data`, `EventSource`, `x-show` spans).

#### BT-022: `test_no_version_selected_fully_static` keeps passing
- **Protects:** SPEC-0003 SC-004, zero-versions precondition — Given zero versions / When `GET /?project=<id>` / Then Versions section contains neither `EventSource` nor `x-text=` (existing test, unmodified).

### 4.4 Existing tests to touch

| Test file | Test name | Action | Reason |
|-----------|-----------|--------|--------|
| `tests/functional/test_project_page.py` | `test_no_version_selected_fully_static` | Kept | Zero-version fixture, BR-004 preserves it; regression anchor (BT-022) |
| `tests/test_state_manager.py` | `test_list_versions_sorts_numerically_not_lexicographically` | Kept | Asserts `id` order only, unaffected by the additive field |
| `tests/test_state_manager.py` | `test_a_corrupted_version_state_is_reported_minimally` | Kept | Asserts the corrupted dict exactly; BR-002 excludes that branch |

## 5. Impact

| File / Module | Change | Notes |
|---------------|--------|-------|
| `src/tgi/tgi.py` | `index()` (`:267-306`) gains BR-001/BR-004 default-selection | Reads `versions` (already fetched `:292`) before the `if version:` branch |
| `src/tgi/services/state_manager.py` | `list_versions` (`:391-414`) adds `error` (BR-002) | Additive; corrupted branch untouched |
| `src/tgi/templates/project.html` | Static status cell (`:244`) gains BR-003's `failed — <error>` | No change to the live-bound branch (`:237-242`) |

**Existing specs affected:** SPEC-0003 (path above) — SC-004 and FR-NEW-002/003 are not modified;
this specification adds a precondition SC-004 never covered. SPEC-0003 is not edited.

## 6. Implementation Order

BR-002 (data field) SHALL land before or together with BR-003, which reads it. BR-001/BR-004 are independent of both.

## 7. Decisions & Assumptions

- **BDEC-001:** fix is "auto-select the running version," not "auto-select the most recent regardless of status." **Rationale:** SC-004's postcondition is explicit and SPEC-0003 stays unedited. **Implemented by:** BR-001, BR-004.
- **BDEC-002:** the error field is additive on `list_versions`, not a new endpoint. **Rationale:** the data already exists on disk (`orchestrator.py:79`); only its projection was missing. **Implemented by:** BR-002.
- **BDEC-003:** the non-live failed row reuses the live row's exact text format, no click-to-expand interaction. **Rationale:** no such pattern exists elsewhere in this template. **Implemented by:** BR-003.

## 8. Implementability Checklist

| Verdict | IMPLEMENTABLE |
|---|---|
| Open F failures | 0 |
| Registered drift | none |

1. No orphan decision — every `BDEC-XXX` names its `BR-XXX`. PASS
2. No buried change — each Section 5 file maps to its own `BR-XXX`. PASS
3. Every name spelled — `version_state`, `"error"` key, `" — "` separator. PASS
4. No forced choice — single-running-version guarantee; explicit parameter priority stated. PASS
5. Order stated — Section 6. PASS
6. Every test specified — 4.1-4.4 fully written. PASS
7. Reproduction test is end to end — BT-001 drives `GET /`, asserts response markup, fails today. PASS
7ante. Security misclassification — UI state-sync defect, none of the listed classes. `Security: n/a` stands. PASS
8. No out of spec prerequisite — all files/functions already exist as cited. PASS
9. EARS clean — `BR-001`-`BR-004` match their patterns, no forbidden modal, no nesting. PASS
10. Right tool — behavior changes, no new capability; 4 requirements within S's 3-8 range. PASS
11. Length — within the S budget (100-200 lines) after trim. PASS
12. Every code claim cited — `path:LINE` throughout; counts recounted (3 files, 4 requirements). PASS
13. No requirement rests on an absent capability — BR-002 reads `state["error"]`, already written
   (`orchestrator.py:79`); BR-003 reads BR-002's field, ordered together. PASS
14. Verdict consistent — `no authority`, `Defect class: absent`, every `BR-XXX` traces to a `BDEC-XXX`. PASS
