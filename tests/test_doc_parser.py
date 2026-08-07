"""Tests for the document parser."""

from __future__ import annotations

from pathlib import Path

from tgi.services.doc_parser import DocParser


def test_parse_txt(tmp_path: Path) -> None:
    f = tmp_path / "spec.txt"
    f.write_text("  Regle metier en texte.  ", encoding="utf-8")
    assert DocParser().parse(f) == "Regle metier en texte."


def test_parse_md(tmp_path: Path) -> None:
    f = tmp_path / "spec.md"
    f.write_text("# Titre\ncontenu", encoding="utf-8")
    assert "Titre" in DocParser().parse(f)


def test_parse_unknown_extension_falls_back_to_text(tmp_path: Path) -> None:
    f = tmp_path / "spec.xyz"
    f.write_text("contenu brut", encoding="utf-8")
    assert DocParser().parse(f) == "contenu brut"


def test_parse_no_extension(tmp_path: Path) -> None:
    f = tmp_path / "README"
    f.write_text("sans extension", encoding="utf-8")
    assert DocParser().parse(f) == "sans extension"


def test_parse_accepts_string_path(tmp_path: Path) -> None:
    f = tmp_path / "spec.txt"
    f.write_text("string path", encoding="utf-8")
    assert DocParser().parse(str(f)) == "string path"


def test_parse_docx(tmp_path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("Premier paragraphe.")
    doc.add_paragraph("Deuxieme paragraphe.")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "cellA"
    table.rows[0].cells[1].text = "cellB"
    path = tmp_path / "spec.docx"
    doc.save(str(path))

    result = DocParser().parse(path)
    assert "Premier paragraphe." in result
    assert "Deuxieme paragraphe." in result
    assert "cellA | cellB" in result
