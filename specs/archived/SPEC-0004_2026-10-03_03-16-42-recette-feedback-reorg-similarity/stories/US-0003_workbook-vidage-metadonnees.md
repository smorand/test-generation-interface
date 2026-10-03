
# US-0003: Vidage des métadonnées sur les lignes d'étape 2+ et colonne Classification

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 7
> Depends On: US-0002
> Complexity: M
> min_tier: 2
> Files touched: 2

## Objective
Arrêter de répéter les métadonnées de test (Cas d'utilisation, Scénario, Nom du test,
Description, Exigences validées, Classification, Statut, etc.) sur chaque ligne d'étape : seule
la première ligne de chaque test les porte, les lignes suivantes ne portant que Étape/Action/
Résultat attendu (et "ID test", qui reste rempli sur chaque ligne). Ajoute aussi la nouvelle
colonne "Classification" (MOA/MOE) au classeur recette.

## Technical Context

### Stack
Python 3.13, `openpyxl`.

### Relevant File Structure
```
src/tgi/
  workbook.py          # _TEST_COLUMNS (37-50), _test_rows (132-190), _finish_sheet (111-129)
  classification.py     # classification_of (US-0001)
tests/
  test_workbook.py
```

### Existing Patterns
`workbook.py:111-129`, `_finish_sheet`, applique un banding par bloc avec `band_on=
_TEST_ID_COLUMN` : ce banding continue de fonctionner sans modification car il se fie
uniquement à "ID test", qui reste toujours rempli. L'autofiltre (même fonction) continue de
fonctionner sur des colonnes partiellement vides, comportement normal d'Excel.

`_TEST_ID_COLUMN = 4` (index inchangé) : colonne explicitement exclue du vidage.

### Data Model (excerpt)
Un test a `steps: list[dict]` ; la première ligne produite pour ce test porte toutes les
colonnes de métadonnées, les lignes suivantes du même test ne portent que "ID test",
"Étape", "Action", "Résultat attendu".

### Decisions That Govern This Story
Aucune décision additionnelle au-delà des FR eux-mêmes : c'est la règle structurante communiquée
explicitement par l'utilisateur (section Rationale de FR-NEW-080 dans le spec), appliquée à
toutes les feuilles de cas de test produites par US-0002.

### Applicable NFRs
Aucune.

### Bounded Context
Classeur recette : `workbook.py`.

## Functional Requirements

### FR-NEW-075 [EARS-U]: Nouvelle colonne "Classification" dans le classeur recette
> THE classeur recette SHALL porter une colonne "Classification" dans chaque feuille de type,
> immédiatement après "Exigences validées" et avant "Statut".

- **Inputs:** sortie de `classification_of` (US-0001).
- **Outputs:** `_TEST_COLUMNS` (`workbook.py:37-50`) étendu : `..., ("Exigences validées", 30),
  ("Classification", 12), ("Statut", 11)`. Valeur affichée uniquement sur la première ligne
  d'étape du test, vide sur les lignes suivantes.
- **Exact names:** libellé de colonne exact "Classification".
- **Priority:** Must-have

### FR-NEW-080 [EARS-U]: Vidage des colonnes de métadonnées de test sur les lignes d'étape 2+
> THE classeur recette SHALL renseigner les colonnes "Cas d'utilisation", "Scénario", "Intention
> du scénario", "Nature", "Nom du test", "Description", "Exigences validées", "Classification"
> et "Statut" uniquement sur la première ligne d'étape de chaque test, en laissant ces colonnes
> vides sur les lignes d'étape suivantes du même test, et SHALL continuer à renseigner "ID test"
> sur **chaque** ligne, sans exception.

- **Inputs:** `_test_rows` actuel (`workbook.py:132-190`).
- **Outputs:** pour un test à 3 étapes, seule la ligne de l'étape 1 porte les 9 colonnes de
  métadonnées renseignées ; les lignes des étapes 2 et 3 les laissent vides, sauf "ID test" qui
  reste rempli sur les 3 lignes.
- **Business Rules:** le banding par bloc (`_finish_sheet`, `band_on=_TEST_ID_COLUMN`) continue
  de fonctionner sans modification. L'autofiltre continue de fonctionner sur des colonnes
  partiellement vides.
- **Exact names:** colonnes visées exactement : "Cas d'utilisation", "Scénario", "Intention du
  scénario", "Nature", "Nom du test", "Description", "Exigences validées", "Classification",
  "Statut". Colonne exclue du vidage : "ID test" (index 4, inchangé, `_TEST_ID_COLUMN = 4`).
- **Priority:** Must-have

### FR-NEW-081 [EARS-UB]: Le classeur recette ne doit jamais répéter une métadonnée de test au-delà de sa première ligne
> THE classeur recette SHALL NOT répéter une valeur de colonne de métadonnée de test (listées en
> FR-NEW-080) sur une ligne d'étape autre que la première ligne de ce test.

- **Priority:** Must-have
- **Rationale:** formulation négative explicite de FR-NEW-080, pour qu'un test de
  non-régression puisse l'affirmer directement.

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| test 3 étapes | `TEST-0100`, couvrant `EU01.CU01.RM01` | fixture test | ready |
| test 5 étapes | `TEST-0400`, couvrant `EU01.CU01.RM03` | fixture test | ready |
| test 2 étapes | pour E2E-MOD-001 | fixture test | ready |

### E2E-NEW-002: Les colonnes de métadonnées sont vides sur les lignes d'étape 2+, "ID test" reste rempli
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-080, FR-NEW-081
- **Driver:** direct function call
- **Preconditions:** un test à 3 étapes, `TEST-0100`, couvrant `EU01.CU01.RM01`.
- **Steps:**
  - Given un scénario avec un test `TEST-0100` à 3 étapes
  - When `build_workbook(state)` produit la feuille `EU01.CU01-RM`
  - Then la ligne 2 (étape 1) porte "Cas d'utilisation", "Nom du test", "Exigences validées",
    "Classification", "Statut" renseignés, et "ID test" = `TEST-0100`
  - And la ligne 3 (étape 2) a ces mêmes colonnes vides, sauf "ID test" = `TEST-0100`
  - And la ligne 4 (étape 3) a ces mêmes colonnes vides, sauf "ID test" = `TEST-0100`
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-NEW-011: Une métadonnée de test ne réapparaît jamais sur une ligne d'étape non première
- **Category:** Error (negative assertion)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-081
- **Driver:** direct function call
- **Preconditions:** un test à 5 étapes.
- **Steps:**
  - Given un test `TEST-0400` à 5 étapes couvrant `EU01.CU01.RM03`
  - When le classeur est construit
  - Then les colonnes "Cas d'utilisation", "Scénario", "Intention du scénario", "Nature", "Nom
    du test", "Description", "Exigences validées", "Classification", "Statut" sont vides sur les
    lignes 3, 4, 5 et 6 (étapes 2 à 5)
  - And aucune de ces 4 lignes ne contient la valeur du test répétée
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-MOD-001: Une seule ligne par test porte ses métadonnées (was `test_one_row_per_step_repeating_the_test_columns`)
- **Original test validated:** que chaque ligne d'étape répète toutes les colonnes de
  métadonnées du test (`tests/test_workbook.py`, nom explicite).
- **Now validates:** que seule la première ligne d'étape porte les métadonnées, les suivantes
  les laissant vides sauf "ID test" (FR-NEW-080, FR-NEW-081).
- **Steps:** Given un test à 2 étapes / When le classeur est construit / Then ligne 1 porte
  toutes les colonnes, ligne 2 ne porte que "ID test", "Étape", "Action", "Résultat attendu".

## Constraints

### Files Not to Touch
`src/tgi/qc_export.py` (la répétition sur chaque ligne de step reste la règle pour l'export QC,
c'est une règle d'import ALM différente, voir US-0009).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas toucher au banding `_finish_sheet` : il continue de fonctionner tel quel sur "ID test".

### Scope Boundary
Cette story ne modifie pas l'organisation des feuilles (déjà faite en US-0002), seulement le
contenu des lignes à l'intérieur de chaque feuille.

## Non Regression

### Existing Tests That Must Pass
Les 5 autres tests existants de `tests/test_workbook.py` (hors
`test_one_row_per_step_repeating_the_test_columns`, remplacé par E2E-MOD-001), adaptés si
nécessaire à la nouvelle structure d'onglets déjà posée par US-0002.

### Behaviors That Must Not Change
Le banding par bloc et l'autofiltre continuent de fonctionner identiquement.

### API Contracts to Preserve
La signature `build_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
