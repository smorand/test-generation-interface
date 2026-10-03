
# US-0008: Légende des onglets et renvoi croisé Synthèse → Traçabilité

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 10
> Depends On: US-0002
> Complexity: S
> min_tier: 2
> Files touched: 2

## Objective
Ajouter à l'onglet "Synthèse" une légende expliquant chaque onglet réellement présent dans le
classeur, et un lien hypertexte interne depuis le bloc "Par type d'exigence" vers la première
ligne de l'onglet "Traçabilité".

## Technical Context

### Stack
Python 3.13, `openpyxl` (`openpyxl.worksheet.hyperlink.Hyperlink` ou `cell.hyperlink`).

### Relevant File Structure
```
src/tgi/
  workbook.py    # bloc "Par type d'exigence" (223-225), sheet_title (79-93), _SUMMARY_COLUMNS
tests/
  test_workbook.py
```

### Existing Patterns
`workbook.py:79-93`, `sheet_title()`, peut suffixer `(2)` en cas de collision : le lien
hypertexte doit toujours cibler le nom de feuille **tel qu'il existe réellement** dans ce
classeur (jamais un nom en dur "Traçabilité").

### Data Model (excerpt)
La liste des onglets effectivement créés par `build_workbook` pour cette version (dépend de
US-0002/003/004/007, exécutées avant cette story dans l'ordre d'implémentation).

### Decisions That Govern This Story
Aucune décision additionnelle au-delà de la définition des FR eux-mêmes.

### Applicable NFRs
Aucune.

### Bounded Context
Classeur recette : `workbook.py`.

## Functional Requirements

### FR-NEW-071 [EARS-U]: Légende des onglets dans la Synthèse
> THE onglet "Synthèse" SHALL contenir une section "Légende des onglets" listant, pour chaque
> onglet du classeur, son nom exact et une phrase expliquant son contenu.

- **Inputs:** la liste réelle des onglets créés par `build_workbook` pour cette version.
- **Outputs:** lignes ajoutées après le bloc "Par type d'exigence" existant
  (`workbook.py:223-225`) : une ligne par onglet effectivement créé, avec son nom et sa
  description (ex. "Traçabilité — une ligne par exigence du document, avec son statut et les
  tests qui la couvrent").
- **Business Rules:** la légende est générée dynamiquement (elle ne liste que les onglets
  réellement présents dans cette version, pas un texte statique qui listerait un onglet absent
  faute de données).
- **Exact names:** libellé de section exact "Légende des onglets" dans la colonne "Indicateur"
  de `_SUMMARY_COLUMNS`.
- **Priority:** Must-have

### FR-NEW-072 [EARS-E]: Renvoi croisé Synthèse → Traçabilité
> WHEN l'onglet "Synthèse" affiche le bloc "Par type d'exigence" THE système SHALL faire
> figurer, sur chaque ligne de ce bloc, un lien hypertexte interne pointant vers la première
> ligne de l'onglet "Traçabilité" filtrée sur ce type (ou, si openpyxl ne permet pas un filtre
> préconfiguré, un lien vers l'onglet lui-même accompagné du nom du type à chercher).

- **Inputs:** le nom de l'onglet "Traçabilité" tel que produit par `sheet_title`.
- **Outputs:** une cellule avec `Hyperlink` openpyxl (`cell.hyperlink =
  f"#'{trace_sheet_name}'!A1"`) sur chaque ligne "Par type d'exigence" de la Synthèse.
- **Business Rules:** le lien cible toujours l'onglet Traçabilité tel qu'il existe dans ce
  classeur précis (jamais un nom en dur "Traçabilité").
- **Exact names:** `openpyxl.worksheet.hyperlink.Hyperlink`, ou l'attribut `cell.hyperlink`
  (string interne commençant par `#`).
- **Priority:** Should-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| state produisant 4 feuilles | "Synthèse", "Traçabilité", "IHM_E04", "Analyse" | fixture test | ready |

### E2E-NEW-006: Légende des onglets et renvoi croisé vers la Traçabilité
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-071, FR-NEW-072
- **Driver:** direct function call, puis ouverture du fichier via `openpyxl.load_workbook`
- **Steps:**
  - Given un `state` produisant les feuilles "Synthèse", "Traçabilité", "IHM_E04", "Analyse"
  - When le classeur est construit puis relu avec `openpyxl.load_workbook`
  - Then l'onglet "Synthèse" contient une ligne "Légende des onglets" suivie d'une ligne par
    feuille réellement présente (4 lignes : Traçabilité, IHM_E04, Analyse, et elle-même ou non
    selon implémentation)
  - And la ligne "Par type d'exigence" porte une cellule avec `cell.hyperlink` non nul pointant
    vers `#'Traçabilité'!A1`
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/qc_export.py`.

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne jamais utiliser un nom de feuille en dur : toujours passer par `sheet_title()` / le nom réel
produit lors de la construction.

### Scope Boundary
Cette story ne modifie que l'onglet "Synthèse" existant.

## Non Regression

### Existing Tests That Must Pass
Les tests existants sur l'onglet "Synthèse" (bloc "Par type d'exigence" déjà présent).

### Behaviors That Must Not Change
Le contenu existant de la Synthèse (hors ajout de la légende et des liens) reste identique.

### API Contracts to Preserve
La signature `build_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
