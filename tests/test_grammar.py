"""Tests for reading the numbering a specification gives itself."""

from __future__ import annotations

from tgi.grammar import (
    axes_of,
    containers,
    extract_requirements,
    infer_grammar,
    keep_known_references,
    references_in,
    titles_in,
)

# Shaped like the reference specification: a functional family four segments deep, a screen
# family two deep, and prose in between.
DOC = """
# Description du projet
Contexte sans identifiant, du blabla de cadrage.

### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations du portefeuille.
F01.EU01.CU01.RM02 : Le système masque les relations inactives.
F01.EU01.CU01.EM01 : L'utilisateur doit être authentifié.

### F01.EU01.CU02 Supprimer une relation
F01.EU01.CU02.RM01 : La suppression demande une confirmation.
F01.EU01.CU02.RM02a : Un GAC composé d'un seul GN affiche une ligne.

### F02.EU01.CU01 Déléguer temporairement
F02.EU01.CU01.RM01 : Le manager choisit un délégataire.

Écran E01, messages et notifications:
E01.M01 : « Aucune relation trouvée »
E01.M02 : « Opération impossible »
E01.M03 : « Champ obligatoire »
E01.N01 : Notification d'ajout d'une relation.
E01.N02 : Notification de retrait d'une relation.
E01.N03 : Notification de délégation.
"""


# ---------------------------------------------------------------------------
# Grammar inference
# ---------------------------------------------------------------------------


def test_grammar_is_inferred_per_family_not_globally() -> None:
    """A single global depth silently drops the shorter families."""
    grammar = infer_grammar(DOC)
    assert set(grammar.axes) == {"F", "E"}

    functional = grammar.axes["F"]
    assert functional.leaf_depth == 3
    assert functional.container_depth == 2
    assert "RM" in functional.leaf_prefixes

    screens = grammar.axes["E"]
    assert screens.leaf_depth == 1
    assert screens.container_depth == 0
    assert set(screens.leaf_prefixes) == {"M", "N"}


def test_the_use_case_level_is_found_without_naming_it() -> None:
    """A document writing UC instead of CU must be read just as well."""
    other = DOC.replace(".CU", ".UC")
    grammar = infer_grammar(other)
    requirements = extract_requirements(other, grammar)
    assert grammar.axes["F"].container_depth == 2
    assert {r.parent for r in requirements if r.axis == "F"} == {
        "F01.EU01.UC01",
        "F01.EU01.UC02",
        "F02.EU01.UC01",
    }


def test_a_prefix_seen_once_is_not_a_level() -> None:
    grammar = infer_grammar(DOC + "\nZZ01.QQ01 : une coquille isolee\n")
    assert "ZZ" not in grammar.axes


def test_a_document_without_numbering_yields_no_grammar() -> None:
    grammar = infer_grammar("Une specification en prose, sans le moindre identifiant.")
    assert not grammar.known
    assert extract_requirements("Que du texte libre.", grammar) == []


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


def test_requirements_carry_their_statement_kind_and_parent() -> None:
    requirements = {r.ref: r for r in extract_requirements(DOC)}
    rule = requirements["F01.EU01.CU01.RM01"]
    assert rule.kind == "RM"
    assert rule.parent == "F01.EU01.CU01"
    assert rule.axis == "F"
    assert "affiche les relations" in rule.statement
    assert requirements["F01.EU01.CU01.EM01"].kind == "EM"
    assert requirements["E01.M01"].parent == "E01"


def test_a_container_is_not_a_requirement() -> None:
    """F01.EU01.CU01 names a use case, only what sits below states something testable."""
    refs = {r.ref for r in extract_requirements(DOC)}
    assert "F01.EU01.CU01" not in refs
    assert "F01.EU01.CU01.RM01" in refs
    assert "E01" not in refs
    assert "E01.M01" in refs


def test_a_statement_stops_at_the_next_identifier() -> None:
    """Reading past the boundary attributes a neighbour's sentence."""
    requirements = {r.ref: r for r in extract_requirements(DOC)}
    assert "RM02" not in requirements["F01.EU01.CU01.RM01"].statement
    assert requirements["E01.M01"].statement.startswith("«")


def test_letter_suffixed_requirements_are_kept() -> None:
    refs = {r.ref for r in extract_requirements(DOC)}
    assert "F01.EU01.CU02.RM02A" in refs


def test_requirements_are_deduplicated_on_the_first_statement() -> None:
    """A specification repeats identifiers in reminders and cross references."""
    doubled = DOC + "\nRappel: F01.EU01.CU01.RM01 : reprise de la regle precedente.\n"
    requirements = [r for r in extract_requirements(doubled) if r.ref == "F01.EU01.CU01.RM01"]
    assert len(requirements) == 1
    assert "affiche les relations" in requirements[0].statement


# ---------------------------------------------------------------------------
# Containers, axes, titles
# ---------------------------------------------------------------------------


def test_containers_take_the_title_the_document_gives_them() -> None:
    requirements = extract_requirements(DOC)
    found = containers(requirements, DOC)
    assert found["F01.EU01.CU01"] == "Visualiser son portefeuille"
    assert found["F02.EU01.CU01"] == "Déléguer temporairement"
    # A screen introduced in prose has no heading, so no title, and a human names it
    assert found["E01"] == ""


def test_titles_are_read_greedily() -> None:
    """A lazy pattern turns "F03.EU08.CU01 Notification" into the reference "F"."""
    titles = titles_in("### F03.EU08.CU01 Notification d'ajout ou retrait\n")
    assert titles == {"F03.EU08.CU01": "Notification d'ajout ou retrait"}


def test_axes_group_by_family() -> None:
    grouped = axes_of(extract_requirements(DOC))
    assert set(grouped) == {"F", "E"}
    assert len(grouped["E"]) == 6
    assert [r.ref for r in grouped["E"]][:2] == ["E01.M01", "E01.M02"]


def test_references_in_reads_dotted_identifiers_only() -> None:
    found = references_in("voir F01.EU01.CU01.RM01 et E01.M02, mais pas R1 seul")
    assert found == ["F01.EU01.CU01.RM01", "E01.M02"]


# ---------------------------------------------------------------------------
# The guard on model output
# ---------------------------------------------------------------------------


def test_only_references_present_in_the_document_survive() -> None:
    """Asked about one named use case, a model returned 17 references where 1 exists."""
    kept = keep_known_references(
        ["F01.EU01.CU01.RM01", "F01.EU01.CU01.RM99", "f01.eu01.cu02.rm01", "n'importe quoi"],
        DOC,
    )
    assert kept == ["F01.EU01.CU01.RM01", "F01.EU01.CU02.RM01"]


def test_the_guard_is_case_insensitive_on_letter_suffixes() -> None:
    """RM07a broke this comparison twice before."""
    assert keep_known_references(["F01.EU01.CU02.RM02A"], DOC) == ["F01.EU01.CU02.RM02A"]


def test_the_guard_tolerates_anything_that_is_not_a_list() -> None:
    assert keep_known_references(None, DOC) == []
    assert keep_known_references("F01.EU01.CU01.RM01", DOC) == []
    assert keep_known_references([None, 12], DOC) == []


def test_a_requirement_declared_in_a_table_carries_its_wording() -> None:
    """Measured: 19 of the 20 requirements left without a statement were declared in a table.

    The document states its screen messages as table rows and only cites them in prose, so
    reading the first occurrence read the citation and left an uncovered requirement that no
    reviewer could act on: a reference, and nothing to test.
    """
    text = """
### E01 Composition du portefeuille

F03.EU03.CU01.RM02 Si c'est le cas, le système affiche un message E01.M05.

## Messages métier

ID | Type | Libellé | Conditions

E01.M05 | E | Relation déjà présente dans le portefeuille | Au retour d'un ajout manuel

E01.N01 | Information
Temps réel | Titre : Retrait d'un GAC
Texte : « Relation retirée du portefeuille. »

Archivage automatique sous 30 jours.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert "Relation déjà présente dans le portefeuille" in statements["E01.M05"]
    assert "Au retour d'un ajout manuel" in statements["E01.M05"]
    # A cell may hold a blank line, so the row survives it
    assert "Titre : Retrait d'un GAC" in statements["E01.N01"]
    assert "Relation retirée du portefeuille" in statements["E01.N01"]
    # but the row stops when the table does, instead of swallowing the next section
    assert "Archivage" not in statements["E01.N01"]


def test_a_statement_citing_another_requirement_is_not_cut_short() -> None:
    """Stopping at the next identifier truncated the sentence that cites one."""
    text = """
F01.EU01.CU05.RM04 Le système informe l'ancien RRC par une notification E01.N01.

F01.EU01.CU05.RM05 Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert statements["F01.EU01.CU05.RM04"].endswith("notification E01.N01.")


def test_prose_does_not_swallow_the_title_of_the_next_section() -> None:
    """This document writes section titles as plain lines, so shape has to separate them:
    short, and ending without punctuation."""
    text = """
F01.EU01.CU01.EM01 Chaque jour, le système identifie les changements.

Présentation détaillée

F01.EU01.CU01.EM02 Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert statements["F01.EU01.CU01.EM01"] == "Chaque jour, le système identifie les changements."


def test_a_statement_continued_in_the_next_paragraph_keeps_it() -> None:
    """The document states a second case of the same rule after a blank line, and cutting
    there dropped it: 16 rules of the reference document lost their conditions."""
    text = """
F01.EU01.CU01.RM03 Si le gestionnaire est un CAGE, le système l'ajoute au portefeuille.

Si le gestionnaire est un CAE, le système ne le remonte pas automatiquement dans le CRM.

F01.EU01.CU01.RM04 Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert "CAGE" in statements["F01.EU01.CU01.RM03"]
    assert "ne le remonte pas automatiquement" in statements["F01.EU01.CU01.RM03"]
    assert "Autre règle" not in statements["F01.EU01.CU01.RM03"]


def test_a_rule_announcing_a_list_keeps_its_bullets() -> None:
    text = """
F01.EU01.CU05.RM03 Le système teste si le gestionnaire était le binôme. Si oui :

- le binôme est supprimé
- la relation est maintenue dans son état actif

F01.EU01.CU05.RM04 Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert "le binôme est supprimé" in statements["F01.EU01.CU05.RM03"]
    assert "maintenue dans son état actif" in statements["F01.EU01.CU05.RM03"]


def test_a_requirement_only_ever_cited_keeps_an_empty_statement() -> None:
    """Measured: 1 of 468. The document names it and never states it, and saying so is the
    honest answer, rather than attributing a neighbour's sentence to it."""
    text = """
F04.EU03.CU01.EM01 Le système notifie le nouvel intervenant E06.N03.

F04.EU03.CU01.EM02 Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert statements["E06.N03"] == ""


def test_a_citation_between_parentheses_leaves_no_statement() -> None:
    """Measured on the reference document: E01.N0x, a notification number the specification
    never decided, came out with the statement ")." and looked documented."""
    text = """
F02.EU01.CU03.RM01 : Le système notifie le RRC de l'intégration (E01.N0x).

F02.EU01.CU03.RM02 : Autre règle.
"""
    statements = {r.ref: r.statement for r in extract_requirements(text)}

    assert statements["E01.N0X"] == ""
    assert statements["F02.EU01.CU03.RM01"].startswith("Le système notifie")
