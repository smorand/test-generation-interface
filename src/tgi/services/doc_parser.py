"""Document parser: Word (.docx), PDF, plain text to clean text."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Word style names that carry the document outline. Templates often add their own
# (H2, Titre 3), so matching is done on a trailing level digit.
_HEADING_STYLE_RE = re.compile(r"^(?:heading|titre|h)\s*([1-6])$", re.IGNORECASE)
_MAX_HEADING_LEVEL = 6


def _heading_level(style_name: str) -> int:
    """Markdown level for a Word style name, 0 when it is not a heading."""
    match = _HEADING_STYLE_RE.match(style_name.strip())
    if not match:
        return 0
    return min(_MAX_HEADING_LEVEL, int(match.group(1)))


def _is_comment_style(style_name: str) -> bool:
    """True for review/comment styles whose text is not part of the specification."""
    lowered = style_name.strip().lower()
    return "comment" in lowered or "commentaire" in lowered


def _iter_blocks(document: Any) -> Iterator[Any]:
    """Yield paragraphs and tables in the order they appear in the document.

    python-docx exposes doc.paragraphs and doc.tables as separate flat lists, which
    loses the interleaving.
    """
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


class DocParser:
    """Parse various document formats into clean plain text."""

    __slots__ = ()

    def parse(self, path: str | Path) -> str:
        """Auto-detect format and return clean text."""
        p = Path(path)
        suffix = p.suffix.lower()

        if suffix == ".docx":
            return self._parse_docx(p)
        if suffix == ".pdf":
            return self._parse_pdf(p)
        if suffix in {".txt", ".md", ".rst", ""}:
            return self._parse_text(p)

        # Fallback: try text
        logger.warning("Unknown extension %s, trying plain text", suffix)
        return self._parse_text(p)

    def _parse_docx(self, path: Path) -> str:
        doc = Document(str(path))
        parts: list[str] = []
        skipped_comments = 0

        # Walk paragraphs and tables in document order. Emitting every table at the
        # end instead detaches specification tables from their heading, which
        # produced one gigantic heading-less blob for table driven documents.
        for block in _iter_blocks(doc):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                style = str(getattr(block.style, "name", "") or "")
                if _is_comment_style(style):
                    # Hidden review comments are not specification content: feeding
                    # them to the extractor invents rules the document never stated.
                    skipped_comments += 1
                    continue
                level = _heading_level(style)
                # Keep the outline as markdown so the splitter can cut on real
                # section boundaries instead of arbitrary character counts.
                parts.append(f"{'#' * level} {text}" if level else text)
            elif isinstance(block, Table):
                for row in block.rows:
                    row_parts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_parts:
                        parts.append(" | ".join(row_parts))

        if skipped_comments:
            logger.info("Skipped %d hidden comment paragraph(s) in %s", skipped_comments, path.name)
        return "\n\n".join(parts)

    def _parse_pdf(self, path: Path) -> str:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text.strip())

        return "\n\n".join(parts)

    def _parse_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace").strip()


doc_parser = DocParser()
