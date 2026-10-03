"""The QC export: a second workbook, one sheet, shaped for ALM's Excel import.

The recette workbook (workbook.py) is untouched by this increment. This is a distinct
artefact (FR-NEW-034): Quality Center's public import plugin refuses requirement
coverage, so the references travel concatenated into Test Name instead (DEC-001). The
format here is our own invention, isolated in this module precisely so it can be revised
locally once a real QC import file is available (section 15).
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from tgi.classification import classification_of
from tgi.grammar import Grammar, infer_grammar
from tgi.workbook import onglet_type_name

_SHEET_NAME = "QC"
_HEADER = [
    "Subject",
    "Test Name",
    "Description",
    "Classification",
    "Step Name",
    "Step Description",
    "Expected Results",
]

# Excel rejects a cell beyond this many characters.
_MAX_CELL_CHARS = 32767


def _truncate(value: str) -> str:
    """Excel refuses a cell beyond 32767 characters (FR-NEW-038)."""
    if len(value) <= _MAX_CELL_CHARS:
        return value
    return value[: _MAX_CELL_CHARS - 1] + "…"


def _grammar_of(state: dict[str, Any]) -> Grammar:
    """Rebuild the numbering grammar from the requirements a run already extracted.

    Same reconstruction as `workbook._grammar_of`, duplicated rather than imported because
    that helper is private to its module.
    """
    refs = [str(r.get("ref")) for r in state.get("requirements") or [] if isinstance(r, dict) and r.get("ref")]
    text = " ".join(ref for ref in refs for _ in range(5))
    return infer_grammar(text)


def build_qc_workbook(state: dict[str, Any]) -> tuple[bytes, list[str]]:
    """Return the QC xlsx bytes and the warnings produced while building it.

    One row per step, Subject and Test Name repeated on every row of the same test: that
    repetition is ALM's own rule for grouping steps under one test on import (FR-NEW-035).
    """
    warnings: list[str] = []
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _SHEET_NAME
    sheet.append(_HEADER)

    grammar = _grammar_of(state)

    for scenario in state.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        for test in scenario.get("tests") or []:
            if not isinstance(test, dict):
                continue
            refs = [str(ref) for ref in test.get("requirement_refs") or []]
            if refs:
                subject = onglet_type_name(refs[0], grammar)
            else:
                subject = "INCONNU"
                warnings.append(f"test sans référence d'exigence: {test.get('id', '')}")

            classification = classification_of(refs, grammar)
            joined_refs = ", ".join(refs)
            test_name = f"TRA_{test.get('id', '')}_{test.get('name', '')}__{joined_refs}"
            description = str(test.get("description") or "")
            if refs:
                description = f"{description}\nExigences validées : {', '.join(refs)}"

            steps = [step for step in (test.get("steps") or []) if isinstance(step, dict)]
            for step in steps:
                sheet.append(
                    [
                        _truncate(subject),
                        _truncate(test_name),
                        _truncate(description),
                        classification,
                        f"Étape {step.get('order', '')}",
                        _truncate(str(step.get("description", ""))),
                        _truncate(str(step.get("expected_result", ""))),
                    ]
                )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), warnings
