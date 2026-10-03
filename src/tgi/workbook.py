"""The reviewable workbook: the two reading axes, one sheet family each.

The JSON export serves tooling. This serves the human who has to sign off a test plan, so
it follows the specification's own numbering and stays sortable: no merged cells, a frozen
header, an autofilter on every sheet. The traceability sheet is what proves nothing was
forgotten, and it is the sheet a reviewer opens first.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

from tgi.classification import classification_of
from tgi.coverage_report import coverage_summary, requirement_rows
from tgi.deliverable import UNPLACED, natural_key
from tgi.grammar import Grammar, infer_grammar

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet

_HEADER_FILL = PatternFill("solid", start_color="FF0F62FE")
_HEADER_FONT = Font(color="FFFFFFFF", bold=True)
# A very light grey: it has to survive printing and not fight with the status colours
_BAND_FILL = PatternFill("solid", start_color="FFF2F4F8")
# Zero based index of the "ID test" column, the block a reviewer follows across step rows
_TEST_ID_COLUMN = 4
_WRAP = Alignment(vertical="top", wrap_text=True)
_TOP = Alignment(vertical="top")

# Columns at least this wide hold prose, so their cells wrap
_WRAPPED_COLUMN_WIDTH = 40

_TEST_COLUMNS = [
    ("Cas d'utilisation", 18),
    ("Scénario", 12),
    ("Intention du scénario", 42),
    ("Nature", 10),
    ("ID test", 12),
    ("Nom du test", 40),
    ("Description", 46),
    ("Étape", 7),
    ("Action", 48),
    ("Résultat attendu", 48),
    ("Exigences validées", 30),
    ("Classification", 12),
    ("Statut", 11),
]

_SUMMARY_COLUMNS = [
    ("Indicateur", 34),
    ("Valeur", 16),
]

_TRACE_COLUMNS = [
    ("Référence exigence", 22),
    ("Type", 8),
    ("Cas d'utilisation", 18),
    ("Énoncé", 60),
    ("Statut", 12),
    ("Motif si non testable", 40),
    ("Scénarios", 34),
    ("Tests", 30),
]

_DISCARD_COLUMNS = [
    ("Élément écarté", 60),
    ("Motif", 20),
    ("Références", 26),
    ("Décision", 12),
]

_ANALYSIS_COLUMNS = [
    ("Section", 20),
    ("Titre", 40),
    ("Exigences trouvées", 18),
    ("Exigences rattachées à un scénario", 30),
    ("Scénarios issus de cette section", 34),
    ("Éléments écartés", 40),
]

_DATA_ROW_COLUMNS = [
    ("ID test", 12),
    ("Nom du test", 40),
    ("Détail", 60),
    ("Onglet source", 18),
]

# One sentence per sheet the workbook can produce, keyed by the fixed label it is
# created under (FR-NEW-071). A sheet named after a requirement type or a section is not
# in here: its description is composed where it is created instead.
_SHEET_DESCRIPTIONS = {
    "Synthèse": "vue d'ensemble des compteurs de couverture et la légende des onglets.",
    "Traçabilité": "une ligne par exigence du document, avec son statut et les tests qui la couvrent.",
    "Jeux de données": "les jeux de données de chaque test, un par ligne, rattachés à son onglet source.",
    "Écarts": "les éléments du document écartés de la génération, avec leur motif.",
    "Analyse": "une ligne par section du document, avec ses compteurs d'exigences et de scénarios.",
}


def _sheet_description(name: str) -> str:
    if name in _SHEET_DESCRIPTIONS:
        return _SHEET_DESCRIPTIONS[name]
    return "les tests d'un type d'exigence, un onglet par type et par rattachement."


# Excel refuses these in a sheet name, and caps it at 31 characters
_FORBIDDEN_IN_SHEET_NAME = re.compile(r"[\[\]:*?/\\]")


def sheet_title(name: str, used: set[str]) -> str:
    """Sheet name Excel accepts, kept unique within the workbook."""
    cleaned = _FORBIDDEN_IN_SHEET_NAME.sub("-", str(name or "Feuille")).strip() or "Feuille"
    candidate = cleaned[:31]
    if candidate not in used:
        used.add(candidate)
        return candidate
    for index in range(2, 100):
        suffix = f" ({index})"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate
    unique = cleaned[:27] + f" {len(used)}"
    used.add(unique)
    return unique


def _write_header(sheet: Worksheet, columns: list[tuple[str, int]]) -> None:
    sheet.append([label for label, _ in columns])
    for index, (_, width) in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _TOP
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"


def _finish_sheet(sheet: Worksheet, columns: list[tuple[str, int]], band_on: int | None = None) -> None:
    """Autofilter, wrapped text on the long columns, and one shade per block.

    A reviewer reads 7000 rows of steps, and an even and odd banding is useless there: what
    they follow is a test, which spans several rows. So the shade changes when the value of
    one column changes, which draws each test, or each requirement, as a block.
    """
    last_row = max(sheet.max_row, 1)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{last_row}"
    wrapped = {index for index, (_, width) in enumerate(columns, start=1) if width >= _WRAPPED_COLUMN_WIDTH}
    previous: object = None
    shaded = False
    for row in sheet.iter_rows(min_row=2, max_row=last_row):
        if band_on is not None:
            current = row[band_on].value
            if current != previous:
                shaded = not shaded
                previous = current
        for cell in row:
            cell.alignment = _WRAP if cell.column in wrapped else _TOP
            if shaded:
                cell.fill = _BAND_FILL


def _test_metadata(
    scenario: Any, test: dict[str, Any], refs: str, classification: str, description: str, is_first: bool
) -> tuple[list[Any], str, str, list[Any]]:
    """The metadata columns around "ID test" and the step triple, blank on every row but the
    first (FR-NEW-080, FR-NEW-081)."""
    if not is_first:
        return (["", "", "", ""], "", "", ["", "", ""])
    lead = [scenario.container or UNPLACED, scenario.id, scenario.title, scenario.kind]
    return (lead, test.get("name", ""), description, [refs, classification, test.get("status", "")])


def _test_rows(scenario: Any, tests: list[dict[str, Any]], grammar: Grammar) -> list[list[Any]]:
    """One row per step. Only the first row of each test carries its metadata columns; the
    following ones leave them blank, except "ID test" which stays filled on every row
    (FR-NEW-080, FR-NEW-081).
    """
    rows: list[list[Any]] = []
    for test in tests:
        refs_list = [str(ref) for ref in test.get("requirement_refs") or []]
        refs = ", ".join(refs_list)
        classification = classification_of(refs_list, grammar)
        steps = [step for step in (test.get("steps") or []) if isinstance(step, dict)] or [{}]
        test_id = test.get("id", "")
        is_first = True
        for step in steps:
            lead, name, description, trailer = _test_metadata(
                scenario, test, refs, classification, test.get("description", ""), is_first
            )
            rows.append(
                [
                    *lead,
                    test_id,
                    name,
                    description,
                    step.get("order", ""),
                    step.get("description", ""),
                    step.get("expected_result", ""),
                    *trailer,
                ]
            )
            is_first = False
    if not tests:
        rows.append(
            [
                scenario.container or UNPLACED,
                scenario.id,
                scenario.title,
                scenario.kind,
                "",
                "AUCUN TEST",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    return rows


def _grammar_of(state: dict[str, Any]) -> Grammar:
    """Rebuild the numbering grammar from the requirements a run already extracted.

    A real document carries each axis well past the support threshold `infer_grammar` needs,
    but a project with only a handful of requirements, or a unit test fixture, would not. Each
    reference is repeated so the same inference holds regardless of how many requirements the
    project actually has.
    """
    refs = [str(r.get("ref")) for r in state.get("requirements") or [] if isinstance(r, dict) and r.get("ref")]
    text = " ".join(ref for ref in refs for _ in range(5))
    return infer_grammar(text)


def onglet_type_name(ref: str, grammar: Grammar) -> str:
    """The sheet a requirement's type sends its tests to: one per (type, rattachement).

    IHM is named after its screen, RM and EMOE after the use case they belong to
    (`Requirement.parent`, which is exactly what `grammar.container_of` recomputes here).
    """
    kind = grammar.kind_of(ref)
    container = grammar.container_of(ref) or ref
    if kind in {"M", "N"}:
        return f"IHM_{container}"
    if kind == "EM":
        return f"{container}-EMOE"
    if kind == "RM":
        return f"{container}-RM"
    return container


def _tests_by_group(
    state: dict[str, Any], tests_by_scenario: dict[str, list[dict[str, Any]]]
) -> dict[str, list[tuple[Any, dict[str, Any]]]]:
    """Tests, grouped by the sheet their requirements send them to.

    A test covering requirements of several groups is repeated in each of them (FR-NEW-077).
    """
    grammar = _grammar_of(state)
    tests_by_group: dict[str, list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
    for scenario in state.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        entry = SimpleNamespace(
            id=str(scenario.get("id", "")),
            title=str(scenario.get("title", "")),
            container=str(scenario.get("container") or ""),
            kind=str(scenario.get("kind") or "nominal"),
        )
        for test in tests_by_scenario.get(entry.id, []):
            seen: set[str] = set()
            for ref in test.get("requirement_refs") or []:
                key = onglet_type_name(str(ref), grammar)
                if key in seen:
                    continue
                seen.add(key)
                tests_by_group[key].append((entry, test))
    return tests_by_group


def _analysis_rows(state: dict[str, Any], grammar: Grammar) -> list[tuple[str, str, int, int, list[str], list[str]]]:
    """One row per section the inferred numbering declares (FR-NEW-073).

    A section is every container `state["containers"]` knows about, plus every parent a
    requirement declares: a container without a title still reads as a row. Counters are
    arithmetic, never a model's judgement.
    """
    requirements = [r for r in state.get("requirements") or [] if isinstance(r, dict)]
    titles: dict[str, str] = dict(state.get("containers") or {})
    sections: set[str] = set(titles)
    for requirement in requirements:
        parent = str(requirement.get("parent") or "")
        if parent:
            sections.add(parent)

    requirements_by_section: dict[str, list[str]] = defaultdict(list)
    for requirement in requirements:
        parent = str(requirement.get("parent") or "")
        ref = str(requirement.get("ref") or "")
        if parent and ref:
            requirements_by_section[parent].append(ref)

    scenarios = [s for s in state.get("scenarios") or [] if isinstance(s, dict)]
    attached_refs: set[str] = set()
    scenarios_by_section: dict[str, list[str]] = defaultdict(list)
    for scenario in scenarios:
        for ref in scenario.get("requirement_refs") or []:
            attached_refs.add(str(ref))
        section = str(scenario.get("source_section") or "")
        if section:
            scenarios_by_section[section].append(str(scenario.get("id") or ""))
            sections.add(section)

    discards = [d for d in state.get("discards") or [] if isinstance(d, dict)]
    discards_by_section: dict[str, list[str]] = defaultdict(list)
    for discard in discards:
        for ref in discard.get("refs") or []:
            section = grammar.container_of(str(ref)) or str(ref)
            if section:
                discards_by_section[section].append(str(discard.get("what") or ref))

    rows: list[tuple[str, str, int, int, list[str], list[str]]] = []
    for section in sorted(sections, key=natural_key):
        refs = requirements_by_section.get(section, [])
        attached = sum(1 for ref in refs if ref in attached_refs)
        rows.append(
            (
                section,
                titles.get(section, ""),
                len(refs),
                attached,
                scenarios_by_section.get(section, []),
                discards_by_section.get(section, []),
            )
        )
    return rows


def build_workbook(state: dict[str, Any]) -> bytes:
    """Return the xlsx bytes for this project."""
    summary = coverage_summary(state)
    tests_by_scenario: dict[str, list[dict[str, Any]]] = {
        str(scenario.get("id")): [t for t in scenario.get("tests") or [] if isinstance(t, dict)]
        for scenario in state.get("scenarios") or []
        if isinstance(scenario, dict)
    }

    workbook = Workbook()
    used_names: set[str] = set()

    # Sheet one: does the deliverable hold together
    overview = workbook.active
    overview.title = sheet_title("Synthèse", used_names)
    _write_header(overview, _SUMMARY_COLUMNS)
    for label, value in (
        ("Scénarios", summary["scenarios"]),
        ("Tests", summary["tests"]),
        ("Étapes de test", summary["steps"]),
        ("Tests par scénario", summary["tests_per_scenario"]),
        ("Exigences du document", summary["requirements"]),
        ("Exigences couvertes", summary["covered"]),
        ("Couverture", f"{summary['coverage_percent']} %"),
        ("Exigences non couvertes", summary["missing_count"]),
        ("Déclarées non testables", summary["untestable"]),
        ("Écartées par décision humaine", summary["discarded"]),
    ):
        overview.append([label, value])
    overview.append([])
    type_block_row = overview.max_row + 1
    overview.append(["Par type d'exigence", ""])
    for kind, counts in summary["by_kind"].items():
        overview.append([f"  {kind} couvertes / total", f"{counts['covered']} / {counts['total']}"])
    type_block_last_row = overview.max_row

    # Sheet two: the traceability matrix, the proof nothing was forgotten
    trace = workbook.create_sheet(sheet_title("Traçabilité", used_names))
    _write_header(trace, _TRACE_COLUMNS)
    for row in requirement_rows(state):
        trace.append(
            [
                row["ref"],
                row["kind"],
                row["parent"],
                row["statement"],
                row["status"],
                row["reason"],
                ", ".join(row["scenarios"]),
                ", ".join(str(test["id"]) for test in row["tests"]),
            ]
        )
    # Banded per use case: the matrix is read use case by use case
    _finish_sheet(trace, _TRACE_COLUMNS, band_on=2)

    # Then one sheet per (requirement type, rattachement), one row per step.
    grammar = _grammar_of(state)
    tests_by_group = _tests_by_group(state, tests_by_scenario)
    for key in sorted(tests_by_group, key=natural_key):
        sheet = workbook.create_sheet(sheet_title(key, used_names))
        _write_header(sheet, _TEST_COLUMNS)
        for entry, test in tests_by_group[key]:
            for line in _test_rows(entry, [test], grammar):
                sheet.append(line)
        # Banded per test, since a test spans one row per step
        _finish_sheet(sheet, _TEST_COLUMNS, band_on=_TEST_ID_COLUMN)

    # One row per data_rows entry, tagged with the test's ID and its type sheet
    # (FR-NEW-078): a single "Détail" column, never one per key (DEC-026).
    data_sheet = workbook.create_sheet(sheet_title("Jeux de données", used_names))
    _write_header(data_sheet, _DATA_ROW_COLUMNS)
    for key in sorted(tests_by_group, key=natural_key):
        for _entry, test in tests_by_group[key]:
            for data_row in test.get("data_rows") or []:
                data_sheet.append(
                    [
                        test.get("id", ""),
                        test.get("name", ""),
                        " | ".join(f"{k}: {v}" for k, v in data_row.items()),
                        key,
                    ]
                )
    _finish_sheet(data_sheet, _DATA_ROW_COLUMNS, band_on=0)

    discards = [d for d in state.get("discards") or [] if isinstance(d, dict)]
    if discards:
        sheet = workbook.create_sheet(sheet_title("Écarts", used_names))
        _write_header(sheet, _DISCARD_COLUMNS)
        for discard in sorted(discards, key=lambda d: natural_key(d.get("reason", ""))):
            sheet.append(
                [
                    discard.get("what", ""),
                    discard.get("reason", ""),
                    ", ".join(str(ref) for ref in discard.get("refs") or []),
                    discard.get("decision", "proposed"),
                ]
            )
        _finish_sheet(sheet, _DISCARD_COLUMNS)

    # One row per section the numbering declares, even one left with nothing attached
    # to it (FR-NEW-073): absence here would read as "nothing to report" rather than the
    # truth, "this section was not read".
    analysis = workbook.create_sheet(sheet_title("Analyse", used_names))
    _write_header(analysis, _ANALYSIS_COLUMNS)
    for section, title, found, attached, scenario_ids, discard_labels in _analysis_rows(state, grammar):
        analysis.append(
            [
                section,
                title,
                found,
                attached,
                ", ".join(scenario_ids),
                ", ".join(discard_labels),
            ]
        )
    _finish_sheet(analysis, _ANALYSIS_COLUMNS)

    _add_legend_and_cross_reference(overview, workbook, trace.title, type_block_row, type_block_last_row)
    _finish_sheet(overview, _SUMMARY_COLUMNS)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _add_legend_and_cross_reference(
    overview: Worksheet, workbook: Workbook, trace_sheet_name: str, type_block_row: int, type_block_last_row: int
) -> None:
    """Légende des onglets (FR-NEW-071) and the renvoi croisé vers la Traçabilité
    (FR-NEW-072): only the sheets this workbook actually created, and the real sheet name
    it produced, never a hardcoded "Traçabilité".
    """
    overview.append([])
    overview.append(["Légende des onglets", ""])
    for name in workbook.sheetnames:
        overview.append([f"  {name}", _sheet_description(name)])

    trace_target = f"#'{trace_sheet_name}'!A1"
    for row_number in range(type_block_row, type_block_last_row + 1):
        cell = overview.cell(row=row_number, column=1)
        cell.hyperlink = Hyperlink(ref=cell.coordinate, target=trace_target)
