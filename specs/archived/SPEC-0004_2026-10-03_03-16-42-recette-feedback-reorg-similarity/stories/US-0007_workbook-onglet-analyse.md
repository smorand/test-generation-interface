
# US-0007: Onglet "Analyse" matérialisant la lecture par section

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 9
> Depends On: US-0002, US-0005
> Complexity: M
> min_tier: 2
> Files touched: 2

## Objective
Ajouter un onglet "Analyse" au classeur recette, qui matérialise, pour chaque section du
document identifiée par la numérotation inférée, ce qui a été lu, rattaché à un scénario, ou
écarté — visible directement dans le seul livrable reçu par Véronique, sans accès aux logs
serveur.

## Technical Context

### Stack
Python 3.13, `openpyxl`.

### Relevant File Structure
```
src/tgi/
  workbook.py     # nouvel onglet "Analyse", colonnes _ANALYSIS_COLUMNS
  grammar.py       # Grammar (conteneurs, numérotation inférée)
tests/
  test_workbook.py
```

### Existing Patterns
Le champ `source_section`, ajouté à chaque scénario par US-0005, est la donnée clé qui permet de
rattacher un scénario à sa section. `state["containers"]` donne déjà les titres des sections.

### Data Model (excerpt)
`state["requirements"]`, `state["scenarios"]` (porteurs de `source_section`),
`state["discards"]`, `state["containers"]`.

### Decisions That Govern This Story
Aucune décision additionnelle au-delà de la définition de FR-NEW-073 elle-même.

### Applicable NFRs
Aucune.

### Bounded Context
Classeur recette : `workbook.py`.

## Functional Requirements

### FR-NEW-073 [EARS-U]: Onglet "Analyse" matérialisant la lecture par section
> THE système SHALL ajouter un onglet "Analyse" au classeur recette, listant, pour chaque
> section du document identifiée par la numérotation inférée (`grammar.Grammar`), ce qui a été
> lu, rattaché à un scénario, ou écarté.

- **Inputs:** `state["requirements"]`, `state["scenarios"]`, `state["discards"]`,
  `state["containers"]`, le champ `source_section` (US-0005).
- **Outputs:** une feuille "Analyse" avec les colonnes : "Section" (référence de conteneur),
  "Titre" (`state["containers"]`), "Exigences trouvées" (compte), "Exigences rattachées à un
  scénario" (compte), "Scénarios issus de cette section" (liste), "Éléments écartés" (liste des
  `discards` dont une ref appartient à cette section).
- **Business Rules:** une section sans aucune exigence ni aucun scénario (une section purement
  narrative du document) apparaît quand même, avec des compteurs à zéro, pour que "rien n'a été
  lu ici" soit une ligne visible plutôt qu'une absence silencieuse.
- **Exact names:** nom d'onglet exact "Analyse", colonnes `_ANALYSIS_COLUMNS` dans
  `workbook.py`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| section sans exigence | `F02.EU01.CU02` sans aucune exigence ni scénario rattaché | fixture test | ready |

### E2E-NEW-010: L'onglet "Analyse" liste chaque section avec ses compteurs, y compris une section sans exigence
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-073
- **Driver:** direct function call
- **Steps:**
  - Given un `state` avec une section `F02.EU01.CU02` sans aucune exigence ni scénario rattaché
  - When le classeur est construit
  - Then l'onglet "Analyse" contient une ligne pour `F02.EU01.CU02` avec "Exigences trouvées" =
    0 et "Scénarios issus de cette section" vide
- **Cleanup:** aucun.
- **Priority:** High

## Constraints

### Files Not to Touch
`src/tgi/agents/distiller.py` (déjà fait en US-0005), `src/tgi/coverage_report.py`.

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas omettre une section sans exigence ni scénario : elle doit apparaître avec des compteurs
à zéro plutôt que d'être absente.

### Scope Boundary
Cette story ajoute uniquement l'onglet "Analyse" ; elle ne modifie pas les autres onglets.

## Non Regression

### Existing Tests That Must Pass
Tous les tests de `tests/test_workbook.py` déjà adaptés par US-0002/US-0003/US-0004.

### Behaviors That Must Not Change
Rien d'autre dans le classeur ne change.

### API Contracts to Preserve
La signature `build_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
