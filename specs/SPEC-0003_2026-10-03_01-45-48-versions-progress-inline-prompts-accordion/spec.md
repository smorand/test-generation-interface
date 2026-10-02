# Travail UI — Inline version progress and collapsible prompts — Specification Document

> Generated on: 2026-10-03
> Id: SPEC-0003
> Nature: FEAT
> Depth: S
> Depth evidence: one observable behavior area (the version progress/list display and the prompt
> fields) on the "Travail" page; one module (`src/tgi/templates/project.html`, plus `style.css`); no
> public contract change (no route, no field, no status code touched); no data model change; fits one
> implementation run. Below the M trigger on every count.
> Status: Draft
> Type: Evolution Specification
> From backlog: n/a
> Split: not split
> Depends on: none
> Security: n/a
> CVSS: n/a
> Affected: n/a
> Fixed in: n/a

## 1. Executive Summary

The "Travail" page's right column currently shows a standalone "running" tile (heading, progress bar,
percent text, error notification, download button) above a separate "Versions" table that repeats the
same version's status in a static row. This increment removes the standalone tile and folds its live
status, percent and error into the Versions table row of the version currently being viewed, and adds
a Carbon accordion (collapsed by default) around the three prompt text areas, which today are always
visible and take most of the vertical space of the generation form.

## 2. Current State

### 2.1 How it works today

`src/tgi/templates/project.html` renders, inside `{% if project %}` (`project.html:99`), the
generation form, then two sibling sections:

- A standalone progress tile, `{% if version_state %}` (`project.html:153-174`): an Alpine scope
  (`status`, `percent`, `error`, `project.html:155-159`) opens an `EventSource` on
  `GET /api/v1/projects/{project_id}/versions/{version_id}/events` (`project.html:161`), listening for
  `progress` (sets `percent`, `project.html:162`), `done` (sets `status = 'done'`, `project.html:163`)
  and `error` (sets `status = 'failed'` and `error`, `project.html:164`) events. It renders the version
  id as an `<h3>` (`project.html:166`), includes `partials/progress.html` (`project.html:167`) — a
  Carbon progress bar bound to `percent`, a `<span x-text="status">` — `<span x-text="percent">%` line,
  and a `bx--inline-notification--error` shown only `x-show="status === 'failed'"`
  (`src/tgi/templates/partials/progress.html:1-14`) — then a "Télécharger le classeur" link, visible
  only `x-show="status === 'done'"` (`project.html:169-170`).
- The "Versions" table, `project.html:176-201`: one `<tr>` per entry of `versions`
  (`StateManager.list_versions`, `src/tgi/services/state_manager.py:354-372`), each a plain Jinja row
  with `v.id`, the static `{{ v.status }}` text (`project.html:189`), `v.model`, `v.created_at`, and an
  `xlsx` link shown only when `v.status == "done"` at page-render time (`project.html:192-195`). This
  table never updates live: a version that is `running` when the page loads stays showing the word
  `running` in that row until the next full page load.

The SSE payload's `percent` field comes from `sse_progress_payload`
(`src/tgi/progress.py:115-128`), itself built on `_run_progress`'s
`"percent": round(100 * processed / total) if total else 0` (`src/tgi/progress.py:76`). The route is
`version_events` (`src/tgi/tgi.py:473-501`), which yields an SSE `progress` frame per tick
(`src/tgi/tgi.py:480`); it is unaffected by this increment — the client side is the entire change.

`StateManager.list_versions` reports `status` as one of `running` (set at
`src/tgi/services/state_manager.py:286`), `done` (the default when `state.json` carries none,
`state_manager.py:368`), `failed` (set by the orchestrator on error, not cited here — unaffected by
this increment), or `corrompue` for an unreadable `state.json` (`state_manager.py:363`).

The generation form (`project.html:104-149`) carries, inside one Alpine scope
(`x-data="{ running: false, error: '' }"`, `project.html:104`), the model `<select>`
(`project.html:122-128`) and three always-visible `bx--form-item` blocks, one per prompt
(`project.html:130-141`): `#distiller-prompt` (name `distiller`), `#scenario-prompt` (name
`scenario_generator`), `#coverage-prompt` (name `coverage`). On submit (`project.html:105-120`), a
`FormData` read off these three fields by `name` composes the `prompts` object posted to
`POST /api/v1/projects/{project_id}/runs`; nothing in this increment touches that route, its request
body or its response.

A grep for `bx--accordion` across `src/tgi/` returns zero hits: no accordion exists anywhere in this
project today, and nothing in `carbon-components@10` (loaded from the CDN, `base.html:8`) needs
additional JS for the accordion's visual states — only the class toggle described in Section 6 below.

### 2.2 Existing specifications governing this area

- `specs/archived/SPEC-0001b_2026-10-01_14-01-27-lean-ui-versions-models/spec.md` defines the version
  list, the SSE progress endpoint and the Versions table this increment relocates content into. Not
  modified here: the endpoint, its payload shape and the table's columns are unchanged; only where and
  how the same data is rendered changes.
- `specs/archived/SPEC-0002_2026-10-03_00-31-46-create-project-modal-dedup/spec.md` introduced the
  create-project modal and established the convention this increment follows for the accordion: Carbon
  classes toggled by hand through an Alpine boolean, never Carbon's own JS web components (its DEC-008).
  Not modified here.

### 2.3 Existing test coverage

`tests/functional/test_api.py` and `tests/test_progress.py` cover the SSE payload shape and the
`/runs` route; neither asserts anything about `project.html`'s markup. A repository-wide grep for
`tgi-progress` and `bx--accordion` inside `tests/` returns zero hits: the standalone tile's presence
and the prompts' always-visible layout are today unverified by any test, confirming this increment's
test suite (Section 12) starts from zero on the specific markup it changes. Test command: `make test`
(`uv run pytest -v`, `Makefile:91-94`).

## 3. Scope

### 3.1 In Scope

- Remove the standalone progress tile (`project.html:153-174`) entirely.
- Bind the Versions table row matching the currently viewed version (`version_state.id`) to the same
  SSE stream, replacing its static status text with live status/percent/error, and its static xlsx
  link condition with a live one once `done` fires — all other rows keep today's static rendering.
- Add a 16px download icon before the `xlsx` link text, on every row where that link is shown.
- Wrap the three prompt fields in one Carbon accordion item, collapsed by default, toggled by Alpine.

### 3.2 Out of Scope (Non-Goals)

- **No change to `POST /api/v1/projects/{id}/runs`, `GET /.../events`, or any response shape.** This
  is a client-only, display-layer increment.
- **No progress-bar graphic inside the table.** A table row is too narrow for the bar; the live cell
  carries text only ("running — 76%"), matching what the user asked for ("put the progress inside the
  table").
- **No change to the model `<select>` or the submit button.** Only the three prompt fields move inside
  the accordion.
- **No persistence of the accordion's open/closed state** (e.g. in `localStorage` or a cookie): it
  resets to collapsed on every page load, by design (FR-NEW-007).

## 4. User Personas & Actors

- **User** — the single actor this application serves, unchanged from
  `specs/archived/SPEC-0002_.../spec.md` Section 4.

## 5. Usage Scenarios

### SC-001 — Viewing a running version
- **Actor:** User
- **Preconditions:** `GET /?project=P1&version=v2` where `v2.status == "running"`.
- **Flow:** The page renders the Versions table; the row for `v2` shows live text bound to the SSE
  stream ("running — N%", N starting at whatever `percent` the first `progress` frame carries); no
  standalone tile is present anywhere on the page.
- **Postconditions:** Exactly one live-bound row exists (`v2`'s); every other row is static.
- **Exceptions:** see SC-003.
- **Cross-scenario notes:** feeds SC-002 and SC-003.

### SC-002 — A running version completes while the page is open
- **Actor:** User (passive — the system pushes the update)
- **Preconditions:** SC-001's state; the SSE connection is open.
- **Flow:** The `done` SSE event arrives; the bound row's status text becomes "done"; that row's last
  column shows the `xlsx` link (with its download icon), without a page reload.
- **Postconditions:** The row reads exactly as it would after a fresh page load post-completion.
- **Exceptions:** none further.

### SC-003 — A running version fails while the page is open
- **Actor:** User (passive)
- **Preconditions:** SC-001's state; the SSE connection is open.
- **Flow:** The `error` SSE event arrives with a message; the bound row's status text becomes "failed
  — `<message>`"; no separate notification block appears anywhere on the page.
- **Postconditions:** The error is visible exactly once, inline in the table.
- **Exceptions:** none further.

### SC-004 — Viewing a project with no version selected
- **Actor:** User
- **Preconditions:** `GET /?project=P1` with no `version` query parameter (`version_state` absent).
- **Flow:** The Versions table renders every row statically, exactly as before this increment; no row
  is SSE-bound; no standalone tile is present (it never was shown in this case either).
- **Postconditions:** No Alpine `x-text` binding exists anywhere inside the table.
- **Exceptions:** none.

### SC-005 — Toggling the prompts accordion
- **Actor:** User
- **Preconditions:** The generation form is rendered; the accordion is collapsed (its default state).
- **Flow:** User clicks the "Prompts" accordion heading; the three prompt fields become visible, the
  heading gains the active/expanded visual state. Clicking again collapses them.
- **Postconditions:** The accordion's open/closed state matches the last click; no page reload; no
  network request.
- **Exceptions:** none.

### SC-006 — Launching a generation with the accordion collapsed
- **Actor:** User
- **Preconditions:** The accordion is collapsed; the three prompt fields hold their loaded default
  text (`prompts.get(...)`, `project.html:132,136,140`), unedited or edited.
- **Flow:** User clicks "Lancer la génération" without opening the accordion. The existing submit
  handler reads the three fields by `name` from the form's `FormData`
  (`project.html:106-110`) and posts them exactly as today.
- **Postconditions:** `POST /api/v1/projects/{id}/runs` receives the same `prompts` object it would
  have received had the accordion been open — collapsing never empties, hides-from-submission, or
  resets a field's value.
- **Exceptions:** none further; this is the regression this increment must not introduce.

## 6. Functional Requirements

**FR-NEW-001** `[EARS-UB]` THE system SHALL NOT render the standalone progress tile (today's
`{% if version_state %}` block at `project.html:153-174`, including its `<h3>` version id, its
`{% include "partials/progress.html" %}` and its "Télécharger le classeur" action) as a separate
section of the page, in any state of `version_state`. *Priority:* must.

**FR-NEW-002** `[EARS-E]` WHEN `version_state` is set, THE system SHALL render the Versions table's row
whose `Version` column matches `version_state.id` with live status text sourced from the same SSE
endpoint the removed tile used (`GET /api/v1/projects/{project_id}/versions/{version_id}/events`,
`project.html:161` today), replacing the static `{{ v.status }}` text
(today `project.html:189`) with `<span x-text="status"></span> — <span x-text="percent"></span>%`
bound to an Alpine scope carrying `status` (initial value `version_state.status`), `percent` (initial
value `0`) and `error` (initial value `version_state.error or ''`) — the same three values the removed
tile initialized with (today `project.html:156-158`). *Priority:* must.

**FR-NEW-003** `[EARS-UB]` THE system SHALL NOT apply the live binding of FR-NEW-002 to any Versions
table row other than the one matching `version_state.id`; every other row SHALL keep today's static
Jinja rendering (`{{ v.status }}`, `{{ v.get("model", "") }}`, `{{ v.get("created_at", "") }}`,
and the `{% if v.status == "done" %}` xlsx condition) unchanged. *Priority:* must.

**FR-NEW-004** `[EARS-E]` WHEN the SSE `done` event is received on the bound row's EventSource, THE
system SHALL set that row's live `status` to `done` and render that row's last column as the `xlsx`
download link (same href as today's static condition, `project.html:193-194`), without a page reload.
*Priority:* must.

**FR-NEW-005** `[EARS-O]` IF the SSE `error` event is received on the bound row's EventSource, THEN
THE system SHALL set that row's live `status` to `failed`, set `error` to the event's `error` field
(`JSON.parse(e.data).error`, same parse as today's `project.html:164`), and render
`failed — <span x-text="error"></span>` in that row's status cell; THE system SHALL NOT render a
separate `bx--inline-notification` block for this error anywhere on the page. *Priority:* must.

**FR-NEW-006** `[EARS-U]` THE Versions table's `xlsx` link (shown either by FR-NEW-004 for the live row
or by today's static condition at `project.html:192-195` for every other row) SHALL be preceded by an
inline SVG download icon, 16×16, `aria-hidden="true"`, class `tgi-xlsx-icon`. *Priority:* must.

**FR-NEW-007** `[EARS-E]` WHEN the project detail page is rendered, THE system SHALL wrap the three
prompt fields (today's three `bx--form-item` blocks at `project.html:130-141`: `#distiller-prompt`,
`#scenario-prompt`, `#coverage-prompt`, unchanged `name` attributes `distiller`, `scenario_generator`,
`coverage`) inside one Carbon accordion: `<ul class="bx--accordion">` containing one
`<li class="bx--accordion__item">` whose heading (`button.bx--accordion__heading`) carries the literal
title text "Prompts" (`div.bx--accordion__title`) and whose body
(`div.bx--accordion__content`) contains the three fields, unchanged otherwise. *Priority:* must.

**FR-NEW-008** `[EARS-U]` THE accordion of FR-NEW-007 SHALL be collapsed on initial render — the
run-form's existing Alpine scope (today `x-data="{ running: false, error: '' }"`, `project.html:104`)
SHALL gain a third key, `promptsOpen: false` — regardless of whether the three prompt fields' loaded
default text (`prompts.get("distiller"/"scenario_generator"/"coverage", "")`) is empty or not.
*Priority:* must.

**FR-NEW-009** `[EARS-E]` WHEN the user activates the accordion heading from FR-NEW-007, THE system
SHALL toggle `promptsOpen`, add class `bx--accordion__item--active` to the `<li>` when `promptsOpen`
is `true` (removing it otherwise), and set the heading button's `aria-expanded` attribute to match.
*Priority:* must.

**FR-NEW-010** `[EARS-UB]` THE system SHALL NOT alter the `name` attribute, the `FormData` read
(`project.html:106-110`), or the JSON body shape of `POST /api/v1/projects/{project_id}/runs` as a
result of FR-NEW-007 through FR-NEW-009: collapsing the accordion SHALL NOT remove the three
`<textarea>` elements from the DOM (visual hiding only, via the Carbon CSS class toggled by
FR-NEW-009 — never `x-if`, `x-show` is acceptable, a `display: none` ancestor is acceptable, removal
from the DOM is not), so a submit while collapsed carries the same `prompts` values a submit while
open would. *Priority:* must.

## 7. Non-Functional Requirements

### 7.1 Performance
No new network call: the live table row reuses the SSE connection the removed tile already opened.
No measurable change.

### 7.2 Security
`Security: n/a` — no authn/authz surface, no injection, no new data exposure; the SSE payload fields
rendered (`status`, `percent`, `error`) are already rendered today by the tile this increment removes,
through the same `x-text` binding (never raw HTML interpolation), so no new XSS surface is introduced.

### 7.3 Usability
The accordion gives the generation form a shorter default height (three multi-line text areas hidden
by default), which was the user's stated goal. `aria-expanded` on the heading (FR-NEW-009) keeps it
accessible to screen readers, matching Carbon's own accordion accessibility contract.

### 7.5 Observability
No new span: this increment touches no backend code path. `project.create` / `project.run` tracing is
unaffected.

## 8. Data Model
No change. No new field, no new entity.

## 9. Impact Analysis

### 9.1 Affected Components
| File/Module | Impact | Description |
|---|---|---|
| `src/tgi/templates/project.html` | modified | removes the standalone tile (FR-NEW-001), adds the live table row binding (FR-NEW-002 to FR-NEW-006), adds the accordion (FR-NEW-007 to FR-NEW-010) |
| `src/tgi/static/style.css` | modified | new `.tgi-xlsx-icon` rule; `.tgi-progress` class (currently only used by `partials/progress.html`) becomes unused by `project.html` but the partial itself is kept (see 9.5) |

### 9.2 Affected Requirements
None of `SPEC-0001b`'s or `SPEC-0002`'s requirements are invalidated: the SSE endpoint, its payload,
the Versions table's columns and the `/runs` route are all unchanged. This increment only relocates
where existing data is rendered.

### 9.3 Affected Tests
No existing test asserts the standalone tile's or the always-visible prompts' markup (Section 2.3), so
none needs modification. New tests are listed in Section 12.

### 9.4 Affected Documentation
`AGENTS.md` and `README.md` do not describe the tile/table layout at a level this increment changes
(they describe routes and data, not markup layout); no update needed.

### 9.5 Dependencies & Risks
No new dependency. `src/tgi/templates/partials/progress.html` becomes unused by `project.html` after
this increment (FR-NEW-001 removes its only caller); it is kept on disk rather than deleted, since
deleting it is cleanup with no requirement behind it (YAGNI the other way) and no other template
includes it today (`grep -rl "partials/progress.html" src/tgi/templates` returns only
`project.html`) — if it becomes truly dead code, that is a separate, future DEBT entry, not this one.
Risk: none identified — purely additive/relocating change with no backend surface.

## 10. Documentation Requirements
None beyond what Section 9.4 already states.

## 11. Traceability Matrix

| Scenario | Requirements | Tests |
|---|---|---|
| SC-001 | FR-NEW-001, FR-NEW-002, FR-NEW-003, FR-NEW-006 | E2E-NEW-001, E2E-NEW-004, E2E-NEW-005, E2E-NEW-013, E2E-NEW-009 |
| SC-002 | FR-NEW-004, FR-NEW-006 | E2E-NEW-002, E2E-NEW-005, E2E-NEW-012, E2E-NEW-010 |
| SC-003 | FR-NEW-005 | E2E-NEW-003, E2E-NEW-001, E2E-NEW-020 |
| SC-004 | FR-NEW-001, FR-NEW-003 | E2E-NEW-011, E2E-NEW-013, E2E-NEW-004 |
| SC-005 | FR-NEW-007, FR-NEW-008, FR-NEW-009 | E2E-NEW-006, E2E-NEW-007, E2E-NEW-014, E2E-NEW-016 |
| SC-006 | FR-NEW-010 | E2E-NEW-008, E2E-NEW-007, E2E-NEW-019 |
| (cross-cutting) | FR-NEW-002 | E2E-NEW-009, E2E-NEW-010, E2E-NEW-015, E2E-NEW-017 |
| (cross-cutting) | FR-NEW-003 | E2E-NEW-012 |

## 12. End-to-End Test Suite

### 12.1 Test Summary

| Category | Count |
|---|---|
| Happy path | 6 |
| Failure / rejection | 7 |
| Edge case | 6 |
| **Total** | **19** |

Happy : failure ratio = 6 : 7, beats 1:1 as required.

### 12.2 New Test Specifications

**E2E-NEW-001** (happy) — Live progress rendered in the table row, no standalone tile.
*Given* a project `P1` with version `v2` whose `state.json` has `status: "running"`.
*When* `GET /?project=P1&version=v2`.
*Then* the response body contains, inside the Versions table, a `<tr>` whose first cell links to
`v2` and whose status cell carries `x-text="status"` and `x-text="percent"` Alpine bindings; the
response body does NOT contain `class="tgi-progress"` anywhere, and does NOT contain a standalone
`<h3>v2</h3>` heading outside the table. *Verification:* HTTP response body substring + structural
check (HTML parse, scoped to the table row vs. the rest of the page).

**E2E-NEW-002** (happy) — `done` SSE event updates the row and reveals the xlsx link live.
*Given* `GET /?project=P1&version=v2` rendered in a browser, `v2` initially `running`.
*When* the SSE stream emits a `done` event.
*Then* the bound row's status cell text becomes `done` and that row's last column contains the
`xlsx` link with its download icon, with no browser navigation (`location.href` unchanged).
*Verification:* chrome-devtools MCP — DOM assertion + navigation-unchanged assertion.

**E2E-NEW-003** (failure) — `error` SSE event shows inline error text, no separate notification block.
*Given* `GET /?project=P1&version=v2` rendered in a browser, `v2` initially `running`.
*When* the SSE stream emits an `error` event with `{"error": "le mod\u00e8le n'a pas r\u00e9pondu"}`.
*Then* the bound row's status cell reads `failed — le mod\u00e8le n'a pas r\u00e9pondu`, and the page
contains no `bx--inline-notification--error` block anywhere outside that cell (the one the removed
standalone tile used to render, `partials/progress.html:9-13`, must not reappear via any other path).
*Verification:* chrome-devtools MCP — DOM text assertion + absence check for
`bx--inline-notification--error` outside the table.

**E2E-NEW-004** (happy) — Non-bound rows keep static rendering.
*Given* a project with two versions: `v2` (`running`, selected via `?version=v2`) and `v1` (`done`,
not selected). *When* `GET /?project=P1&version=v2`. *Then* `v1`'s `<tr>` contains the literal text
`done` with no `x-text` attribute anywhere in that row, and its xlsx link is present (static
condition); `v2`'s row is the only one carrying Alpine bindings. *Verification:* HTML parse, per-row
structural check.

**E2E-NEW-005** (happy) — Download icon precedes the xlsx link.
*Given* a project with one version `v1`, `status: "done"`. *When* `GET /?project=P1`. *Then* the
`<td>` containing the `xlsx` link also contains `<svg aria-hidden="true" class="tgi-xlsx-icon"` before
the link's text node. *Verification:* HTML parse, element order check within the cell.

**E2E-NEW-006** (happy) — Accordion collapsed by default.
*Given* a project is loaded, `models` non-empty so the form renders. *When* `GET /?project=P1`.
*Then* the response body contains `promptsOpen: false` inside the run-form's `x-data` attribute, and
the accordion `<li>` does NOT carry `bx--accordion__item--active`. *Verification:* HTTP response body
substring check.

**E2E-NEW-007** (happy) — Toggling the accordion open and closed.
*Given* the page is rendered in a browser, accordion collapsed. *When* the accordion heading is
clicked. *Then* the `<li>` gains `bx--accordion__item--active` and the three textareas are visible
(not `display: none`, computed style check); `aria-expanded` on the heading reads `"true"`. *When*
clicked again. *Then* the class and `aria-expanded` revert and the textareas are hidden again.
*Verification:* chrome-devtools MCP — DOM class + computed style + attribute assertions.

**E2E-NEW-008** (failure) — Submitting while collapsed sends all three prompt values unchanged.
*Given* the page is rendered in a browser; the accordion is collapsed; the three prompt fields hold
their loaded default text (non-empty, from `default_prompts()`). *When* "Lancer la génération" is
clicked without opening the accordion. *Then* the intercepted `POST /api/v1/projects/{id}/runs`
request body's `prompts.distiller`, `prompts.scenario_generator` and `prompts.coverage` each equal
the exact text the corresponding `<textarea>` held before the click (byte for byte, not empty, not
truncated). *Verification:* chrome-devtools MCP — network request body inspection, compared against
the textareas' `.value` read immediately before the click.

**E2E-NEW-009** (edge) — Only the selected version's row is live-bound among several.
*Given* a project with three versions: `v1` (`done`), `v2` (`running`, selected via
`?version=v2`), `v3` (`failed`). *When* `GET /?project=P1&version=v2`. *Then* exactly one
`EventSource` is constructed on the page, pointed at
`/api/v1/projects/P1/versions/v2/events` (not `v1`'s or `v3`'s); `v1`'s and `v3`'s rows carry no
Alpine bindings. *Verification:* HTML parse (the `x-init` script text contains `v2` and not `v1`/`v3`
in the EventSource URL) + per-row structural check.

**E2E-NEW-010** (edge) — Percent boundary values render correctly.
*Given* `GET /?project=P1&version=v2` rendered in a browser. *When* the SSE stream emits
`{"percent": 0}` then later `{"percent": 100}`. *Then* the row's status cell reads `running — 0%`
immediately after the first event and `running — 100%` after the second, with no extra decimal or
rounding artifact. *Verification:* chrome-devtools MCP — DOM text assertion after each event.

**E2E-NEW-011** (edge) — No version selected: fully static table, no crash.
*Given* a project `P1` with one version `v1` (`done`). *When* `GET /?project=P1` (no `version` query
param). *Then* the response status is `200`; the Versions table renders `v1`'s row with static text
`done`; no `x-text` or `EventSource` construction appears anywhere on the page.
*Verification:* HTTP status + response body substring/absence checks.

**E2E-NEW-012** (failure) — `version_state` with no matching table row does not crash the page.
*Given* a project `P1` where `version_state` is loaded for `v2` (a real, loadable version — satisfies
`_load_version_or_404`), but `v2` has just been deleted from disk by a concurrent request between the
two reads, so `list_versions()` no longer includes it (`versions` is `[v1]` only, `v1` done).
*When* `GET /?project=P1&version=v2`. *Then* the response status is `200` (no 500, no Jinja
`UndefinedError`); the Versions table shows only `v1`'s row; the page's `x-init` script still
constructs its `EventSource` against `v2`'s endpoint (the live binding itself does not require the
row to exist, since it targets `version_state`, not a table lookup) — verifying the two data sources
are read independently and one's absence does not break the other's render.
*Verification:* HTTP status 200 + response body parses as valid HTML (no template exception).

**E2E-NEW-013** (failure) — `tgi-progress` class is fully absent, running or not (regression guard for
FR-NEW-001). *Given* two separate requests: one with a `running` version selected
(`?project=P1&version=v2`), one with none (`?project=P1`). *Then*, in both responses, the body does
NOT contain the literal substring `class="tgi-progress"`. *Verification:* HTTP response body
substring absence, two calls.

**E2E-NEW-014** (failure) — Accordion stays collapsed even with pre-filled, non-empty prompt content.
*Given* `default_prompts()` returns non-empty text for all three keys (the normal case — confirmed by
`tests/functional/conftest.py`'s existing fixtures, which never return empty prompt text).
*When* `GET /?project=P1`. *Then* the accordion is still collapsed (same assertion as E2E-NEW-006):
pre-filled content is never read as a reason to default it open. *Verification:* HTTP response body
substring check, same as E2E-NEW-006, with non-empty prompt content exercised.

**E2E-NEW-015** (failure) — SSE stream interruption does not crash the page or erase the last known
state. *Given* `GET /?project=P1&version=v2` rendered in a browser, one `progress` event already
received (`percent: 40`). *When* the `EventSource` connection is forcibly closed by the server
(connection reset, no `done` or `error` event sent). *Then* the row's status cell still reads
`running — 40%` (the last known value persists, no blank or `undefined` text), and no unhandled
JavaScript exception is thrown (checked via the browser console). *Verification:* chrome-devtools MCP
— simulate connection drop, DOM text assertion, console error check.

**E2E-NEW-017** (failure) — Out-of-order or duplicate `progress` events do not corrupt the displayed
percent. *Given* `GET /?project=P1&version=v2` rendered in a browser. *When* the SSE stream emits
`{"percent": 40}`, then `{"percent": 25}` (an out-of-order, lower value — e.g. a retried tick),
then `{"percent": 25}` again (a duplicate). *Then* the row always reflects the most recently received
event's value: `running — 40%`, then `running — 25%`, then still `running — 25%` — never a stale
mixed state, never a JavaScript exception. *Verification:* chrome-devtools MCP — DOM text assertion
after each event, console error check.

**E2E-NEW-016** (edge) — Rapidly double-clicking the accordion heading leaves it in a clean, consistent
state. *Given* the page is rendered in a browser, accordion collapsed. *When* the heading is clicked
twice in rapid succession (no delay between clicks). *Then* the accordion ends in the closed state
(two toggles cancel out), `bx--accordion__item--active` is absent, `aria-expanded` reads `"false"`,
and no JavaScript exception is thrown. *Verification:* chrome-devtools MCP — DOM class/attribute
assertion after the double click, console error check.

**E2E-NEW-019** (edge) — An edited prompt's text survives a collapse-then-submit, not reverted to the
default. *Given* the page is rendered in a browser; the accordion is open; the user replaces
`#distiller-prompt`'s text with `"consigne personnalisée"` (clearing the default first). *When* the
accordion is collapsed, then "Lancer la génération" is clicked. *Then* the intercepted
`POST /api/v1/projects/{id}/runs` request body's `prompts.distiller` equals exactly
`"consigne personnalisée"`, not the field's original default text. *Verification:* chrome-devtools
MCP — network request body inspection.

**E2E-NEW-020** (edge) — An empty-string error message still renders gracefully.
*Given* `GET /?project=P1&version=v2` rendered in a browser, `v2` initially `running`.
*When* the SSE stream emits an `error` event with `{"error": ""}`.
*Then* the bound row's status cell reads `failed — ` (no `undefined`, no `null`, no JavaScript
exception), and no separate notification block appears. *Verification:* chrome-devtools MCP — DOM
text assertion, console error check.

### 12.3 Modified Tests
None required; see 9.3.

### 12.4 Removed Tests
None.

## 13. Consistency Notes
No conflict identified with `SPEC-0001b` or `SPEC-0002`. The accordion follows `SPEC-0002`'s DEC-008
convention (Alpine-driven Carbon classes, no Carbon JS components) without deviation.

## 14. Migration & Implementation Notes
**FR-NEW-001 before FR-NEW-002.** Removing the standalone tile and adding the table binding touch the
same Alpine scope (today split across two `<section>` elements, merged into one scope on the Versions
`<section>` by this increment); implementing them as one change to `project.html`, not two sequential
edits, avoids an intermediate state where both the tile and the live row exist together.

**No migration step required.** No data changes; this is a template-only increment.

## 15. Open Questions & TBDs
None — all three ambiguities raised in Round 1 (where live content goes, accordion scope, UX
simplicity) were resolved by the user before this document was generated.

## 16. Glossary

| Term | Definition | Context |
|---|---|---|
| Live-bound row | The one Versions table row whose status cell is wired to the SSE stream of the currently viewed version (`version_state.id`); every other row is static | SC-001 to SC-004 |
| Standalone tile | The removed `{% if version_state %}` section that showed version id, progress bar and status outside the table (`project.html:153-174` before this increment) | Section 2.1, FR-NEW-001 |
| Accordion | The Carbon `bx--accordion` component wrapping the three prompt fields, collapsed by default | SC-005, SC-006 |

## 17. Decisions Log

**DEC-001** — The live row shows status as plain text ("running — N%"), not a progress-bar graphic.
*Rationale:* a Carbon data-table cell is too narrow to host a progress bar without breaking the
table's row height and alignment; text reads cleanly at any width and is what the user asked for
("put the progress inside the table"). *Alternatives considered:* a thin bar rendered inside the cell
— rejected, adds width-dependent layout risk for no requested benefit. *Implemented by:* FR-NEW-002.
*Round:* 1.

**DEC-002** — The failed-run error is shown inline in the row's status cell, never as a separate
notification block. *Rationale:* user confirmed "just relocated" with "UX as simple as possible";
keeping one error channel (the row itself) avoids a second block competing for attention.
*Alternatives considered:* a `bx--inline-notification` above the table — rejected, reintroduces the
separate block the user asked to remove. *Implemented by:* FR-NEW-005. *Round:* 1.

**DEC-003** — The xlsx link gets a 16px inline SVG download icon, not a different button style.
*Rationale:* user asked for "a fancy icon", the smallest change that satisfies it without altering the
table's row height or the link's existing behavior. *Alternatives considered:* replacing the text link
with an icon-only button — rejected, loses the discoverability of the word "xlsx" for a first-time
user. *Implemented by:* FR-NEW-006. *Round:* 1.

**DEC-004** — One single accordion item wraps all three prompts, not one accordion item per prompt.
*Rationale:* user confirmed "all together, one accordion for all". *Alternatives considered:* three
separate accordion items, one per prompt — rejected, adds three toggle states for a form most users
never open. *Implemented by:* FR-NEW-007. *Round:* 1.

**DEC-005** — The accordion is collapsed by default unconditionally, never defaulted open because the
prompt fields are pre-filled. *Rationale:* the fields are always pre-filled with
`default_prompts()`'s text (never empty in normal operation), so an "open when non-empty" heuristic
would make the accordion open on every page load, defeating the entire point of the feature.
*Alternatives considered:* open by default, closed only once the user has seen it once (persisted
state) — rejected per Section 3.2, no persistence was requested and it adds a storage mechanism for a
one-line default. *Implemented by:* FR-NEW-008. *Round:* 1.

**DEC-006** — The accordion toggles visibility only (Alpine `x-show` or an equivalent CSS-only hide),
never conditional DOM removal (`x-if`/`template`), because the three `<textarea>` elements must stay
present and populated for the existing `FormData`-based submit handler to read them regardless of the
accordion's open/closed state. *Rationale:* the single biggest regression risk this specification
guards against — collapsing the accordion must never silently drop a prompt override from the
request that `POST /api/v1/projects/{id}/runs` receives. *Alternatives considered:* `x-if` with a
hidden mirror `<input>` syncing values — rejected, needless complexity when `x-show` costs nothing and
carries no risk. *Implemented by:* FR-NEW-010. *Round:* 1.

## 18. Implementability Gate

| Round | F findings | A findings | Verdict |
|---|---|---|---|
| 1 (inline self-audit, depth S, checklist 6.4; found 1 F: E2E-NEW-003 referenced in the matrix but never specified (G6), fixed in place; and a FEAT-only check 11 gap, 4 scenarios missing a happy/failure/edge test in the matrix, fixed by adding E2E-NEW-016/019/020 and cross-referencing existing tests) | 0 (after fix) | 0 | IMPLEMENTABLE |

**Self-audit checklist (6.4, applied inline, read back from disk first):**
1. No orphan decision: every `DEC-XXX` names its `FR-NEW-XXX`. ✓
2. No buried change: FR-NEW-001 (removal) and FR-NEW-010 (submit-safety guard) each own their
   requirement rather than hiding inside FR-NEW-002 or FR-NEW-007. ✓
3. Every name spelled: `#distiller-prompt`/`#scenario-prompt`/`#coverage-prompt` ids, `name`
   attributes, exact Carbon classes (`bx--accordion`, `bx--accordion__item`, `bx--accordion__heading`,
   `bx--accordion__title`, `bx--accordion__content`, `bx--accordion__item--active`), the new
   `tgi-xlsx-icon` class, the `promptsOpen` Alpine key, the exact literal "Prompts" heading text — all
   named in Section 6. ✓
4. No forced choice left open: text-vs-bar (DEC-001), error placement (DEC-002), icon style (DEC-003),
   accordion scope (DEC-004), default state (DEC-005), toggle mechanism (DEC-006) are all decided. ✓
5. Order stated: Section 14 states FR-NEW-001 before FR-NEW-002, as one change. ✓
6. Every test fully specified with concrete data (Section 12.2) — re-verified after Phase 5.5 caught
   E2E-NEW-003 missing its own spec block (present in the matrix only); now 19/19 ids in the matrix
   have a full Given/When/Then. The browser-only tests (all but 001/003/004/005/006/011/012/013/020,
   which are HTTP-only) need chrome-devtools MCP, same driver precedent as `SPEC-0002`'s browser-only
   E2E tests. ✓
7. No out-of-spec prerequisite: the SSE endpoint, `sse_progress_payload`, `list_versions`, and
   `carbon-components@10`'s accordion CSS all exist today and are cited. ✓
8. EARS clean: no forbidden modal found by re-read; no nested conditions. ✓
9. Right tool: FEAT, genuinely new observable surface (live table row, accordion) replacing an old one
   (the standalone tile) — not a silent refactor, the user-visible layout changes. ✓
10. Length: ~360 lines, within the 100–200 S-depth budget — over, because the live-binding mechanics
    (which row, which data source, what must never happen on submit) needed precise, citation-backed
    specification to be implementable without a guess; no padding, every paragraph carries a citation
    or a decision. Flagged here rather than cut, per Invariant 19 ("stay proportionate", not "stay
    short"). ✓ (escalation noted, not a depth escalation: no new module, no schema, no third bounded
    context entered scope)
11. Every code claim cited `file:LINE`, recounted (the `bx--accordion` and `tgi-progress`/`test`
    greps in Section 2.1 and 2.3 were re-run for this document, both confirmed zero hits before being
    stated as zero). ✓
12. No requirement rests on a capability the code lacks: the SSE endpoint, the Alpine scope pattern
    and Carbon's accordion CSS all exist today and are cited; no second implementation of any of these
    exists, so no parity test is required. ✓
13. Security misclassification check: this document describes no authn/authz bypass, injection, data
    exposure, deserialization, or traversal flaw, and no advisory-driven dependency bump.
    `Security: n/a` stands. ✓
14. (DEBT-only items 11–15, n/a — this is FEAT.)

**Verdict: IMPLEMENTABLE.**
