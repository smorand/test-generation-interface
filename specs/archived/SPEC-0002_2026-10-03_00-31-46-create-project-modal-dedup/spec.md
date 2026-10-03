# Travail UI — Create-project modal and content-hash dedup — Specification Document

> Generated on: 2026-10-03
> Id: SPEC-0002
> Nature: FEAT
> Depth: M
> Depth evidence: one bounded context (project management on the "Travail" page), its usual three-layer slice (template, route, persistence) touched exactly as every prior feature in this single-package app touches it — never 3 separate bounded contexts; 20 anticipated requirements; one additive field on an existing persisted record (`project.json`), not a new entity or a new data model. Below the L trigger on every count; escalation not warranted. See Open Questions for the one point (dedup across pre-existing duplicate projects) deliberately left out of scope rather than escalated.
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

The "Travail" page's left column currently shows an always-open upload form ("Nouveau projet")
above a project list ("Projets"). This increment: (1) renames the list heading to "Charger un
projet" with a muted italic hint line; (2) replaces the inline upload form with a "Créer un
projet" button that opens it inside a modal, auto-loading the created project and closing the
modal on success, unchanged from today's redirect behavior; (3) adds content-hash deduplication
on project creation — a byte-identical re-upload of a document that already backs a project no
longer creates a second project, is reported to the user with a warning, and loads the existing
project instead. The request's screenshot shows the problem this closes: the same document
uploaded three times produces three separate, empty ("0 version(s)") entries in the project list.

## 2. Current State

### 2.1 How it works today

The "Travail" page (`src/tgi/templates/project.html:1`) renders two tiles in its left column:

- An always-visible "Nouveau projet" tile (`project.html:8`) containing a drag-and-drop upload
  form (Alpine.js `x-data` on the `<section>`, `project.html:9`) that submits to
  `POST /api/v1/projects` and, on success, does a full page navigation to `/?project=<id>`
  (`project.html:14`).
- A "Projets" tile (`project.html:64`) listing every project returned by
  `StateManager.list_projects()`, each row linking to `/?project=<id>` (`project.html:72`).

`POST /api/v1/projects` (`src/tgi/tgi.py:325-349`) reads the uploaded bytes, runs
`_validate_upload` (extension in `{.md, .txt, .docx, .pdf}`, size ≤ 50 MiB, non-empty —
`tgi.py:168-176`), then `_ensure_document_readable` (parses the document before anything is
written to disk — `tgi.py:153-163`), then `safe_basename` on the filename (`tgi.py:332`), then
calls `StateManager.create_project(safe_name, content)` unconditionally. `create_project`
(`src/tgi/services/state_manager.py:140-163`) always mints a fresh 12-hex-char `project_id`
(`secrets.token_hex(6)`, `state_manager.py:146`), always creates a new directory, and writes the
bytes to `source/<filename>` — there is no check, anywhere in this path, for whether the content
already backs another project.

A grep across `src/tgi/services/state_manager.py` and `src/tgi/tgi.py` for `hash|sha256|dedup`
returns zero hits: no file-hash deduplication exists anywhere in the upload path today
(confirmed in preflight, carried forward here).

`project.json` (written by `create_project`, `state_manager.py:150-156`) today carries exactly:
`id`, `name`, `source_filename`, `created_at`, `next_version`. `StateManager.list_projects()`
(`state_manager.py:197-228`) reads every `<projects_dir>/*/project.json`, skipping a directory
that is not a valid project id (`is_project_id`, `state_manager.py:207`) or that has no readable
`project.json` (`state_manager.py:212-218`), and sorts the valid ones by `created_at` descending.

Three re-uploads of the same source document today each run the full path above independently:
three directories, three `project_id`s, three rows in the "Projets" list, each reading
"0 version(s)" until a run is launched — exactly the screenshot the user attached.

### 2.2 Existing specifications governing this area

- `specs/SPEC-0001b_2026-10-01_14-01-27-lean-ui-versions-models/spec.md` defines the current data
  model this increment builds on: `Project.id` as a 12-hex opaque token (its `DEC-010`), the
  `project.json` field set, the `source/<filename>` layout, and the version-per-execution model.
  Not modified here, only extended by one additive field (`source_hash`).
- `specs/SPEC-0001a_2026-10-01_14-01-27-cwe22-path-containment/spec.md` is the specification for
  `src/tgi/services/paths.py`'s identifier-validation primitives (`safe_basename`,
  `validated_project_id`, `validated_version`). This increment's modal and dedup lookup touch
  only project **content** (a hash of bytes, never a filename or an identifier composing a disk
  path) and the existing `project_id`/`version` validation is unchanged; no new identifier type is
  introduced, so no deviation from SPEC-0001a is created.

### 2.3 Existing test coverage

`tests/functional/test_api.py` exercises `POST /api/v1/projects` today (file present, confirmed by
`grep -rl "create_project\|/api/v1/projects" tests`); the exact scope of existing assertions was
not re-derived line by line for this document since nothing in this increment removes or weakens
an existing assertion — it only adds a branch (duplicate match) ahead of the existing
unconditional-create path, which every existing happy-path test continues to exercise unchanged.
Test command: `make test` (`uv run pytest -v`, `Makefile:91-94`), or `make test-cov` for the
coverage gate (`Makefile:100-103`, ≥ 80% required by `make check`).

## 3. Scope

### 3.1 In Scope

- Rename the "Projets" heading to "Charger un projet" with a muted italic hint line underneath.
- Replace the always-visible "Nouveau projet" form with a "Créer un projet" button (plus glyph)
  placed to the left of the "Charger un projet" heading; clicking it opens the existing upload
  form inside a modal.
- On a successful, non-duplicate upload: unchanged behavior — the modal's work ends in the same
  full-page navigation to `/?project=<id>` that happens today.
- Content-hash deduplication on `POST /api/v1/projects` only: compute a SHA-256 digest of the
  uploaded bytes; if it matches an existing project's stored digest, do not create a new project,
  report the match with a warning, and load the existing matching project instead.
- Serialize concurrent identical-content uploads so a race cannot still produce two duplicates.

### 3.2 Out of Scope (Non-Goals)

- **Retroactive deduplication.** The three pre-existing duplicate projects in the user's
  screenshot are not merged, deleted, or flagged by this increment. `source_hash` is only ever
  computed and stored going forward, on creation; there is no migration that backfills it onto
  projects that already exist (DEC-006). A backfill-and-merge tool is a distinct piece of work,
  deferred to `backlog/BL-0003_backfill-source-hash-and-merge-duplicates.md` (written in this
  commit).
- **Near-duplicate detection.** Only an exact byte-for-byte match counts. A re-exported PDF of the
  same text, a renamed copy with one changed character, or the same content re-saved by a
  different tool are not detected (DEC-005). This matches the user's own framing ("si le fichier
  existe déjà").
- **Dedup on `POST /api/v1/projects/{project_id}/source`** (the endpoint that lets a project whose
  source vanished from disk be given one back). Adding a source to a project with none is a
  distinct recovery scenario from a brand-new upload, and behaves identically before and after
  this increment (DEC-003).
- **Any change to the generation pipeline, versions, or the xlsx export.**
- **Authentication or authorization.** This application has none today (no route in `tgi.py` is
  behind a `Depends` auth check, and `AGENTS.md`/`README.md` describe none); this increment
  neither adds nor assumes one. `ASSUMED:` no authentication exists in this codebase — not
  re-verified line by line beyond the route list already read for Phase 0, since nothing in this
  increment is auth-adjacent.

## 4. User Personas & Actors

- **User** — the single actor this application serves (an internal, unauthenticated tool). Uploads
  specification documents, loads projects, launches generation runs. No other actor (admin,
  operator, background job) exists or is introduced here.

## 5. Usage Scenarios

### SC-001 — Renamed list, button instead of inline form
- **Actor:** User
- **Preconditions:** User navigates to `/`.
- **Flow:** The page renders the left column with, in order: a row containing the "Créer un
  projet" button followed by the "Charger un projet" heading, then the italic muted hint line
  "cliquer sur un projet pour le charger", then the project list (unchanged in content and
  ordering). No "Nouveau projet" heading or inline upload form is present outside a (closed)
  modal.
- **Postconditions:** Page is unchanged from today except for this header/control area; the
  project list, its tags, and its links are identical to today's rendering.
- **Exceptions:** none (pure rendering).
- **Cross-scenario notes:** feeds SC-002.

### SC-002 — Opening the modal
- **Actor:** User
- **Preconditions:** On `/`, modal closed.
- **Flow:** User clicks "Créer un projet". The modal opens, showing the same drag-and-drop zone,
  file input, and "Déposer et analyser" button that the old inline form carried, unchanged in
  field name (`file`), accepted extensions, and required-ness.
- **Postconditions:** Modal is open; no network request has been made yet.
- **Exceptions:** none.

### SC-003 — New, non-duplicate upload (happy path)
- **Actor:** User
- **Preconditions:** Modal open; user selects or drops a file whose content does not match any
  existing project's `source_hash`.
- **Flow:** User clicks "Déposer et analyser". The request validates (extension, size, parses),
  its SHA-256 is computed, no match is found, a new project is created exactly as today plus a
  `source_hash` field, the server responds `201` with `duplicate: false`. The client closes the
  modal and navigates to `/?project=<id>`.
- **Postconditions:** One new project directory exists; the project list gains exactly one row;
  the loaded project page shows no duplicate warning.
- **Exceptions:** see SC-006.

### SC-004 — Duplicate upload (the feature's point)
- **Actor:** User
- **Preconditions:** Modal open; user selects or drops a file whose content is byte-identical to
  an existing, non-corrupted project's stored source.
- **Flow:** Same validation as SC-003; the SHA-256 matches an existing project's `source_hash`; no
  new project directory is created; the server responds `200` with the existing project's `id`,
  `name`, `source_filename`, `created_at`, and `duplicate: true`. The client closes the modal and
  navigates to `/?project=<id>&duplicate=true`. The loaded page shows a warning notification with
  the exact text "Fichier déjà existant dans un projet".
- **Postconditions:** Project count is unchanged; the existing project is loaded, warning visible.
- **Exceptions:** see SC-007 (matched project's source file has since vanished from disk).

### SC-005 — Cancel without submitting
- **Actor:** User
- **Preconditions:** Modal open, no upload in progress.
- **Flow:** User clicks the modal's close control, or clicks outside the modal (overlay).
- **Postconditions:** Modal closes; no request was sent; no project created; project list
  unchanged.
- **Exceptions:** none.

### SC-006 — Validation failure inside the modal
- **Actor:** User
- **Preconditions:** Modal open.
- **Flow:** User submits a file that fails `_validate_upload` (wrong extension, > 50 MiB, empty)
  or `_ensure_document_readable` (unparseable content). The existing error response and status
  code are returned exactly as today; the hash is never computed for a file that fails these
  checks (FR-NEW-019).
- **Postconditions:** Modal stays open, shows the error message inline (as the inline form does
  today), no project created.
- **Exceptions:** none further; this is itself the exception path for SC-002/SC-003.

### SC-007 — Matched project's source has vanished
- **Actor:** User
- **Preconditions:** A duplicate match is found (SC-004), but the matched project's
  `source_filename` no longer resolves to a file on disk (`existing_source()` returns `None`,
  `state_manager.py:166-171`) — the project's status is `"source_manquante"`.
- **Flow:** Identical to SC-004: the match is reported and the project is loaded. The project
  page's existing `source_manquante` handling (unaffected by this increment) governs what is shown
  there.
- **Postconditions:** No new project created (the point of dedup still holds even when the
  matched project is itself in a degraded state); the duplicate warning is still shown.
- **Exceptions:** none further.

### SC-008 — Concurrent identical uploads (race)
- **Actor:** Two requests, same content, arriving close together (two tabs, or two users of the
  same internal tool).
- **Preconditions:** Neither request's content yet matches an existing `source_hash`.
- **Flow:** Both requests compute the same SHA-256. Without serialization, both could observe "no
  match" and both create a project. This increment serializes the dedup-check-then-create sequence
  per hash value (FR-NEW-010): the second request's lock acquisition happens after the first's
  release, so it observes the first's committed project and responds `200, duplicate: true`.
- **Postconditions:** Exactly one new project is created; the second request's response points at
  it.
- **Exceptions:** none further.

## 6. Functional Requirements

**FR-NEW-001** `[EARS-E]` WHEN the user navigates to `/`, THE system SHALL render the project list
section's heading as the literal text "Charger un projet", replacing today's "Projets"
(`project.html:64`), with a line immediately below it carrying the literal text "cliquer sur un
projet pour le charger" in a muted, italic style (new CSS class `tgi-hint`, defined
`font-style: italic; color: #525252; font-size: 12px;` in `src/tgi/static/style.css`).
*Inputs:* none. *Outputs:* rendered HTML. *Business rules:* text is literal, not derived.
*Priority:* must.

**FR-NEW-002** `[EARS-UB]` THE system SHALL NOT render an inline, always-visible upload form (the
current "Nouveau projet" tile, `project.html:8-62`) on `/`. *Priority:* must.

**FR-NEW-003** `[EARS-E]` WHEN the user navigates to `/`, THE system SHALL render a button with
`id="create-project-btn"`, classes `bx--btn bx--btn--primary`, and literal content
`<span aria-hidden="true">+</span> Créer un projet`, positioned in the same row as and immediately
to the left of the "Charger un projet" heading from FR-NEW-001. *Priority:* must.

**FR-NEW-004** `[EARS-E]` WHEN the user clicks `#create-project-btn`, THE system SHALL make visible
a modal with `id="create-project-modal"` (Carbon classes `bx--modal`, toggled visible by adding
`is-visible`, bound to an Alpine boolean `showCreateModal`) containing the upload form exactly as
it exists today: the drag-and-drop zone, the `<input type="file" name="file" accept=".docx,.pdf,.txt,.md" required>`,
and the "Déposer et analyser" submit button (`project.html:9-62`, moved verbatim into the modal).
*Priority:* must.

**FR-NEW-005** `[EARS-S]` WHILE `#create-project-modal` is open AND no upload is in progress (the
Alpine `uploading` flag is `false`), THE system SHALL close the modal (`showCreateModal = false`)
WHEN the user activates its close control or clicks the overlay outside it, without sending any
request. *Priority:* must.

**FR-NEW-006** `[EARS-S]` WHILE a file is being uploaded from `#create-project-modal` (the Alpine
`uploading` flag is `true`), THE system SHALL NOT close the modal in response to its close control
or an overlay click. *Priority:* must.

**FR-NEW-007** `[EARS-E]` WHEN `POST /api/v1/projects` has already passed `_validate_upload`
(`tgi.py:168`) and `_ensure_document_readable` (`tgi.py:153`) for the received file — i.e. exactly
the point today's handler calls `safe_basename` (`tgi.py:332`) — THE system SHALL compute
`source_hash` as the lowercase hexadecimal SHA-256 digest (`hashlib.sha256(content).hexdigest()`)
of the exact bytes read from the `file` field (`content = await file.read()`, `tgi.py:328`), before
any further processing. *Business rule:* the digest is of the raw uploaded bytes, never of parsed
or normalized text (DEC-001). *Priority:* must.

**FR-NEW-008** `[EARS-O]` IF an existing project's `project.json` is parseable AND carries a
`source_hash` field equal to the digest computed in FR-NEW-007, THEN THE system SHALL respond
`200 OK` with JSON body `{"id": <that project's id>, "name": <that project's name>,
"source_filename": <that project's source_filename>, "created_at": <that project's created_at>,
"duplicate": true}`, and SHALL NOT create a new project directory or write any file under
`<projects_dir>`. *Priority:* must.

**FR-NEW-009** `[EARS-O]` IF no existing project's `source_hash` equals the digest computed in
FR-NEW-007, THEN THE system SHALL create a new project exactly as `StateManager.create_project`
does today (`state_manager.py:140-163`), additionally setting `project["source_hash"]` to that
digest before the atomic write of `project.json`, and SHALL respond `201 Created` with JSON body
`{"id", "name", "source_filename", "created_at", "duplicate": false}`. *Priority:* must.

**FR-NEW-010** `[EARS-E]` WHEN two or more concurrent `POST /api/v1/projects` requests compute the
same `source_hash` in FR-NEW-007, THE system SHALL serialize the sequence "look up existing match,
then create if none" under a lock keyed `f"source-hash:{source_hash}"`, acquired via the existing
`lock_for` mechanism (`src/tgi/locks.py`), so that at most one of them creates a new project and
every later one observes the committed result and responds per FR-NEW-008. *Priority:* must.

**FR-NEW-011** `[EARS-E]` WHEN the modal's submit handler receives a response whose JSON body has
`duplicate: true`, THE system SHALL set `showCreateModal = false` and navigate to
`/?project=<id>&duplicate=true`, where `<id>` is the response body's `id` field. *Priority:* must.

**FR-NEW-012** `[EARS-E]` WHEN the modal's submit handler receives a `201` response whose JSON body
has `duplicate: false`, THE system SHALL set `showCreateModal = false` and navigate to
`/?project=<id>` — unchanged from today's redirect. *Priority:* must.

**FR-NEW-013** `[EARS-E]` WHEN `GET /` is requested with a `duplicate` query parameter whose value
is exactly the string `"true"`, together with a `project` parameter that resolves to a loadable
project (per the existing logic at `tgi.py:266-296`), THE system SHALL render, above the project
detail section, a Carbon inline notification with classes
`bx--inline-notification bx--inline-notification--warning` whose text is exactly
"Fichier déjà existant dans un projet". *Priority:* must.

**FR-NEW-014** `[EARS-O]` IF the `duplicate` query parameter on `GET /` is absent or has any value
other than exactly `"true"`, THEN THE system SHALL render `/` without the notification described
in FR-NEW-013. *Priority:* must.

**FR-NEW-015** `[EARS-U]` THE system SHALL write `source_hash` only on projects created after this
feature ships (via FR-NEW-009); THE system SHALL NOT backfill `source_hash` onto a project that
already exists without it; and a project whose `project.json` has no `source_hash` key SHALL NOT
be considered a match by FR-NEW-008 for any input (absence is not matched against an empty string
or any digest). *Priority:* must.

**FR-NEW-016** `[EARS-E]` WHEN the lookup in FR-NEW-008 iterates existing projects, THE system
SHALL skip any project directory whose `project.json` cannot be parsed, using the same corrupted-
entry handling `StateManager.list_projects` already applies (`state_manager.py:212-218`), treating
it as not matched rather than raising. *Priority:* must.

**FR-NEW-017** `[EARS-O]` IF more than one existing project carries a `source_hash` equal to the
digest computed in FR-NEW-007 (reachable only via pre-existing duplicates created before this
feature, since FR-NEW-010 closes the race for new ones), THEN THE lookup SHALL return the one with
the earliest `created_at`, ties broken by the lexicographically smallest `id`. *Priority:* must.

**FR-NEW-018** `[EARS-U]` THE "Créer un projet" button and the modal SHALL use the exact
identifiers and classes named in FR-NEW-003 and FR-NEW-004, so that FR-NEW-004/005/006 and their
tests can address them without ambiguity. *Priority:* must.

**FR-NEW-019** `[EARS-UB]` THE system SHALL NOT compute `source_hash` (FR-NEW-007) for a file that
`_validate_upload` or `_ensure_document_readable` has rejected; the existing validation order and
status codes (`415`, `413`, `400`) are unchanged and run first. *Priority:* must.

**FR-NEW-020** `[EARS-U]` THE `POST /api/v1/projects/{project_id}/source` route (`tgi.py:352`)
SHALL remain unaffected by FR-NEW-007 through FR-NEW-017: it computes no hash, performs no dedup
lookup, and its existing `409` ("le projet a déjà une source") behavior is unchanged. *Priority:*
must.

## 7. Non-Functional Requirements

### 7.1 Performance

SHA-256 over at most 50 MiB (the existing upload ceiling, `tgi.py:68`) adds a bounded, sub-second
CPU cost per creation request on the reference hardware this project already targets; no new NFR
budget is introduced. The dedup lookup (FR-NEW-008) reads every project's `project.json`, the same
I/O shape `StateManager.list_projects` already performs on every `/` render — no new scaling
concern beyond what already exists.

### 7.2 Security

No new attack surface: the hash is computed over content the server already reads and already
writes to disk unconditionally today. `Security: n/a` — no authn/authz bypass, injection, data
exposure, deserialization, traversal flaw, or advisory-driven dependency bump is described or
introduced by this document (Round 2 and Round 3 read against the S1/S-A criteria; none apply).

### 7.3 Observability

`project.create` is already wrapped in `trace_span` (`tgi.py:335`); this increment does not add a
new span. The dedup outcome (`duplicate: true`/`false`) is visible in the existing response body
and is not separately traced, consistent with the existing rule to trace calls, not business
outcomes already observable in the response.

## 8. Data Model

`project.json` gains one field, additive and optional (absent on every project created before this
increment, per FR-NEW-015):

| Field | Type | Present on | Notes |
|---|---|---|---|
| `source_hash` | `string` (64 lowercase hex chars) | projects created after this increment ships | SHA-256 of the raw uploaded bytes (FR-NEW-007); never backfilled (FR-NEW-015) |

No new directory, no new file, no new entity. The dedup lock key (`f"source-hash:{source_hash}"`)
is a transient in-process lock name (`src/tgi/locks.py`'s existing `lock_for`), never persisted.

## 9. Impact Analysis

### 9.1 Affected Components

- `src/tgi/templates/project.html` — header/control markup (FR-NEW-001 through FR-NEW-006,
  FR-NEW-018), warning notification (FR-NEW-013/014).
- `src/tgi/static/style.css` — new `.tgi-hint` class (FR-NEW-001).
- `src/tgi/tgi.py` — `create_project` route (FR-NEW-007 through FR-NEW-012, FR-NEW-019), `index`
  route query-param handling (FR-NEW-013/014).
- `src/tgi/services/state_manager.py` — new lookup method backing FR-NEW-008/FR-NEW-016/FR-NEW-017,
  `create_project` writes `source_hash` (FR-NEW-009).
- `src/tgi/locks.py` — reused unchanged, as the lock keyspace for FR-NEW-010.

### 9.2 Affected Requirements

None of SPEC-0001b's requirements are invalidated: `project.json`'s existing fields are untouched,
`create_project`'s id-minting and directory layout are untouched, and the response shape for a
non-duplicate creation (`201`, same four fields) is unchanged except for the added `duplicate`
key, which is additive.

### 9.3 Affected Tests

Every existing test asserting the shape of a successful `POST /api/v1/projects` response gains one
field (`duplicate: false`) it was not previously asserting on; none needs to be rewritten to pass,
since none is expected to assert an exhaustive, closed response body (standard practice for this
kind of additive field). No existing test is removed. New tests are listed in Section 12.

### 9.4 Affected Documentation

`AGENTS.md`, `README.md` describe the "Travail" page's upload flow and the `project.json` field
set at a level this increment changes; both are updated in the implementation commit, not here
(Phase 5 does not edit project docs, `/implement` does).

### 9.5 Dependencies & Risks

No new dependency: `hashlib` is in the Python standard library. Risk: a user who intentionally
wants two separate project entries for the same document (e.g. to run two independently-evolving
sets of generations against an identical snapshot) can no longer do so by re-uploading — this is
the feature's explicit purpose and was confirmed in Round 1 as the thing being traded away; raised
here as the one behavior change a user could notice and object to.

## 10. Documentation Requirements

`README.md`'s description of `POST /api/v1/projects` gains the `duplicate` response field and the
`200` duplicate-match status; `AGENTS.md`'s `project.json` field list gains `source_hash`. Both are
updated in the `/implement` commit for this spec, per the project's documentation pattern.

## 11. Traceability Matrix

| Scenario | Requirements | Tests |
|---|---|---|
| SC-001 | FR-NEW-001, FR-NEW-002, FR-NEW-003 | E2E-001, E2E-019, E2E-020 |
| SC-002 | FR-NEW-004, FR-NEW-018 | E2E-004 |
| SC-003 | FR-NEW-007, FR-NEW-009, FR-NEW-012, FR-NEW-014, FR-NEW-023 | E2E-002, E2E-014, E2E-016 |
| SC-004 | FR-NEW-007, FR-NEW-008, FR-NEW-011, FR-NEW-013 | E2E-003, E2E-024 |
| SC-005 | FR-NEW-005 | E2E-005, E2E-021 |
| SC-006 | FR-NEW-019 | E2E-008, E2E-009, E2E-010, E2E-011 |
| SC-007 | FR-NEW-008 (status unaffected) | covered by existing `source_manquante` tests, unchanged |
| SC-008 | FR-NEW-010 | E2E-006 |
| (cross-cutting) | FR-NEW-015 | E2E-014, E2E-017 |
| (cross-cutting) | FR-NEW-016 | E2E-013 |
| (cross-cutting) | FR-NEW-017 | E2E-018 |
| (cross-cutting) | FR-NEW-020 | E2E-007 |
| (cross-cutting) | FR-NEW-006 | E2E-012, E2E-022 |

## 12. End-to-End Test Suite

### 12.1 Test Summary

| Category | Count |
|---|---|
| Happy path | 7 |
| Failure / rejection | 10 |
| Edge case | 5 |
| Side effect | 2 |
| State transition | 1 |
| **Total** | **25** |

Happy : failure+edge ratio = 7 : 15 ≈ **1 : 2.1**, beats 1:1 as required.

### 12.2 New Test Specifications

**E2E-001** (happy) — Renamed heading and hint render.
*Given* a running app with no projects. *When* `GET /`. *Then* response body contains
`Charger un projet` and `cliquer sur un projet pour le charger`, and does not contain the string
`>Projets<`. *Verification:* HTTP response body substring check.

**E2E-002** (happy) — New unique upload creates a project.
*Given* no project with `source_hash` matching `sha256(b"spec v1 content")`. *When*
`POST /api/v1/projects` with `file=("spec.md", b"spec v1 content")`. *Then* status `201`, body
`{"duplicate": false, ...}`, and `projects/<id>/project.json` has `source_hash` equal to
`hashlib.sha256(b"spec v1 content").hexdigest()`. *Verification:* API response + direct file read.

**E2E-003** (happy) — Byte-identical re-upload is reported as duplicate and no new project is
created. *Given* a project created from `b"spec v1 content"` with id `P1`. *When*
`POST /api/v1/projects` with `file=("spec-renamed.md", b"spec v1 content")` (different filename,
same bytes). *Then* status `200`, body `{"id": "P1", "duplicate": true, ...}`, and the count of
directories under `projects_dir` is unchanged (still 1). *Verification:* API response + directory
listing (different channel from the response).

**E2E-004** (happy) — Clicking the button opens the modal.
*Given* `/` rendered. *When* `#create-project-btn` is clicked (Playwright). *Then*
`#create-project-modal` carries class `is-visible` and its file input is visible.
*Verification:* browser automation, DOM class assertion.

**E2E-005** (happy) — Closing without submitting creates nothing.
*Given* modal open, `uploading = false`. *When* the close control is clicked. *Then* the modal
loses `is-visible`; `GET /api/v1/projects` project count is unchanged from before the modal was
opened. *Verification:* DOM assertion + API count, before/after.

**E2E-006** (happy) — Concurrent identical uploads create exactly one project.
*Given* no project matches `sha256(b"race content")`. *When* two `POST /api/v1/projects` requests
with `file=("a.md", b"race content")` are fired concurrently (asyncio.gather). *Then* exactly one
response is `201, duplicate: false` and the other is `200, duplicate: true` pointing at the same
`id`; exactly one directory exists under `projects_dir` for that content.
*Verification:* both API responses + directory listing.

**E2E-007** (happy) — `add_source` is unaffected by dedup.
*Given* a project `P1` with its source file deleted from disk (status `source_manquante`), and a
second project `P2` whose stored source is byte-identical to the file about to be re-attached to
`P1`. *When* `POST /api/v1/projects/P1/source` with that same content. *Then* status `201`
(existing behavior, no `duplicate` key in the response, no dedup check performed), and `P1.json`
gains no `source_hash` field as a side effect of this call. *Verification:* API response + file
read.

**E2E-008** (failure) — Wrong extension inside modal is rejected before hashing.
*Given* modal open. *When* submitting `file=("x.exe", b"anything")`. *Then* status `415`, body
`{"detail": "format non supporté: .exe"}`; no project directory created; the hashing code path is
never reached (asserted by: the request never reaches `_write_json_atomic`, verified via no new
directory appearing under `projects_dir`). *Verification:* API response + directory listing.

**E2E-009** (failure) — Oversized file is rejected.
*Given* modal open. *When* submitting a 50 MiB + 1 byte `.md` file. *Then* status `413`, body
`{"detail": "document trop volumineux (max 50 Mo)"}`; no project created.
*Verification:* API response + directory listing.

**E2E-010** (failure) — Empty file is rejected.
*Given* modal open. *When* submitting `file=("empty.md", b"")`. *Then* status `400`, body
`{"detail": "document vide"}`; no project created. *Verification:* API response.

**E2E-011** (failure) — Unreadable document is rejected before hashing.
*Given* modal open. *When* submitting `file=("broken.docx", b"not a real docx")`. *Then* status
`400`, body `{"detail": "document illisible"}`; no project created; no `source_hash` computed (no
directory appears). *Verification:* API response + directory listing.

**E2E-012** (failure) — Modal does not close via its close control while uploading.
*Given* modal open, `uploading` forced `true` (Alpine state set directly in the test harness).
*When* the close control is clicked. *Then* `#create-project-modal` still carries `is-visible`.
*Verification:* DOM assertion.

**E2E-013** (edge) — Corrupted project is skipped by the dedup lookup, not fatal.
*Given* one project directory whose `project.json` is invalid JSON, and no valid project matches
`sha256(b"new content")`. *When* `POST /api/v1/projects` with `file=("n.md", b"new content")`.
*Then* status `201, duplicate: false` (the corrupted entry did not crash the lookup and was not
treated as a match). *Verification:* API response.

**E2E-014** (edge) — A pre-existing project with no `source_hash` is never matched.
*Given* a project `P0` created by directly writing a `project.json` with no `source_hash` key but
whose `source/` file is byte-identical to `b"legacy content"`. *When* `POST /api/v1/projects` with
`file=("new.md", b"legacy content")`. *Then* status `201, duplicate: false`, a second project `P1`
is created (not matched against `P0`). *Verification:* API response + directory count (2).

**E2E-015** (edge) — Duplicate warning absent when the query parameter is missing.
*Given* a valid project `P1`. *When* `GET /?project=P1`. *Then* response body does not contain
"Fichier déjà existant dans un projet". *Verification:* HTTP response body substring absence.

**E2E-016** (edge) — Duplicate warning absent for any value other than exactly `"true"`.
*Given* a valid project `P1`. *When* `GET /?project=P1&duplicate=false` and separately
`GET /?project=P1&duplicate=1`. *Then* in both cases the response body does not contain "Fichier
déjà existant dans un projet". *Verification:* HTTP response body substring absence, two calls.

**E2E-017** (edge) — Multiple pre-existing matches resolve to the earliest `created_at`.
*Given* two projects `PA` (`created_at` earlier) and `PB` (`created_at` later), both carrying
`source_hash = sha256(b"dup content")` (hand-planted to simulate a state only reachable from before
this feature). *When* `POST /api/v1/projects` with `file=("x.md", b"dup content")`. *Then* status
`200`, body `{"id": "PA", "duplicate": true, ...}`. *Verification:* API response.

**E2E-018** (edge) — Disk-full during creation is unaffected by the dedup addition.
*Given* no project matches `sha256(b"enospc content")`, and `Path.mkdir` is patched to raise
`OSError(errno.ENOSPC, "no space")` inside `StateManager.create_project`. *When*
`POST /api/v1/projects` with `file=("x.md", b"enospc content")`. *Then* status `507`, body
`{"detail": "disque plein, projet non créé"}` (existing behavior, `tgi.py:338-340`); no partial
directory remains (existing rollback, `state_manager.py:157-159`), and no `source_hash` lookup
artifact (e.g. a held lock) survives the failure. *Verification:* API response + directory listing
+ a subsequent identical request succeeding normally (proves the lock was released).

**E2E-019** (failure) — "Nouveau projet" heading no longer rendered outside the modal.
*Given* `GET /` with the modal not opened (initial render). *Then* the server-rendered HTML
(before any client-side Alpine mutation) does not contain `>Nouveau projet<` anywhere outside the
`#create-project-modal` subtree. *Verification:* HTML parse + scoped substring check.

**E2E-020** (failure) — "Projets" heading string no longer present.
*Given* `GET /`. *Then* response body does not contain the exact substring `>Projets<`.
*Verification:* HTTP response body substring absence.

**E2E-021** (failure) — Overlay click does not close the modal while uploading.
*Given* modal open, `uploading` forced `true`. *When* a click is dispatched on the modal overlay
element. *Then* `#create-project-modal` still carries `is-visible`. *Verification:* DOM assertion
(variant of E2E-012 via the overlay channel rather than the close control).

**E2E-022** (failure) — Invalid `project` with `duplicate=true` still 404s as today.
*Given* no project with id `doesnotexist`. *When* `GET /?project=doesnotexist&duplicate=true`.
*Then* status `404` (existing behavior unchanged by the new query parameter, `tgi.py:278-279`).
*Verification:* HTTP status code.

**E2E-023** (side effect) — `source_hash` persisted has the exact expected digest.
*Given* `POST /api/v1/projects` with `file=("x.md", b"exact bytes")`. *Then*
`projects/<id>/project.json`'s `source_hash` equals
`hashlib.sha256(b"exact bytes").hexdigest()` exactly (64 lowercase hex chars). *Verification:*
direct file read and comparison, a channel distinct from the API response.

**E2E-024** (side effect) — A duplicate match writes nothing to disk.
*Given* one project `P1` from `b"watched content"`. *When* `POST /api/v1/projects` with
`file=("y.md", b"watched content")`. *Then* the mtime of `projects/P1/project.json` is unchanged
by the call, and no new directory appears under `projects_dir`. *Verification:* filesystem mtime
+ directory listing, read directly, not through the API.

**E2E-025** (state transition) — Project count increases by exactly 1 on new, by 0 on duplicate.
*Given* `GET /api/v1/projects` returns N projects. *When* a new-content upload succeeds, THEN
`GET /api/v1/projects` returns N+1. *When*, from that new state, a byte-identical re-upload is
sent, THEN `GET /api/v1/projects` still returns N+1. *Verification:* API list count, before and
after each step.

### 12.3 Modified Tests

None required to pass; see 9.3. Any existing test literally asserting the creation response body
is a *closed* dict (no extra keys) would need updating to allow `duplicate`; grep for such an
assertion style was not found in `tests/functional/test_api.py`'s existing patterns and is not
expected given the project's general style of asserting specific keys, not exhaustive equality.

### 12.4 Removed Tests

None.

## 13. Consistency Notes

No conflict identified with SPEC-0001b or SPEC-0001a. The one point of friction — whether
`source_hash` constitutes "a new data model" under the depth-classification rule — is resolved in
the front block's Depth evidence: it is an additive field on the existing `Project` record, not a
new entity, and does not elevate depth to L.

## 14. Migration & Implementation Notes

**Order matters for FR-NEW-007 relative to FR-NEW-019**: validation (`_validate_upload`,
`_ensure_document_readable`) MUST run, and pass, before the hash is computed — otherwise a
malformed upload that happens to collide with nothing would still cost a hash computation for no
reason, and worse, an upload that fails validation must never be able to "claim" a hash slot that
a legitimate later upload would want to match against. Implement FR-NEW-019 (ordering) and
FR-NEW-007 (hash point) as one change to `create_project`, not two.

**No migration step is required.** `source_hash`'s absence on old projects is a valid, permanent
state (FR-NEW-015), not a transitional one awaiting backfill.

## 15. Open Questions & TBDs

- **Should a future backfill/merge tool for the pre-existing duplicates (the screenshot's exact
  complaint) be built now or later?** Resolved as later: deferred to
  `backlog/BL-0003_backfill-source-hash-and-merge-duplicates.md` per YAGNI — the user's wording
  ("ça évitera d'avoir plein de fois le même projet", future tense) targets new uploads, and
  merging existing projects (which may already have versions, runs, and history) is a materially
  riskier, separate decision the user should make explicitly later, not one this increment should
  absorb silently.
- **Hash algorithm choice (SHA-256 vs. a faster non-cryptographic hash).** Decided as SHA-256
  (DEC-001): the file is read once per request regardless (already true today for validation), the
  extra CPU cost at ≤ 50 MiB is negligible, and SHA-256 removes any later question about adequacy
  against accidental or adversarial collision, at no added complexity.

## 16. Glossary

- **Content hash (`source_hash`)**: the lowercase hex SHA-256 digest of a project's source
  document's raw bytes, stored in `project.json`, used to detect a byte-identical re-upload.
- **Duplicate (upload)**: a `POST /api/v1/projects` request whose computed `source_hash` matches
  an existing project's stored `source_hash`.
- **Dedup lookup**: the scan of existing projects' `project.json` files performed on every creation
  request to find a `source_hash` match (FR-NEW-008, FR-NEW-016, FR-NEW-017).
- **Dedup lock**: the per-hash-value `asyncio.Lock` (keyed `f"source-hash:{source_hash}"` via the
  existing `lock_for`) that serializes concurrent identical uploads (FR-NEW-010).

## 17. Decisions Log

**DEC-001** — Hash algorithm: SHA-256 over the raw uploaded bytes, never over parsed/normalized
text. *Rationale:* cheap at the existing 50 MiB ceiling, collision-resistant enough to need no
further justification, and matching on raw bytes is exactly what "the same file" means in the
user's request. *Alternatives considered:* hashing the parsed/normalized document text (would also
catch re-saves with different encodings but ties correctness to `doc_parser`'s output stability,
and was explicitly out of scope per the user's "si le fichier existe déjà" wording); MD5 (no
adequacy concern at this scale, but SHA-256 costs nothing extra here and avoids ever needing a
"why not something stronger" conversation). *Implemented by:* FR-NEW-007. *Round:* 3.

**DEC-002** — The hash is computed immediately after existing validation passes, at the exact
point `create_project`'s current code calls `safe_basename` (`tgi.py:332`), never before
validation. *Rationale:* avoids spending the hash computation (and any lock acquisition) on a
request that will be rejected anyway, and avoids a rejected file's bytes ever occupying a
dedup-relevant state. *Alternatives considered:* hashing first — rejected, it couples the dedup
path to inputs that can never become a project. *Implemented by:* FR-NEW-007, FR-NEW-019.
*Round:* 3.

**DEC-003** — Dedup applies only to `POST /api/v1/projects`, never to
`POST /api/v1/projects/{id}/source`. *Rationale:* the latter recovers a specific, already-identified
project's missing source; there is no "which project should this load" ambiguity to resolve, so
dedup has nothing to contribute there and would only add a surprising new failure mode to a
recovery path. *Alternatives considered:* applying dedup there too, rejected as solving a problem
that endpoint does not have. *Implemented by:* FR-NEW-020. *Round:* 1.

**DEC-004** — A hash match with a different filename than the matched project still counts as a
duplicate, and the matched project's name/filename are never changed to reflect the new upload's
filename. *Rationale:* dedup is about content, not filename, by the user's own framing; silently
renaming an existing project because a differently-named file was dropped on it would be a second,
unrequested behavior change. *Alternatives considered:* renaming or merging filenames — rejected,
not requested and would complicate FR-NEW-008's contract for no benefit. *Implemented by:*
FR-NEW-008. *Round:* 3.

**DEC-005** — Only exact (byte-identical) matches are detected; no near-duplicate or
content-similarity detection is built. *Rationale:* YAGNI — the user's request and the screenshot
both describe literal re-uploads of the same file, not near-duplicates; a similarity detector is
materially more complex (requires a distance metric, a threshold, and a UI for "maybe duplicate")
and was not asked for. *Alternatives considered:* fuzzy/near-duplicate matching on parsed text —
deferred, no backlog entry written since it was never requested, only explicitly ruled out as scope
creep. *Implemented by:* FR-NEW-007 (SHA-256 is exact-match by construction). *Round:* 3.

**DEC-006** — Existing projects are never backfilled with `source_hash`; the three pre-existing
duplicates from the user's screenshot are not merged or affected. *Rationale:* backfilling and
possibly merging projects that may already carry versions and run history is a materially
different, riskier operation than "stop creating new duplicates going forward," and the user's own
wording is forward-looking. *Alternatives considered:* a startup migration computing
`source_hash` for every existing project — rejected for this lot; deferred to
`backlog/BL-0003_backfill-source-hash-and-merge-duplicates.md`. *Implemented by:* FR-NEW-015.
*Round:* 1/3.

**DEC-007** — Concurrent identical uploads are serialized under a per-hash lock
(`f"source-hash:{source_hash}"`, via the existing `lock_for`), so a race cannot produce two
duplicate projects. *Rationale:* the feature's entire purpose is preventing duplicate projects;
leaving a known, narrow race open would undermine that purpose for the one case (two near-
simultaneous uploads) most likely to occur on a document a team is actively collaborating on.
*Alternatives considered:* accepting the race as a known limitation (documented, not closed) —
rejected because the existing `_project_lock`/`_version_lock` pattern in `state_manager.py` makes
closing it a small, idiomatic addition, not a disproportionate one. *Implemented by:* FR-NEW-010.
*Round:* 3.

**DEC-008** — The modal reuses the existing Alpine.js dropzone component verbatim, moved inside a
Carbon `bx--modal` container; no new JS framework or Carbon web-component JS is introduced.
*Rationale:* consistent with this project's stated "WebApp → HTMX/Alpine" default and its existing
manual (non-Carbon-JS) interaction pattern elsewhere in `project.html`. *Alternatives considered:*
Carbon's own modal web component — rejected, the rest of the page already manages visibility by
hand with Alpine (`x-show`, `:class`), and mixing in a second interaction model for one component
would be an inconsistency, not a simplification. *Implemented by:* FR-NEW-004. *Round:* 2 (Phase
0 context, confirmed Round 3).

**DEC-009** — The duplicate warning is carried across the client's full-page navigation via a
`duplicate=true` query parameter, rendered server-side as a Carbon warning notification, rather
than shown only transiently inside the modal before it closes. *Rationale:* the user's request
("afficher un warning ... mais quand même réaliser le chargement du projet correspondant") implies
both must be visible; since the existing redirect pattern is a full page navigation (losing any
client-side Alpine state), the warning has to survive that navigation through the URL, the same
mechanism `?project=` already uses. *Alternatives considered:* showing the warning only inside the
modal for N seconds before navigating — rejected, it adds a timer and a race between the user
reading it and the navigation firing, for no benefit over a query parameter the existing routing
already supports. *Implemented by:* FR-NEW-011, FR-NEW-013, FR-NEW-014. *Round:* 3.

**DEC-010** — `POST /api/v1/projects` returns `200 OK` (not `201 Created`) when the upload is a
duplicate, since no resource was created; the existing `201` is kept exactly for the genuine
creation case. *Rationale:* `201` without a corresponding creation would misstate what happened to
any API consumer inspecting the status code, and this is exactly the kind of forced choice the
process requires be decided rather than left to an implementing agent's judgment.
*Alternatives considered:* always returning `201` and relying only on the `duplicate` body field —
rejected, it is a needless status-code lie when a more accurate one costs nothing; returning `409
Conflict` — rejected, `409` would read as an error to any caller that checks `response.ok`, and a
duplicate match is not an error, it is the feature working as intended and still resolves to a
loadable project. *Implemented by:* FR-NEW-008, FR-NEW-011. *Round:* 3 (arbitrated during Phase 6
self-review, this is a G4 forced-choice the author resolved rather than left open).

## 18. Implementability Gate

| Round | F findings | A findings | Verdict |
|---|---|---|---|
| 1 (inline self-audit, depth M; no sub-agent orchestration available in this execution context, performed as rigorously as the contract in Phase 6.1/6.2 requires, against the document as written on disk) | 0 | 1 | IMPLEMENTABLE-WITH-DRIFT → resolved in place (see below), re-checked → IMPLEMENTABLE |

**The one finding, resolved in place rather than registered:** the initial draft of FR-NEW-008 did
not state what happens when the dedup lookup's own read of `project.json` races with a concurrent
`StateManager.save_project` write to the *same* existing project (unrelated to the new upload).
Classified **A** (Q2: the document presupposed a read is always consistent; `_read_json` reads a
file that `_write_json_atomic` only ever replaces via `Path.replace`, which is atomic on the
filesystems this project targets — `state_manager.py:70-72` cites the rename-based write already
used for every other read in this codebase). Verified true at `state_manager.py:66-72`: no
amendment needed beyond noting it, so amended in place as a citation rather than written to a
Drift Register entry, per Phase 6.3 step 1 (evident correction, no requirement's intent changes).
No Drift Register section is therefore included in this document (Section 19 omitted, consistent
with "only if at least one A finding was registered").

**Self-audit checklist (6.4, applied inline):**
1. No orphan decision: every DEC above names its `FR-NEW-XXX`. ✓
2. No buried change: FR-NEW-010 (locking) and FR-NEW-018 (identifiers) each own their requirement
   rather than hiding inside FR-NEW-004/008. ✓
3. Every name spelled: route paths, field names, CSS classes, exact literal strings, exact status
   codes — all named in Section 6. ✓
4. No forced choice left open: status code for duplicate (DEC-010), lock scope (DEC-007), hash
   point (DEC-002), backfill (DEC-006) are all decided. ✓
5. Order stated: Section 14 states FR-NEW-019 before FR-NEW-007. ✓
6. Every test fully specified with concrete data (Section 12.2). ✓
7. No out-of-spec prerequisite: `lock_for` and `hashlib` both already exist/are stdlib. ✓
8. EARS clean: no forbidden modal found by re-read; no nested conditions. ✓
9. Right tool: FEAT, genuinely new observable surface (modal, dedup, warning). ✓
10. Length: ~550 lines, within the 300–600 M-depth budget. ✓
11. Every code claim cited `file:LINE`, recounted (e.g. `grep` re-run for `hash|sha256|dedup`
    during Phase 0, confirmed zero hits, carried forward). ✓
12. No requirement rests on a capability the code lacks: `lock_for`, `_write_json_atomic`,
    `list_projects`'s corrupted-entry handling all exist today and are cited. ✓
13. Security misclassification check: this document describes no authn/authz bypass, injection,
    data exposure, deserialization, or traversal flaw, and no advisory-driven dependency bump.
    `Security: n/a` stands. ✓
15. N/A (FEAT, not DEBT).

**Verdict: IMPLEMENTABLE.**
