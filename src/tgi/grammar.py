"""Read the numbering a specification gives itself, without assuming its vocabulary.

A functional specification numbers its own content, and that numbering is the only
trustworthy skeleton available: measured on a real document, extraction finds 51 of 51 use
cases and 401 of 401 requirements with no orphan, where a model asked the same question
found 46 and fabricated references as soon as it was interrogated about a named one.

So the levels are inferred rather than hardcoded. Counting prefixes per position over the
whole identifier population of the reference document gives position 0 as F or E, position 1
as EU, M, N or T, position 2 as CU, position 3 as RM or EM. The prefix dominating the
deepest shared position is the leaf, the one above it is the container, and a document
writing UC instead of CU is read just as well.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from tgi.deliverable import natural_key

logger = logging.getLogger(__name__)

# A segment is letters then digits, with an optional letter suffix: RM01, RM07a, VAL01
_SEGMENT = r"[A-Za-z]{1,6}\d+[a-z]?"
_REFERENCE_RE = re.compile(rf"\b{_SEGMENT}(?:\.{_SEGMENT})+\b")
_PREFIX_RE = re.compile(r"^[A-Za-z]+")
# The reference must be matched greedily and segment by segment: a lazy pattern stops at
# the first letter and turns "F03.EU08.CU01 Notification" into the reference "F".
_HEADING_RE = re.compile(
    rf"^#{{1,6}}\s*(?P<ref>{_SEGMENT}(?:\.{_SEGMENT})*)\s*[:\-\u2013]?\s+(?P<title>.+)$",
    re.MULTILINE,
)
_WHITESPACE_RE = re.compile(r"\s+")
# A statement says something: at least one word of three characters or more
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# A bullet, in the forms the parsers emit for a Word list
_LIST_ITEM_RE = re.compile(r"^(?:[-\u2013\u2022*o]\s|\d+[.)]\s)")
# A declaration starts its own line, optionally under heading marks. Measured on the
# reference document, 19 of the 20 requirements left without a statement were declared in a
# table, and only cited in prose: taking the first occurrence read the citation.
_DECLARATION_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s*)?(?P<ref>{_SEGMENT}(?:\.{_SEGMENT})+)\s*(?P<rest>.*)$",
)

# A prefix seen once is a typo or a stray label, not a level of the numbering
_MIN_PREFIX_SUPPORT = 3
# How much text after an identifier is kept as its statement
_STATEMENT_CHARS = 300
# A table row states the wording, the kind and the trigger, so a declaration is allowed to be
# longer than a sentence of prose, but not so long that the table becomes unreadable. The
# median statement measured is 146 characters.
_DECLARATION_CHARS = 400
# Below this length, a line ending without punctuation is a section title, not a statement
_TITLE_CHARS = 60


@dataclass(frozen=True)
class Level:
    """One level of the numbering, for example CU at depth 2."""

    depth: int
    prefix: str
    count: int


@dataclass(frozen=True)
class Axis:
    """One family of identifiers, with its own depth.

    Measured on the reference document, families do not share a depth: the functional one
    is F.EU.CU.RM, four segments, while screens are E.M or E.N, two. A single global depth
    silently drops the shorter families, which is how 205 screen references ended up
    treated as noise.
    """

    prefix: str
    leaf_depth: int
    container_depth: int
    leaf_prefixes: tuple[str, ...]
    count: int


@dataclass
class Requirement:
    """A numbered element of the specification, quoted from the document."""

    ref: str
    kind: str
    statement: str
    parent: str
    axis: str = ""
    title: str = ""


@dataclass
class Grammar:
    """The numbering scheme a document actually uses, one entry per family."""

    levels: dict[int, list[Level]] = field(default_factory=dict)
    axes: dict[str, Axis] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return bool(self.axes)

    def axis_of(self, ref: str) -> Axis | None:
        match = _PREFIX_RE.match(ref)
        return self.axes.get(match.group(0).upper()) if match else None

    def is_container(self, ref: str) -> bool:
        """True when the reference names a container rather than a statement."""
        axis = self.axis_of(ref)
        return axis is not None and len(ref.split(".")) <= axis.container_depth + 1

    def container_of(self, ref: str) -> str:
        """The container a leaf belongs to, empty when the family has none."""
        axis = self.axis_of(ref)
        if axis is None or axis.container_depth < 0:
            return ""
        segments = ref.split(".")
        if len(segments) <= axis.container_depth:
            return ""
        return ".".join(segments[: axis.container_depth + 1])

    def prefix_at(self, ref: str, depth: int) -> str:
        segments = ref.split(".")
        if depth >= len(segments):
            return ""
        match = _PREFIX_RE.match(segments[depth])
        return match.group(0).upper() if match else ""

    def kind_of(self, ref: str) -> str:
        """The prefix of the last segment: RM, EM, M, N, and so on."""
        return self.prefix_at(ref, len(ref.split(".")) - 1)


def references_in(text: str) -> list[str]:
    """Every dotted identifier the text contains, in order of appearance."""
    return [match.group(0).upper() for match in _REFERENCE_RE.finditer(text)]


def infer_grammar(text: str) -> Grammar:
    """Derive the numbering families from the identifiers the document contains.

    Each family is inferred on its own: its leaves sit at the deepest position it reaches
    with broad support, its container one position above. A prefix seen once or twice is a
    typo or a stray label, never a level.
    """
    by_depth: defaultdict[int, Counter[str]] = defaultdict(Counter)
    per_axis_depth: defaultdict[str, Counter[int]] = defaultdict(Counter)
    per_axis_leaves: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_axis_count: Counter[str] = Counter()

    for ref in references_in(text):
        segments = ref.split(".")
        head = _PREFIX_RE.match(segments[0])
        if head is None:
            continue
        family_prefix = head.group(0).upper()
        per_axis_count[family_prefix] += 1
        per_axis_depth[family_prefix][len(segments) - 1] += 1
        tail = _PREFIX_RE.match(segments[-1])
        if tail:
            per_axis_leaves[family_prefix][tail.group(0).upper()] += 1
        for depth, segment in enumerate(segments):
            match = _PREFIX_RE.match(segment)
            if match:
                by_depth[depth][match.group(0).upper()] += 1

    levels = {
        depth: [Level(depth, prefix, count) for prefix, count in counter.most_common() if count >= _MIN_PREFIX_SUPPORT]
        for depth, counter in by_depth.items()
    }
    levels = {depth: found for depth, found in levels.items() if found}

    axes: dict[str, Axis] = {}
    for prefix, depths in per_axis_depth.items():
        if per_axis_count[prefix] < _MIN_PREFIX_SUPPORT:
            continue
        leaf_depth = max(depth for depth, count in depths.items() if count >= _MIN_PREFIX_SUPPORT) if depths else 0
        leaves = tuple(leaf for leaf, count in per_axis_leaves[prefix].most_common() if count >= _MIN_PREFIX_SUPPORT)
        axes[prefix] = Axis(
            prefix=prefix,
            leaf_depth=leaf_depth,
            container_depth=leaf_depth - 1,
            leaf_prefixes=leaves,
            count=per_axis_count[prefix],
        )

    grammar = Grammar(levels=levels, axes=axes)
    for family in axes.values():
        logger.info(
            "Numbering family %s: leaves %s at depth %d, container at depth %d, %d references",
            family.prefix,
            "/".join(family.leaf_prefixes),
            family.leaf_depth,
            family.container_depth,
            family.count,
        )
    return grammar


def titles_in(text: str) -> dict[str, str]:
    """Titles a document gives to its identifiers through headings."""
    titles: dict[str, str] = {}
    for match in _HEADING_RE.finditer(text):
        ref = match.group("ref").upper().rstrip(".")
        title = match.group("title").strip()
        if title and ref not in titles:
            titles[ref] = title
    return titles


def extract_requirements(text: str, grammar: Grammar | None = None) -> list[Requirement]:
    """Every numbered element with the sentence that states it, quoted from the document.

    Deduplicated on the reference: a specification repeats an identifier in reminders and
    cross references, and the first statement is the declaring one.
    """
    grammar = grammar or infer_grammar(text)
    titles = titles_in(text)
    declarations = _declarations(text)
    flat = _WHITESPACE_RE.sub(" ", text)

    found: dict[str, Requirement] = {}
    for match in _REFERENCE_RE.finditer(flat):
        ref = match.group(0).upper()
        if ref in found:
            continue
        # A container is not a requirement: F03.EU05.CU01 names a use case, and only what
        # sits below it states something testable.
        if grammar.is_container(ref):
            continue
        # The statement stops at the next identifier: a specification lists them one after
        # another, and reading past the boundary attributes a neighbour's sentence.
        tail = flat[match.end() : match.end() + _STATEMENT_CHARS]
        following = _REFERENCE_RE.search(tail)
        if following:
            tail = tail[: following.start()]
        statement = tail.split(" ###")[0].split(" ##")[0].lstrip(" :-\u2013.").strip()
        # The line where the document declares a reference always wins over an occurrence
        # found in running text: a citation carries no statement of its own, and reading one
        # left a requirement with an empty statement that no reviewer could act on. Preferring
        # whichever was longer was not enough, since a citation running into the next
        # paragraph is longer than the declaration it cites.
        statement = declarations.get(ref) or statement
        # Punctuation is not a statement. A citation between parentheses left ")." behind,
        # which reads as a wording and is worse than an honest blank: the reference E01.N0x,
        # a number the specification never decided, looked documented.
        if not _WORD_RE.search(statement):
            statement = ""
        axis = grammar.axis_of(ref)
        found[ref] = Requirement(
            ref=ref,
            kind=grammar.kind_of(ref),
            statement=statement,
            parent=grammar.container_of(ref),
            axis=axis.prefix if axis else "",
            title=titles.get(ref, ""),
        )
    return list(found.values())


def _continues_after_blank(paragraph: list[str], rest: list[str]) -> bool:
    """Whether a statement continues past a blank line.

    It usually does: the reference document states a second case of the same rule in the next
    paragraph, and cutting at the blank line dropped it. What must not be swallowed is the
    title of the following section, and this document writes those as plain lines rather than
    as headings, so structure cannot separate them. The shape can: a title is short and ends
    without punctuation, "Présentation détaillée", where a continuation is a sentence or a
    bullet. A bullet is never a title, and a colon announces a list, both checked first.
    """
    following = next((line.strip() for line in rest if line.strip()), "")
    if not following or _DECLARATION_RE.match(following) or following.startswith("#"):
        return False
    if _LIST_ITEM_RE.match(following) or (paragraph and paragraph[-1].rstrip().endswith(":")):
        return True
    return not _looks_like_a_title(following)


def _looks_like_a_title(line: str) -> bool:
    """A short line that ends without punctuation announces a section, it states nothing."""
    return len(line) < _TITLE_CHARS and not line.rstrip().endswith((".", "!", "?", "\u00bb", ":", ";", ")"))


def _declarations(text: str) -> dict[str, str]:
    """The statement of every reference the document declares at the start of a line.

    A specification states a message or a notification in a table, one row per identifier,
    and only cites it in prose. Reading the first occurrence therefore read the citation and
    left the requirement with no statement at all, which is unreviewable: an uncovered
    requirement with no wording tells nobody what to test. Measured on the reference
    document, 19 of the 20 statements missing were declared in a table.
    """
    lines = text.splitlines()
    starts: list[tuple[int, str, str]] = []
    for number, line in enumerate(lines):
        match = _DECLARATION_RE.match(line)
        if match:
            starts.append((number, match.group("ref").upper(), match.group("rest")))

    declarations: dict[str, str] = {}
    for index, (number, ref, rest) in enumerate(starts):
        if ref in declarations:
            continue
        limit = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        block = _block_of(lines, number, rest, limit)
        statement = _row_statement(block) if "|" in rest else _prose_statement(block)
        if statement:
            declarations[ref] = statement
    return declarations


def _block_of(lines: list[str], number: int, rest: str, limit: int) -> list[str]:
    """The lines a declaration may draw from: up to the next one, and never past a heading."""
    block = [rest, *lines[number + 1 : limit]]
    for offset, line in enumerate(block):
        if line.lstrip().startswith("#"):
            return block[:offset]
    return block


def _row_statement(block: list[str]) -> str:
    """A table row, joined so the wording, the kind and the trigger are read together.

    A row is not one line: the parser breaks cells over several lines and a cell can hold a
    blank one. But running to the next declaration crossed section boundaries and produced
    700 character statements ending in the next chapter, so a row tolerates one blank line
    and stops once what follows it has left the table.
    """
    row: list[str] = []
    after_blank = False
    for line in block:
        stripped = line.strip()
        if not stripped:
            after_blank = True
            continue
        if after_blank and "|" not in stripped:
            break
        row.append(stripped)
        after_blank = False
    cells = [cell.strip(" :-\u2013.\u00a0") for cell in " ".join(row).split("|")]
    return " \u00b7 ".join(cell for cell in cells if cell)[:_DECLARATION_CHARS]


def _prose_statement(block: list[str]) -> str:
    """Prose, up to the blank line that ends it, unless the statement continues past it."""
    paragraph: list[str] = []
    for offset, line in enumerate(block):
        stripped = line.strip()
        if stripped:
            paragraph.append(stripped)
        elif not _continues_after_blank(paragraph, block[offset + 1 :]):
            break
    return " ".join(paragraph).lstrip(" :-\u2013.\u00a0").strip()[:_DECLARATION_CHARS]


def containers(requirements: list[Requirement], text: str = "") -> dict[str, str]:
    """Container references, with the title the document gives them when it gives one.

    A container appearing only inside its leaves' identifiers has no title, and the human
    names it: measured on the reference document, 49 of 51 use cases carry a heading.
    """
    titles = titles_in(text) if text else {}
    result: dict[str, str] = {}
    for requirement in requirements:
        if requirement.parent:
            result.setdefault(requirement.parent, titles.get(requirement.parent, ""))
    for ref, title in titles.items():
        if ref in result and title:
            result[ref] = title
    return result


def axes_of(requirements: list[Requirement]) -> dict[str, list[Requirement]]:
    """Group requirements by the family their numbering belongs to.

    The reference document numbers four families and the first pipeline recognised one:
    functional (F, EU, CU, RM or EM), screens (E with M or N), batch processes (T), then
    prose. Grouping by the prefix at depth 0 separates them without naming any of them.
    """
    grouped: defaultdict[str, list[Requirement]] = defaultdict(list)
    for requirement in requirements:
        match = _PREFIX_RE.match(requirement.ref)
        grouped[match.group(0).upper() if match else "?"].append(requirement)
    return {prefix: sorted(items, key=lambda r: r.ref) for prefix, items in sorted(grouped.items())}


def keep_known_references(candidates: Any, text: str) -> list[str]:
    """Keep only the identifiers the document really contains, case insensitively.

    The guard that makes model output usable: asked about one named use case, a model
    returned 17 references where the document declares 1. It costs a regex and no call.
    """
    known = {ref.upper() for ref in references_in(text)}
    known.update(ref.upper() for ref in re.findall(rf"\b{_SEGMENT}\b", text))
    if not isinstance(candidates, list):
        return []
    kept: list[str] = []
    for candidate in candidates:
        ref = str(candidate).strip().upper()
        if ref in known and ref not in kept:
            kept.append(ref)
    return kept


def section_of(text: str, ref: str, max_chars: int = 6000) -> str:
    """The document section a reference titles, cut at the next heading of the same rank.

    This is the evidence a generator needs: the paragraphs the specification wrote under
    that use case, not a chunk of fixed size that happens to overlap it.
    """
    target = ref.upper()
    for match in _HEADING_RE.finditer(text):
        if match.group("ref").upper().rstrip(".") != target:
            continue
        hashes = len(text[match.start() : match.end()]) - len(text[match.start() : match.end()].lstrip("#"))
        rest = text[match.end() :]
        boundary = re.search(rf"^#{{1,{max(hashes, 1)}}}\s", rest, re.MULTILINE)
        section = rest[: boundary.start()] if boundary else rest
        return (match.group(0) + section)[:max_chars].strip()
    return ""


def natural_sort_key(value: Any) -> tuple[tuple[int, int | str], ...]:
    """Sort identifiers so RM9 comes before RM10, shared with the deliverable tree."""
    return natural_key(value)
