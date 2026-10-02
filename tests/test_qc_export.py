"""Tests for the QC export: one sheet, columns and TYPE derivation (FR-NEW-034 to 038)."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook

from tgi.qc_export import build_qc_workbook

_HEADER = ["Subject", "Test Name", "Description", "Step Name", "Step Description", "Expected Results"]


def _state(refs: list[str], **extra: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "containers": {"F03.EU05.CU01": "Déléguer temporairement"},
        "scenarios": [
            {
                "id": "SC-001",
                "container": "F03.EU05.CU01",
                "tests": [
                    {
                        "id": "TEST-0001",
                        "name": "cas nominal",
                        "description": "Une description.",
                        "requirement_refs": refs,
                        "steps": [
                            {"order": 1, "description": "agir", "expected_result": "vu"},
                            {"order": 2, "description": "vérifier", "expected_result": "correct"},
                        ],
                    }
                ],
            }
        ],
    }
    state.update(extra)
    return state


def test_header_row_is_exact() -> None:
    content, _ = build_qc_workbook(_state(["F03.EU05.CU01.RM01"]))
    sheet = load_workbook(BytesIO(content))["QC"]
    assert [cell.value for cell in sheet[1]] == _HEADER


def test_one_row_per_step_with_subject_and_test_name_repeated() -> None:
    content, _ = build_qc_workbook(_state(["F03.EU05.CU01.RM01"]))
    sheet = load_workbook(BytesIO(content))["QC"]
    assert sheet.max_row == 3  # header + 2 steps
    assert sheet["A2"].value == sheet["A3"].value
    assert sheet["B2"].value == sheet["B3"].value
    assert sheet["D2"].value == "Étape 1"
    assert sheet["D3"].value == "Étape 2"


def test_subject_and_test_name_composition() -> None:
    content, _ = build_qc_workbook(_state(["F03.EU05.CU01.RM01"]))
    sheet = load_workbook(BytesIO(content))["QC"]
    assert sheet["A2"].value == "F03.EU05.CU01-RM_Déléguer temporairement_SC-001"
    assert sheet["B2"].value == "TRA_TEST-0001_cas nominal__F03.EU05.CU01.RM01"
    assert "Exigences validées : F03.EU05.CU01.RM01" in sheet["C2"].value


def test_type_derivation_table() -> None:
    cases = {
        "F03.EU05.CU01.RM01": "RM",
        "F03.EU05.CU01.EM01": "EMOE",
        "F03.EU05.CU01.M01": "IHM",
        "F03.EU05.CU01.N01": "IHM",
        "F03.EU05.CU01.T01": "IHM",
    }
    for ref, expected_type in cases.items():
        content, warnings = build_qc_workbook(_state([ref]))
        sheet = load_workbook(BytesIO(content))["QC"]
        assert f"-{expected_type}_" in sheet["A2"].value, ref
        assert warnings == []


def test_unknown_prefix_yields_inconnu_and_a_warning() -> None:
    content, warnings = build_qc_workbook(_state(["F03.EU05.CU01.ZZ01"]))
    sheet = load_workbook(BytesIO(content))["QC"]
    assert "-INCONNU_" in sheet["A2"].value
    assert any("préfixe d'exigence inconnu: ZZ" in w for w in warnings)


def test_a_cell_beyond_32767_characters_is_truncated() -> None:
    long_description = "x" * 40000
    state = _state(["F03.EU05.CU01.RM01"])
    state["scenarios"][0]["tests"][0]["description"] = long_description

    content, _ = build_qc_workbook(state)
    sheet = load_workbook(BytesIO(content))["QC"]
    assert len(sheet["C2"].value) == 32767
    assert sheet["C2"].value.endswith("…")


def test_a_test_with_no_requirement_ref_still_produces_a_row_typed_inconnu() -> None:
    content, _ = build_qc_workbook(_state([]))
    sheet = load_workbook(BytesIO(content))["QC"]
    assert "-INCONNU_" in sheet["A2"].value
