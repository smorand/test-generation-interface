"""Shared, deterministic MOA/MOE classification of a test from its requirement references.

No LLM call: the classification is arithmetic over `Grammar.kind_of`, shared between the
recette workbook (workbook.py) and the QC export (qc_export.py) so neither duplicates it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tgi.grammar import Grammar

_MOE_KINDS = {"RM", "EM"}
_MOA_KINDS = {"M", "N", "T"}


def classification_of(refs: list[str], grammar: Grammar) -> str:
    """Classify: MOA if every reference is IHM, MOE if every reference is RM/EMOE, else MOA/MOE.

    A test with no reference is "INCONNU" (FR-NEW-074).
    """
    if not refs:
        return "INCONNU"
    kinds = {grammar.kind_of(ref) for ref in refs}
    is_moa = bool(kinds & _MOA_KINDS)
    is_moe = bool(kinds & _MOE_KINDS)
    if is_moa and is_moe:
        return "MOA/MOE"
    if is_moa:
        return "MOA"
    return "MOE"
