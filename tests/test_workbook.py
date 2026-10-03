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

from tgi.workbook import build_workbook, onglet_type_name, sheet_title


def _state() -> dict[str, Any]:
    return {
        "requirements": [
            {"ref": "F01.CU01.RM01", "kind": "RM", "axis": "F", "parent": "F01.CU01", "statement": "Le système crée."},
            {
                "ref": "F01.CU01.RM02",
                "kind": "RM",
                "axis": "F",
                "parent": "F01.CU01",
                "statement": "Le système refuse.",
            },
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
        "discards": [
            {"what": "Historique des versions", "reason": "sans_valeur_test", "refs": [], "decision": "proposed"}
        ],
    }


def _sheet(name: str) -> Any:
    return load_workbook(io.BytesIO(build_workbook(_state())))[name]


def test_the_reviewer_opens_on_the_summary_then_the_traceability() -> None:
    names = load_workbook(io.BytesIO(build_workbook(_state()))).sheetnames

    assert names[:2] == ["Synthèse", "Traçabilité"]
    assert "F01.CU01-RM" in names
    assert "Écarts" in names


def test_traceability_carries_the_wording_of_every_requirement() -> None:
    """A row with a reference and no wording is what made uncovered requirements unusable."""
    trace = _sheet("Traçabilité")
    rows = {row[0]: row for row in trace.iter_rows(min_row=2, values_only=True)}

    assert rows["F01.CU01.RM01"][3] == "Le système crée."
    assert rows["F01.CU01.RM01"][4] == "covered"
    assert rows["F01.CU01.RM03"][4] == "missing"
    assert rows["F01.CU01.RM01"][7] == "TEST-0001"


def test_e2e_mod_001_only_the_first_step_row_of_a_test_carries_its_metadata() -> None:
    """Only the first step row of a test carries its metadata columns; the following step
    rows of the same test leave them blank, except "ID test" (FR-NEW-080, FR-NEW-081)."""
    sheet = _sheet("F01.CU01-RM")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    steps_of_first = [row for row in rows if row[4] == "TEST-0001"]
    assert [row[7] for row in steps_of_first] == [1, 2]
    first_row, second_row = steps_of_first
    assert first_row[5] == "Création nominale"
    assert not second_row[5]
    assert second_row[4] == "TEST-0001"


def test_e2e_new_004_jeux_de_donnees_sheet_references_test_id_and_source_sheet() -> None:
    """The "Jeux de données" sheet carries the data_rows of every test, each row tagged
    with the test's ID and the type sheet it appears in (FR-NEW-078, DEC-026)."""
    workbook = load_workbook(io.BytesIO(build_workbook(_state())))
    assert "F01.CU01-RM" in workbook.sheetnames

    type_sheet = workbook["F01.CU01-RM"]
    type_rows = list(type_sheet.iter_rows(min_row=2, values_only=True))
    assert not [row for row in type_rows if row[4] == "TEST-0002" and not row[7]]

    data_sheet = workbook["Jeux de données"]
    assert [cell.value for cell in next(data_sheet.iter_rows(min_row=1, max_row=1))] == [
        "ID test",
        "Nom du test",
        "Détail",
        "Onglet source",
    ]
    data_rows = list(data_sheet.iter_rows(min_row=2, values_only=True))
    assert data_rows == [
        ("TEST-0002", "Refus sur doublon", "profil: RRC", "F01.CU01-RM"),
        ("TEST-0002", "Refus sur doublon", "profil: CAGE", "F01.CU01-RM"),
    ]


_METADATA_COLUMNS = (0, 1, 2, 3, 5, 6, 10, 11, 12)


def _multi_step_state(test_id: str, step_count: int, ref: str) -> dict[str, Any]:
    return {
        "requirements": [
            {"ref": ref, "kind": "RM", "axis": "EU", "parent": "EU01.CU01", "statement": "Enonce."},
        ],
        "containers": {},
        "scenarios": [
            {
                "id": "SC-001",
                "title": "Scénario",
                "container": "EU01.CU01",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": [ref],
                "uncovered_refs": [],
                "tests": [
                    {
                        "id": test_id,
                        "name": "Test multi-étapes",
                        "description": "Description",
                        "status": "draft",
                        "requirement_refs": [ref],
                        "steps": [
                            {"order": i + 1, "description": f"Étape {i + 1}", "expected_result": "OK"}
                            for i in range(step_count)
                        ],
                    }
                ],
            }
        ],
    }


def test_e2e_new_002_metadata_columns_are_blank_on_step_rows_2_plus() -> None:
    """Only the first step row of a 3-step test carries its metadata, "ID test" stays filled
    on every row (FR-NEW-080, FR-NEW-081)."""
    state = _multi_step_state("TEST-0100", 3, "EU01.CU01.RM01")

    sheet = _sheet_of(state, "EU01.CU01-RM")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    assert len(rows) == 3
    first, second, third = rows
    assert first[0] == "EU01.CU01"
    assert first[5] == "Test multi-étapes"
    assert first[10] == "EU01.CU01.RM01"
    assert first[11] in {"MOE", "MOA", "MOA/MOE", "INCONNU"}
    assert first[12] == "draft"
    assert first[4] == "TEST-0100"

    for row in (second, third):
        assert row[4] == "TEST-0100"
        for column in _METADATA_COLUMNS:
            assert not row[column]


def test_e2e_new_011_a_test_metadata_value_never_reappears_past_its_first_row() -> None:
    """No metadata column value of a 5-step test repeats on rows 2 through 5 (FR-NEW-081)."""
    state = _multi_step_state("TEST-0400", 5, "EU01.CU01.RM03")

    sheet = _sheet_of(state, "EU01.CU01-RM")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    assert len(rows) == 5
    for row in rows[1:]:
        assert row[4] == "TEST-0400"
        for column in _METADATA_COLUMNS:
            assert not row[column]


def test_e2e_new_075_classification_column_present_after_exigences_before_statut() -> None:
    sheet = _sheet("F01.CU01-RM")
    header = [cell.value for cell in sheet[1]]

    assert header[header.index("Exigences validées") + 1] == "Classification"
    assert header[header.index("Classification") + 1] == "Statut"


def test_a_test_is_one_block_of_shading_across_its_rows() -> None:
    """A reviewer follows a test, which spans several rows, so even and odd banding is
    useless: the shade changes when the test changes, never inside one."""
    sheet = _sheet("F01.CU01-RM")

    shades: dict[str, set[str]] = {}
    for row in sheet.iter_rows(min_row=2):
        shades.setdefault(str(row[4].value), set()).add(str(row[0].fill.start_color.rgb))

    assert all(len(distinct) == 1 for distinct in shades.values())
    assert len({next(iter(distinct)) for distinct in shades.values()}) == 2


def test_the_header_stays_and_the_range_is_filterable() -> None:
    sheet = _sheet("F01.CU01-RM")

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


def _grammar() -> Any:
    from tgi.grammar import infer_grammar

    refs = ["EU01.CU01.RM01", "E04.M01", "F01.EU02.CU03.EM01", "E07.N01", "E04.M02"]
    return infer_grammar(" ".join(ref for ref in refs for _ in range(5)))


def test_e2e_new_006_legende_des_onglets_et_renvoi_croise_vers_la_tracabilite() -> None:
    """FR-NEW-071/072: the Synthèse legend lists only sheets really present, and each
    "Par type d'exigence" row links to the Traçabilité sheet's first row."""
    workbook = load_workbook(io.BytesIO(build_workbook(_state())))
    overview = workbook["Synthèse"]
    rows = list(overview.iter_rows(min_row=1, values_only=True))
    labels = [row[0] for row in rows]

    assert "Légende des onglets" in labels
    legend_index = labels.index("Légende des onglets")
    legend_names = {str(row[0]).strip() for row in rows[legend_index + 1 :] if row[0]}
    assert legend_names == set(workbook.sheetnames)

    type_index = labels.index("Par type d'exigence")
    hyperlinked = [
        cell.hyperlink
        for cell in (overview.cell(row=row_number, column=1) for row_number in range(type_index + 1, legend_index + 1))
        if cell.hyperlink
    ]
    assert hyperlinked
    assert all(link.target == f"#'{workbook.sheetnames[1]}'!A1" for link in hyperlinked)


def test_onglet_type_name_groups_rm_ihm_emoe_by_rattachement() -> None:
    grammar = _grammar()

    assert onglet_type_name("EU01.CU01.RM01", grammar) == "EU01.CU01-RM"
    assert onglet_type_name("E04.M01", grammar) == "IHM_E04"
    assert onglet_type_name("F01.EU02.CU03.EM01", grammar) == "F01.EU02.CU03-EMOE"


def test_e2e_new_010_analyse_sheet_lists_every_section_even_with_zero_counters() -> None:
    """A section with no requirement and no scenario still appears, with zero counters,
    rather than being silently absent (FR-NEW-073)."""
    state = {
        "requirements": [
            {
                "ref": "F02.EU01.CU01.RM01",
                "kind": "RM",
                "axis": "F",
                "parent": "F02.EU01.CU01",
                "statement": "Le système fait.",
            },
            {
                "ref": "F02.EU01.CU02.RM01",
                "kind": "RM",
                "axis": "F",
                "parent": "F02.EU01.CU02",
                "statement": "Le système fait.",
            },
        ],
        "containers": {
            "F02.EU01.CU01": "Cas avec exigence",
            "F02.EU01.CU02": "Cas sans scénario rattaché",
        },
        "scenarios": [
            {
                "id": "SC-001",
                "title": "Scénario rattaché",
                "container": "F02.EU01.CU01",
                "kind": "nominal",
                "status": "done",
                "source_section": "F02.EU01.CU01",
                "requirement_refs": ["F02.EU01.CU01.RM01"],
                "uncovered_refs": [],
                "tests": [],
            }
        ],
        "discards": [],
    }

    workbook_bytes = build_workbook(state)
    sheet = load_workbook(io.BytesIO(workbook_bytes))["Analyse"]
    rows = {row[0]: row for row in sheet.iter_rows(min_row=2, values_only=True)}

    assert "F02.EU01.CU02" in rows
    row = rows["F02.EU01.CU02"]
    assert row[1] == "Cas sans scénario rattaché"
    assert row[2] == 1
    assert row[3] == 0
    assert not row[4]
    assert not row[5]

    row_with = rows["F02.EU01.CU01"]
    assert row_with[2] == 1
    assert row_with[3] == 1
    assert row_with[4] == "SC-001"


def _reorg_state() -> dict[str, Any]:
    return {
        "requirements": [
            {"ref": "EU01.CU01.RM01", "kind": "RM", "axis": "EU", "parent": "EU01.CU01", "statement": "RM."},
            {"ref": "E04.M01", "kind": "M", "axis": "E", "parent": "E04", "statement": "IHM."},
            {
                "ref": "F01.EU02.CU03.EM01",
                "kind": "EM",
                "axis": "F",
                "parent": "F01.EU02.CU03",
                "statement": "EMOE.",
            },
        ],
        "containers": {},
        "scenarios": [
            {
                "id": "SC-RM",
                "title": "Scénario RM",
                "container": "EU01.CU01",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["EU01.CU01.RM01"],
                "uncovered_refs": [],
                "tests": [{"id": "TEST-RM", "name": "Test RM", "requirement_refs": ["EU01.CU01.RM01"], "steps": []}],
            },
            {
                "id": "SC-IHM",
                "title": "Scénario IHM",
                "container": "E04",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["E04.M01"],
                "uncovered_refs": [],
                "tests": [{"id": "TEST-IHM", "name": "Test IHM", "requirement_refs": ["E04.M01"], "steps": []}],
            },
            {
                "id": "SC-EMOE",
                "title": "Scénario EMOE",
                "container": "F01.EU02.CU03",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["F01.EU02.CU03.EM01"],
                "uncovered_refs": [],
                "tests": [
                    {
                        "id": "TEST-EMOE",
                        "name": "Test EMOE",
                        "requirement_refs": ["F01.EU02.CU03.EM01"],
                        "steps": [],
                    }
                ],
            },
        ],
    }


def test_e2e_new_001_one_sheet_per_type_really_present() -> None:
    names = load_workbook(io.BytesIO(build_workbook(_reorg_state()))).sheetnames

    assert set(names) == {
        "Synthèse",
        "Traçabilité",
        "EU01.CU01-RM",
        "IHM_E04",
        "F01.EU02.CU03-EMOE",
        "Jeux de données",
        "Analyse",
    }

    rm_rows = [row[4] for row in _sheet_of(_reorg_state(), "EU01.CU01-RM").iter_rows(min_row=2, values_only=True)]
    assert rm_rows == ["TEST-RM"]
    ihm_rows = [row[4] for row in _sheet_of(_reorg_state(), "IHM_E04").iter_rows(min_row=2, values_only=True)]
    assert ihm_rows == ["TEST-IHM"]


def _sheet_of(state: dict[str, Any], name: str) -> Any:
    return load_workbook(io.BytesIO(build_workbook(state)))[name]


def test_e2e_new_003_no_empty_sheet_for_an_absent_type() -> None:
    state = _reorg_state()
    state["requirements"] = [r for r in state["requirements"] if r["kind"] == "RM"]
    state["scenarios"] = [s for s in state["scenarios"] if s["id"] == "SC-RM"]

    names = load_workbook(io.BytesIO(build_workbook(state))).sheetnames

    assert not any(name.startswith("IHM_") for name in names)
    assert not any(name.endswith("-EMOE") for name in names)


def test_e2e_new_012_a_test_covering_two_groups_appears_in_both_sheets() -> None:
    state = _reorg_state()
    state["requirements"].append({"ref": "E07.N01", "kind": "N", "axis": "E", "parent": "E07", "statement": "IHM 2."})
    multi_scenario = {
        "id": "SC-MULTI",
        "title": "Scénario multi écran",
        "container": "E04",
        "kind": "nominal",
        "status": "done",
        "requirement_refs": ["E04.M01", "E07.N01"],
        "uncovered_refs": [],
        "tests": [
            {"id": "TEST-0500", "name": "Test multi écran", "requirement_refs": ["E04.M01", "E07.N01"], "steps": []}
        ],
    }
    state["scenarios"].append(multi_scenario)

    workbook = load_workbook(io.BytesIO(build_workbook(state)))

    assert "TEST-0500" in [row[4] for row in workbook["IHM_E04"].iter_rows(min_row=2, values_only=True)]
    assert "TEST-0500" in [row[4] for row in workbook["IHM_E07"].iter_rows(min_row=2, values_only=True)]


def test_e2e_new_023_two_requirements_of_the_same_group_share_one_sheet() -> None:
    state = _reorg_state()
    state["requirements"].append({"ref": "E04.M02", "kind": "M", "axis": "E", "parent": "E04", "statement": "IHM 2."})
    second_scenario = {
        "id": "SC-IHM-2",
        "title": "Scénario IHM 2",
        "container": "E04",
        "kind": "nominal",
        "status": "done",
        "requirement_refs": ["E04.M02"],
        "uncovered_refs": [],
        "tests": [{"id": "TEST-IHM-2", "name": "Test IHM 2", "requirement_refs": ["E04.M02"], "steps": []}],
    }
    state["scenarios"].append(second_scenario)

    names = load_workbook(io.BytesIO(build_workbook(state))).sheetnames

    assert names.count("IHM_E04") == 1
    assert "IHM_E04 (2)" not in names
    test_ids = {row[4] for row in _sheet_of(state, "IHM_E04").iter_rows(min_row=2, values_only=True)}
    assert test_ids == {"TEST-IHM", "TEST-IHM-2"}
