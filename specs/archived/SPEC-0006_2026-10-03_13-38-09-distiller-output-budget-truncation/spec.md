# Distillation deterministically fails on dense documents, with no actionable error — Bug Specification

> Generated on: 2026-10-03
> Id: SPEC-0006
> Nature: BUG
> Depth: S
> Depth evidence: 1 bounded context (distiller.py + 1 line of orchestrator.py), no schema/contract change, 4 reqs
> Status: Draft
> Verdict: no authority
> From backlog: n/a
> Security: n/a
> CVSS: n/a
> Affected: n/a
> Fixed in: n/a
> Defect class: absent
> Severity: High

## 1. Defect

### BUG-001: A document whose distilled output needs more than the fixed 16000-token budget fails every run, with a generic message

- **Observed behavior:** `DistillerAgent.distil` (`distiller.py:146-192`) sends one `split_for_reading` part in one
  `chat_json` call (`:166-174`), no `max_tokens` override, so it always uses `settings.max_output_tokens = 16000`
  (`config.py:125`, `llm.py:323`). `reading_budget_chars` (`distiller.py:45-50`) sizes how much *input* fits per call
  against that same flat reservation; nothing sizes the *output* the model must emit for the scenarios/labels a part
  contains. When the honest answer exceeds 16000 tokens, `chat_json`'s retry loop (`llm.py:429-492`) cannot fix it: on
  truncation it only tells the model to stop reasoning and answer directly (`llm.py:178-184`), which helps when chain-
  of-thought ate the budget, not when the JSON payload itself is the overflow.
- **Expected per authority:** none. SPEC-0004 (`specs/archived/SPEC-0004_.../spec.md:376-387`, FR-NEW-064) added a
  fourth required output, `labels`, to this same call, growing what the model must emit, without touching the output
  budget. Nothing sizes it to document density; the gap this closes.
- **Reproduction:** project `d68f57c2c621`, versions v3/v4 (`projects/d68f57c2c621/v{3,4}/state.json`), document "0302
  - SFD - Portefeuille et Intervenants _ v5.docx" (468 requirements, 95 scenarios per the earlier v1/v2 run). Expected
  `done`, actual both fail, every retry hitting the ceiling (`~/.cache/tgi/logs/tgi.log`, 13:08-13:10 for v3,
  13:30:15-13:30:21 for v4): attempt 1 truncates "before any JSON was produced", attempts 2-5 truncate with "only a
  fragment was recovered" — proof the overflow is the payload itself, since 2-5 already carry the "answer immediately"
  correction and still overflow.
- **Root cause:** `distiller.py:166-174` calls `chat_json` with no `max_tokens`; `reading_budget_chars` (`:45-50`)
  reserves one flat `max_output_tokens` per part regardless of scenario/label count (calibration is one empirical
  data point, `:9-10, 33`: "the reference specification is 78 000 tokens", not a density bound).
- **Contributing factor:** `orchestrator.py:138-139` discards the `LLMJSONError` message, writing the hardcoded
  `"réponse du modèle illisible"` instead of the exception's own text (`llm.py:499-501`); SPEC-0005's `BR-003`
  surfaces it inline, but explains nothing.
- **Impact / rollback:** any document needing enough output to exceed 16000 tokens fails deterministically, every
  version, forever, no UI workaround (v3/v4 failed identically, 5/5 each). Revert is one file plus one line, no
  migration, no `state.json` shape change.

## 2. Expected Behavior

#### BR-001 [EARS-E]: Split a part further when its distillation output is truncated
> WHEN a distillation call for one part fails after all retries because the output was truncated by the token limit
> (`TruncatedAnswerError`, `llm.py:58-64`), AND that part is not already the smallest `split_for_reading` can produce,
> THE system SHALL split it into two using `split_for_reading` at half its current character budget, and retry
> distillation independently on each half, merging successful results exactly as the existing multi-part loop already
> does (`distiller.py:161-193`).

- **Source:** decided here, BDEC-001.
- **Inputs:** the failing part's text and `budget_chars`; `TruncatedAnswerError` reaches the per-part `except
  RuntimeError` at `distiller.py:174-177` (`LLMJSONError` is a `RuntimeError`).
- **Outputs:** the part replaced by its two halves; contexts, scenarios, discards, labels accumulated from whichever
  halves succeed, same as today's merge.
- **Business Rules:** recursive — a half that still truncates is split again, until `split_for_reading(half,
  half_budget)` returns it unchanged (`:57-58`). Other call sites (`scenario_generator.py:121`, `coverage.py:87`,
  `similarity_judge.py:47`) are bounded per scenario and unaffected: none failed in the reproduction. Reuses
  `split_for_reading(text, budget_chars)` (`:55`) and the existing `last_error`/`any_success` accumulation; no new
  identifier.

#### BR-002 [EARS-UB]: Stop splitting once a part cannot be divided further
> THE system SHALL NOT attempt to split a part when `split_for_reading` at the halved budget returns it unchanged —
> that part's failure SHALL be recorded through the existing `last_error` path exactly as today, with no infinite
> retry.

- **Source:** decided here, BDEC-001 — stops BR-001 looping forever on one gigantic, unsectioned block; non regression
  anchor for `test_a_document_that_fits_is_read_whole` and the existing split tests.

#### BR-003 [EARS-E]: The persisted error names the real failure, not a fixed string
> WHEN a version fails because distillation never produced valid JSON (`LLMJSONError` reaching `orchestrator.run`,
> `:138-139`), THE system SHALL persist `str(exc)` as `state["error"]` instead of the hardcoded string `"réponse du
> modèle illisible"`.

- **Source:** decided here, BDEC-002.
- **Inputs:** the `LLMJSONError` already caught at `orchestrator.py:138`; its message already names the cause
  (`llm.py:499-501`).
- **Outputs:** `state["error"]` (existing key, SPEC-0005 `BR-002`, no new field) carries, e.g., "model claude-sonnet-5
  returned no valid JSON after 5 attempts (last error: answer was cut off ...)". Consumed as-is by SPEC-0005.
- **Business Rules:** `orchestrator.py:135-136` (`LLMConnectionError`/`LLMAuthError`) already persists `str(exc)`,
  unaffected.

#### BR-004 [EARS-UB]: A document that already fits is unaffected
> THE system SHALL NOT change the number of parts, content, or distilled result for any document whose distillation
> does not hit the output token limit — BR-001 triggers only after an observed `TruncatedAnswerError`-caused failure,
> never speculatively.

- **Source:** decided here, BDEC-001 — non regression anchor for the common case, protects every existing scripted-LLM
  run in `test_orchestrator_pipeline.py`.

## 3. Edge Cases

| Case | Expected behavior | Req |
|------|-------------------|-----|
| Document already within budget (common case) | Unchanged: one call, no split | BR-004 |
| A part truncates once, then its half succeeds | Merged with other successful parts | BR-001 |
| A top-level section still exceeds budget after any split | Fails that part only, `last_error` recorded, no loop | BR-002 |
| Every part/sub-part ultimately fails | Version fails, `state["error"]` names the reason | BR-003 |
| Truncation on `scenario_generator`/`coverage`/`similarity_judge` | Out of scope, unaffected | n/a |

## 4. Tests

### 4.1 End to end reproduction (mandatory)
#### BT-001: A dense document that would truncate today reaches `done` instead of `failed`
- **Reproduces:** BUG-001 | **Driver:** `Orchestrator.run`, invoked directly with a scripted LLM stub (pattern of
  `test_orchestrator_pipeline.py::_ScriptedLLM`). **Fails today because:** `distiller.py:166-174` has no fallback
  when `chat_json` raises `LLMJSONError` from truncation; the whole version fails (`orchestrator.py:139`).
- Given a two-section document whose `budget_chars` forces both into one part, and a stub whose `chat_json` raises
  `LLMJSONError` for the whole part but succeeds on either half (keyed on `user_content` length) / When
  `Orchestrator.run(...)` executes / Then `state["status"] == "done"` (today: `"failed"`).

### 4.2 New behavior
#### BT-010: BR-001 — a truncated part is retried as two halves
- **Validates:** BR-001 — Given `_FakeClient` (`test_distiller.py::_FakeClient` pattern) whose first call raises
  `LLMJSONError`, next two each return a valid scenario / When `distil(model, text)` runs on a two-section document /
  Then `scenarios` has both halves', `_FakeClient.calls` length 3.
#### BT-011: BR-002 — an unsplittable oversized section stops cleanly
- **Validates:** BR-002 — Given a one-section document (no `\n#`), `_FakeClient` whose every call raises
  `LLMJSONError` / When `distil(model, text)` runs / Then it raises the same `LLMJSONError`, `_FakeClient.calls`
  bounded.
#### BT-012: BR-003 — the persisted error is the real exception text
- **Validates:** BR-003 — Given `Orchestrator.run` with an LLM whose `distil` raises `LLMJSONError("model m returned
  no valid JSON after 5 attempts (last error: ...)")` / When the run completes / Then `state["error"]` equals that
  message, not `"réponse du modèle illisible"`.

### 4.3 Non regression
#### BT-020: A document that fits in the budget is distilled in one call, unchanged
- **Protects:** BR-004 — Given `_FakeClient` returning one valid answer, document under `budget_chars` / When `distil`
  runs / Then `_FakeClient.calls` has length 1.
#### BT-021: The connection/auth failure path is unaffected
- **Protects:** `orchestrator.py:135-136` — Given `distil` raises `LLMConnectionError` / When `Orchestrator.run`
  executes / Then `state["error"] == str(exc)`, as before BR-003.
#### BT-022: Existing split/budget unit tests keep passing
- **Protects:** `test_the_reading_budget_comes_from_the_model_window`,
  `test_a_document_that_does_not_fit_is_cut_on_its_outline` — unmodified, stay green.

### 4.4 Existing tests to touch

| Test file | Test name | Action | Reason |
|-----------|-----------|--------|--------|
| `tests/test_distiller.py` | `test_the_reading_budget_comes_from_the_model_window` | Kept | Pure function, untouched |
| `tests/test_distiller.py` | `test_a_document_that_fits_is_read_whole` | Kept | BT-020 is the orchestrator-level equivalent |
| `tests/test_orchestrator_pipeline.py` | every existing scripted-LLM test | Kept | None truncate; BR-004 covers it |

## 5. Impact

| File / Module | Change | Notes |
|---------------|--------|-------|
| `src/tgi/agents/distiller.py` | `distil()` (`:146-192`) gains BR-001/BR-002 split-on-truncation | Reuses `split_for_reading` |
| `src/tgi/agents/orchestrator.py` | `run()` (`:138-139`) persists `str(exc)` (BR-003) | One line |

**Existing specs affected:** SPEC-0004 — FR-NEW-064 added `labels`, growing the per-call output need; not modified,
this closes the budget-sizing gap it left open. SPEC-0005 — `BR-002`/`BR-003` already surface `state["error"]`
inline; not modified, BR-003 here only changes what that field contains.

## 6. Implementation Order

BR-003 is independent, can land first or alone. BR-001 depends on nothing else; BR-002 is the boundary condition
inside the same change as BR-001.

## 7. Decisions & Assumptions

- **BDEC-001:** on truncation, split and retry rather than raising the static `max_output_tokens` ceiling. A safe
  ceiling per deployed model is not knowable here (`models.json` carries no such field); splitting self-scales to any
  document's density and reuses already-tested machinery. **Implemented by:** BR-001, BR-002, BR-004.
- **BDEC-002:** surface the real exception text instead of inventing a new error taxonomy; `LLMJSONError`'s message
  already names the cause, nothing new to produce, only to stop discarding. **Implemented by:** BR-003.

## 8. Implementability Checklist

| Verdict | IMPLEMENTABLE |
|---|---|
| Open F failures | 0 |
| Registered drift | none |

1. No orphan decision — `BDEC-001` names BR-001/002/004, `BDEC-002` names BR-003. PASS
2. No buried change — Section 5's two files each map to their own `BR-XXX`. PASS
3. Every name spelled — `split_for_reading`, `TruncatedAnswerError`, `state["error"]`, `str(exc)`. PASS
4. No forced choice — recursion boundary stated (BR-002), merge reuses the existing loop. PASS
5. Order stated — Section 6. PASS
6. Every test specified — 4.1-4.4 fully written with concrete Given/When/Then. PASS
7. Reproduction is end to end — BT-001 drives `Orchestrator.run`, asserts `state["status"]`, fails today for the
   cited reason. PASS
7ante. Security misclassification — a reliability defect, none of the listed classes. `n/a` stands. PASS
8. No out of spec prerequisite — all cited functions already exist, implemented and tested today. PASS
9. EARS clean — `BR-001`-`BR-004` match their patterns, no forbidden modal, no nesting. PASS
10. Right tool — behavior changes, no new capability; 4 requirements within S's 3-8 range. PASS
11. Length — within the S budget after trim. PASS
12. Every code claim cited — `path:LINE` throughout; counts recounted (468 reqs, 95 scenarios, 5/5 retries per the log
   excerpt). PASS
13. No requirement rests on an absent capability — `TruncatedAnswerError` exists (`llm.py:58-64`), reachable from the
   per-part `except RuntimeError` in `distiller.py`. PASS
14. Verdict consistent — `no authority`, `Defect class: absent`, every `BR-XXX` traces to a `BDEC-XXX`. PASS
