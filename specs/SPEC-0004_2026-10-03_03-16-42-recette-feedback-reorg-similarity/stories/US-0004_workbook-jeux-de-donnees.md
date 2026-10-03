
# US-0004: Onglet "Jeux de données" séparé

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 8
> Depends On: US-0002
> Complexity: S
> min_tier: 2
> Files touched: 2

## Objective
Sortir les lignes de `data_rows` des feuilles de test et les regrouper dans un onglet dédié
"Jeux de données", avec une colonne "ID test" permettant de retrouver le test dans sa feuille de
type.

## Technical Context

### Stack
Python 3.13, `openpyxl`.

### Relevant File Structure
```
src/tgi/
  workbook.py    # _test_rows (132-190) insère aujourd'hui les data_rows dans la même feuille (175-189)
  agents/scenario_generator.py   # _clean_data_rows (69-76), référence uniquement
tests/
  test_workbook.py
```

### Existing Patterns
`workbook.py:175-189` insère aujourd'hui les lignes `data_rows` directement dans la feuille de
test. Cette insertion doit être retirée de `_test_rows` et déplacée vers la construction du
nouvel onglet. `test["data_rows"]` est une liste de dictionnaires à clés arbitraires
(`scenario_generator.py:69-76`, `_clean_data_rows`).

### Data Model (excerpt)
`test["data_rows"]: list[dict[str, Any]]`, clés arbitraires et variables d'un test à l'autre.

### Decisions That Govern This Story
- **DEC-026** (spec §17) : "L'onglet 'Jeux de données' utilise une colonne 'Détail' (paires
  clé:valeur jointes) plutôt qu'une colonne par clé rencontrée, parce que les clés de
  `data_rows` varient librement d'un test à l'autre... Implemented by: FR-NEW-078." Ne PAS créer
  une colonne par clé : une seule colonne "Détail" avec les paires clé:valeur jointes.

### Applicable NFRs
Aucune.

### Bounded Context
Classeur recette : `workbook.py`. Entité : jeu de données.

## Functional Requirements

### FR-NEW-078 [EARS-U]: Onglet "Jeux de données" séparé, référençant l'ID du test
> THE classeur recette SHALL porter un onglet "Jeux de données" distinct, contenant une ligne
> par cas de chaque `data_rows` de chaque test, avec une colonne "ID test" permettant de
> retrouver le test dans sa feuille de type.

- **Inputs:** `test["data_rows"]` pour chaque test de chaque scénario.
- **Outputs:** feuille "Jeux de données" avec colonnes : "ID test", "Nom du test", "Détail"
  (paires clé:valeur jointes, DEC-026), "Onglet source" (le nom de la feuille de type où ce test
  apparaît, issu de `onglet_type_name`, US-0002).
- **Business Rules:** cet onglet remplace les lignes `data_rows` actuellement insérées dans la
  même feuille que les étapes (`workbook.py:175-189`), qui disparaissent de `_test_rows`.
- **Exact names:** nom d'onglet exact "Jeux de données", colonnes `_DATA_ROW_COLUMNS` dans
  `workbook.py`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| test avec 2 data_rows | `TEST-0200` couvrant `IHM E04` | fixture test | ready |

### E2E-NEW-004: L'onglet "Jeux de données" référence l'ID du test et liste un onglet source
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-078
- **Driver:** direct function call
- **Steps:**
  - Given un test `TEST-0200` couvrant `IHM E04` avec 2 `data_rows`
  - When `build_workbook(state)` est appelé
  - Then l'onglet "Jeux de données" contient 2 lignes, chacune avec "ID test" = `TEST-0200` et
    "Onglet source" = `IHM_E04`
  - And l'onglet `IHM_E04` ne contient **aucune** ligne de jeu de données (elles sont retirées
    de `_test_rows`)
- **Cleanup:** aucun.
- **Priority:** High

## Constraints

### Files Not to Touch
`src/tgi/agents/scenario_generator.py` (la structure de `data_rows` elle-même n'est pas
modifiée, seule sa restitution dans le classeur change).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas créer une colonne par clé rencontrée dans `data_rows` (DEC-026 explicitement contre).

### Scope Boundary
Cette story ne modifie pas la structure des feuilles de type elle-même au-delà du retrait des
lignes `data_rows`.

## Non Regression

### Existing Tests That Must Pass
Les tests existants de `tests/test_workbook.py` qui vérifiaient l'insertion des `data_rows`
dans la feuille de test doivent être adaptés pour vérifier leur absence dans cette feuille et
leur présence dans "Jeux de données".

### Behaviors That Must Not Change
Rien d'autre dans `_test_rows` ne change au-delà du retrait des lignes `data_rows`.

### API Contracts to Preserve
La signature `build_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
