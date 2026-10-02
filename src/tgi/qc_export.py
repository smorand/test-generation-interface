"""The QC export: a second workbook, one sheet, shaped for ALM's Excel import.

The recette workbook (workbook.py) is untouched by this increment. This is a distinct
artefact (FR-NEW-034): Quality Center's public import plugin refuses requirement
coverage, so the references travel concatenated into Test Name instead (DEC-001). The
format here is our own invention, isolated in this module precisely so it can be revised
locally once a real QC import file is available (section 15).
"""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import Workbook

_SHEET_NAME = "QC"
_HEADER = ["Subject", "Test Name", "Description", "Step Name", "Step Description", "Expected Results"]

# Excel rejects a cell beyond this many characters.
_MAX_CELL_CHARS = 32767

_LAST_SEGMENT_PREFIX_RE = re.compile(r"^([A-Za-z]+)")

_TYPE_BY_PREFIX = {
    "RM": "RM",
    "EM": "EMOE",
    "M": "IHM",
    "N": "IHM",
    "T": "IHM",
}


def _truncate(value: str) -> str:
    """Excel refuses a cell beyond 32767 characters (FR-NEW-038)."""
    if len(value) <= _MAX_CELL_CHARS:
        return value
    return value[: _MAX_CELL_CHARS - 1] + "…"


def _requirement_type(ref: str) -> tuple[str, str]:
    """TYPE for the first reference of a test, and the prefix it was read from (FR-NEW-036)."""
    last_segment = ref.rsplit(".", maxsplit=1)[-1]
    match = _LAST_SEGMENT_PREFIX_RE.match(last_segment)
    prefix = match.group(1).upper() if match else ""
    return _TYPE_BY_PREFIX.get(prefix, "INCONNU"), prefix


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

    titles = {str(k): str(v) for k, v in (state.get("containers") or {}).items()}

    for scenario in state.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        container = str(scenario.get("container") or "")
        use_case_title = titles.get(container, "")
        scenario_id = str(scenario.get("id", ""))

        for test in scenario.get("tests") or []:
            if not isinstance(test, dict):
                continue
            refs = [str(ref) for ref in test.get("requirement_refs") or []]
            if refs:
                type_, prefix = _requirement_type(refs[0])
                if type_ == "INCONNU":
                    warnings.append(f"préfixe d'exigence inconnu: {prefix} ({refs[0]})")
            else:
                type_ = "INCONNU"

            subject = f"{container or scenario_id}-{type_}_{use_case_title}_{scenario_id}"
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
                        f"Étape {step.get('order', '')}",
                        _truncate(str(step.get("description", ""))),
                        _truncate(str(step.get("expected_result", ""))),
                    ]
                )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), warnings
