"""The workbook is the artefact a reviewer actually opens, so its shape is under test.

What matters here is not that openpyxl works: it is that a human can read 7000 rows. One row
per step with the test columns repeated, so a filter keeps working; one shade per test, so a
test reads as a block; the wording of every requirement in the traceability sheet, since a
row with a reference and no wording tells nobody what to test.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import load_workbook

from tgi.workbook import build_workbook, sheet_title


def _state() -> dict[str, Any]:
    return {
        "requirements": [
            {"ref": "F01.CU01.RM01", "kind": "RM", "axis": "F", "parent": "F01.CU01", "statement": "Le système crée."},
            {"ref": "F01.CU01.RM02", "kind": "RM", "axis": "F", "parent": "F01.CU01", "statement": "Le système refuse."},
            {"ref": "F01.CU01.RM03", "kind": "RM", "axis": "F", "parent": "F01.CU01", "statement": ""},
        ],
        "containers": {"F01.CU01": "Créer une habilitation"},
        "scenarios": [
            {
                "id": "SC-001",
                "title": "Créer une habilitation",
                "container": "F01.CU01",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["F01.CU01.RM01", "F01.CU01.RM02", "F01.CU01.RM03"],
                "uncovered_refs": ["F01.CU01.RM03"],
                "tests": [
                    {
                        "id": "TEST-0001",
                        "name": "Création nominale",
                        "description": "Le cas qui marche",
                        "status": "draft",
                        "requirement_refs": ["F01.CU01.RM01"],
                        "steps": [
                            {"order": 1, "description": "Ouvrir l'écran", "expected_result": "L'écran s'affiche"},
                            {"order": 2, "description": "Valider", "expected_result": "L'habilitation existe"},
                        ],
                    },
                    {
                        "id": "TEST-0002",
                        "name": "Refus sur doublon",
                        "description": "Le cas qui échoue",
                        "status": "draft",
                        "requirement_refs": ["F01.CU01.RM02"],
                        "steps": [{"order": 1, "description": "Créer deux fois", "expected_result": "Refus"}],
                        "data_rows": [{"profil": "RRC"}, {"profil": "CAGE"}],
                    },
                ],
            }
        ],
        "discards": [{"what": "Historique des versions", "reason": "sans_valeur_test", "refs": [], "decision": "proposed"}],
    }


def _sheet(name: str) -> Any:
    return load_workbook(io.BytesIO(build_workbook(_state())))[name]


def test_the_reviewer_opens_on_the_summary_then_the_traceability() -> None:
    names = load_workbook(io.BytesIO(build_workbook(_state()))).sheetnames

    assert names[:2] == ["Synthèse", "Traçabilité"]
    assert "F01" in names
    assert "Écarts" in names


def test_traceability_carries_the_wording_of_every_requirement() -> None:
    """A row with a reference and no wording is what made uncovered requirements unusable."""
    trace = _sheet("Traçabilité")
    rows = {row[0]: row for row in trace.iter_rows(min_row=2, values_only=True)}

    assert rows["F01.CU01.RM01"][3] == "Le système crée."
    assert rows["F01.CU01.RM01"][4] == "covered"
    assert rows["F01.CU01.RM03"][4] == "missing"
    assert rows["F01.CU01.RM01"][7] == "TEST-0001"


def test_one_row_per_step_repeating_the_test_columns() -> None:
    """The columns are repeated so that filtering on a test keeps every one of its steps."""
    sheet = _sheet("F01")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    steps_of_first = [row for row in rows if row[4] == "TEST-0001"]
    assert [row[7] for row in steps_of_first] == [1, 2]
    assert {row[5] for row in steps_of_first} == {"Création nominale"}
    # A parameterised case is a row of its own, with no step number
    data_rows = [row for row in rows if row[6] == "jeu de données"]
    assert [row[8] for row in data_rows] == ["profil: RRC", "profil: CAGE"]


def test_a_test_is_one_block_of_shading_across_its_rows() -> None:
    """A reviewer follows a test, which spans several rows, so even and odd banding is
    useless: the shade changes when the test changes, never inside one."""
    sheet = _sheet("F01")

    shades: dict[str, set[str]] = {}
    for row in sheet.iter_rows(min_row=2):
        shades.setdefault(str(row[4].value), set()).add(str(row[0].fill.start_color.rgb))

    assert all(len(distinct) == 1 for distinct in shades.values())
    assert len({next(iter(distinct)) for distinct in shades.values()}) == 2


def test_the_header_stays_and_the_range_is_filterable() -> None:
    sheet = _sheet("F01")

    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref is not None
    assert sheet.auto_filter.ref.startswith("A1:")


def test_a_sheet_name_fits_excel_and_stays_unique() -> None:
    """Excel refuses a name over 31 characters, and silently refuses a duplicate."""
    used: set[str] = set()

    first = sheet_title("F03.EU04 Déléguer une partie de son portefeuille", used)
    second = sheet_title("F03.EU04 Déléguer une partie de son portefeuille", used)

    assert len(first) <= 31
    assert len(second) <= 31
    assert first != second
