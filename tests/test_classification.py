"""Tests for the shared MOA/MOE classification module."""

from __future__ import annotations

from tgi.classification import classification_of
from tgi.grammar import Grammar


def test_classification_of_mixed_refs_is_moa_moe() -> None:
    grammar = Grammar()
    refs = ["EU01.CU01.RM01", "E04.M01"]
    assert classification_of(refs, grammar) == "MOA/MOE"
    assert classification_of(["EU01.CU01.RM02"], grammar) == "MOE"
    assert classification_of(["E04.M02"], grammar) == "MOA"


def test_classification_of_no_refs_is_inconnu() -> None:
    assert classification_of([], Grammar()) == "INCONNU"
