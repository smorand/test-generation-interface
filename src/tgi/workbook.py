"""The reviewable workbook: the two reading axes, one sheet family each.

The JSON export serves tooling. This serves the human who has to sign off a test plan, so
it follows the specification's own numbering and stays sortable: no merged cells, a frozen
header, an autofilter on every sheet. The traceability sheet is what proves nothing was
forgotten, and it is the sheet a reviewer opens first.
"""

from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING, Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from tgi.coverage_report import coverage_summary, requirement_rows
from tgi.deliverable import UNPLACED, build_tree, natural_key

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


def _test_rows(scenario: Any, tests: list[dict[str, Any]]) -> list[list[Any]]:
    """One row per step, repeating the test columns so filters keep working."""
    rows: list[list[Any]] = []
    for test in tests:
        refs = ", ".join(str(ref) for ref in test.get("requirement_refs") or [])
        steps = [step for step in (test.get("steps") or []) if isinstance(step, dict)] or [{}]
        for step in steps:
            rows.append(
                [
                    scenario.container or UNPLACED,
                    scenario.id,
                    scenario.title,
                    scenario.kind,
                    test.get("id", ""),
                    test.get("name", ""),
                    test.get("description", ""),
                    step.get("order", ""),
                    step.get("description", ""),
                    step.get("expected_result", ""),
                    refs,
                    test.get("status", ""),
                ]
            )
        for data_row in test.get("data_rows") or []:
            rows.append(
                [
                    scenario.container or UNPLACED,
                    scenario.id,
                    scenario.title,
                    scenario.kind,
                    test.get("id", ""),
                    test.get("name", ""),
                    "jeu de données",
                    "",
                    " | ".join(f"{k}: {v}" for k, v in data_row.items()),
                    "",
                    refs,
                    test.get("status", ""),
                ]
            )
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
            ]
        )
    return rows


def build_workbook(state: dict[str, Any]) -> bytes:
    """Return the xlsx bytes for this project."""
    tree = build_tree(state)
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
    overview.append(["Par type d'exigence", ""])
    for kind, counts in summary["by_kind"].items():
        overview.append([f"  {kind} couvertes / total", f"{counts['covered']} / {counts['total']}"])
    _finish_sheet(overview, _SUMMARY_COLUMNS)

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

    # Then one sheet per functionality, one row per step
    chapters = list(tree["chapters"])
    if tree.get("unplaced"):
        chapters.append(tree["unplaced"])
    for chapter in chapters:
        sheet = workbook.create_sheet(sheet_title(chapter.key, used_names))
        _write_header(sheet, _TEST_COLUMNS)
        for group in chapter.groups:
            for scenario in group.scenarios:
                for line in _test_rows(scenario, tests_by_scenario.get(scenario.id, [])):
                    sheet.append(line)
        # Banded per test, since a test spans one row per step
        _finish_sheet(sheet, _TEST_COLUMNS, band_on=_TEST_ID_COLUMN)

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

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
