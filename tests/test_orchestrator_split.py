"""Tests for the pure document-splitting logic in the orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tgi.agents.orchestrator import split_document

if TYPE_CHECKING:
    import pytest


def test_split_empty_document() -> None:
    result = split_document("")
    assert result == []


def test_split_single_paragraph() -> None:
    result = split_document("Une seule regle metier simple.")
    assert len(result) == 1
    bloc = result[0]
    assert bloc["id"] == "bloc-1"
    assert bloc["status"] == "pending"
    assert bloc["judge_passes"] == 0
    assert bloc["tests"] == []
    assert bloc["rules"] == []
    assert bloc["chunk"] == "Une seule regle metier simple."
    assert bloc["title"] == "Une seule regle metier simple."


def test_split_paragraph_path_respects_chunk_size() -> None:
    # No headings: paragraph merge path, small chunk_size forces multiple blocs
    paragraphs = [("Paragraphe numero %d contenu." % i) * 5 for i in range(6)]
    text = "\n\n".join(paragraphs)
    result = split_document(text, chunk_size=100)
    assert len(result) > 1
    for i, bloc in enumerate(result):
        assert bloc["id"] == f"bloc-{i + 1}"


def test_split_heading_path() -> None:
    text = (
        "# Section Un\n"
        "Contenu de la premiere section avec du texte.\n\n"
        "# Section Deux\n"
        "Contenu de la deuxieme section avec du texte."
    )
    result = split_document(text, chunk_size=50)
    # Two headings, small chunk size keeps them separate
    assert len(result) >= 2
    titles = [b["title"] for b in result]
    assert any("Section" in t for t in titles)


def test_split_heading_merge_small_sections() -> None:
    text = "# A\ntexte a\n\n# B\ntexte b\n\n# C\ntexte c"
    result = split_document(text, chunk_size=10000)
    # Large chunk size merges all sections into one bloc
    assert len(result) == 1


def test_split_title_extracted_from_first_line() -> None:
    text = "### Titre du bloc\nDetail apres le titre."
    result = split_document(text)
    assert result[0]["title"] == "Titre du bloc"


def test_split_title_truncated_to_80() -> None:
    long_first = "x" * 200
    result = split_document(long_first)
    assert len(result[0]["title"]) <= 80


def test_split_uses_markdown_headings_as_boundaries() -> None:
    text = "# Titre A\n\nregle a\n\n# Titre B\n\nregle b"
    blocs = split_document(text, chunk_size=20)
    # Each section is its own bloc, and the title comes from the heading
    assert [b["title"] for b in blocs] == ["Titre A", "Titre B"]


def test_split_cuts_a_section_larger_than_the_budget() -> None:
    """A single oversized section must still be cut, or no model could read it."""
    big = "\n\n".join(f"paragraphe numero {i} avec du contenu" for i in range(60))
    text = f"# Grande section\n\n{big}"
    blocs = split_document(text, chunk_size=500, overlap=0)
    assert len(blocs) > 1
    assert all(len(b["chunk"]) <= 700 for b in blocs)


def test_split_applies_overlap_only_on_forced_cuts() -> None:
    big = "\n\n".join(f"phrase distincte numero {i}" for i in range(40))
    text = f"# Section\n\n{big}"
    with_overlap = split_document(text, chunk_size=400, overlap=120)
    without = split_document(text, chunk_size=400, overlap=0)
    # Overlap repeats the tail of the previous chunk, so total text grows
    assert sum(len(b["chunk"]) for b in with_overlap) > sum(len(b["chunk"]) for b in without)


def test_split_title_prefers_heading_over_overlap_tail() -> None:
    big = "\n\n".join(f"contenu de paragraphe {i}" for i in range(40))
    text = f"## Ma section\n\n{big}"
    blocs = split_document(text, chunk_size=400, overlap=100)
    # Every bloc of the section keeps a meaningful title, not a fragment
    assert blocs[0]["title"] == "Ma section"
    assert all(b["title"] for b in blocs)


def test_split_title_skips_table_rows() -> None:
    text = "colonne A | colonne B\n\nUne phrase de prose."
    blocs = split_document(text, chunk_size=4000)
    assert blocs[0]["title"] == "Une phrase de prose."


def test_split_respects_configured_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "chunk_size", 100)
    monkeypatch.setattr(settings, "chunk_overlap", 0)
    text = "\n\n".join(f"paragraphe {i} un peu long pour depasser" for i in range(10))
    blocs = split_document(text)
    assert len(blocs) > 1
