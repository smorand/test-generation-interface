
# US-0009: Export QC — colonne Classification, règle Subject, verrouillage Test Name/Description

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 11
> Depends On: US-0001, US-0002
> Complexity: M
> min_tier: 2
> Files touched: 2

## Objective
Aligner `Subject` de l'export QC sur la même règle de nommage que les onglets du classeur
recette, ajouter la colonne "Classification", et verrouiller par un test de non-régression
explicite la composition déjà en place de `Test Name` et `Description`.

## Technical Context

### Stack
Python 3.13.

### Relevant File Structure
```
src/tgi/
  qc_export.py     # _HEADER (12), _TYPE_BY_PREFIX (26-32), build_qc_workbook, Test Name (84), Description (85-87), Subject (70-77, 82)
  workbook.py        # onglet_type_name (US-0002), classification.py (US-0001)
tests/
  test_qc_export.py
```

### Existing Patterns
`qc_export.py:70-77` calcule aujourd'hui `Subject` via sa propre composition
`{container}-{type_}_{use_case_title}_{scenario_id}` ; `qc_export.py:26-32` a son mapping
`_TYPE_BY_PREFIX`/`_requirement_type`. Ces deux éléments sont remplacés par les fonctions
partagées : `classification_of` (US-0001, `classification.py`) et `onglet_type_name` (US-0002,
`workbook.py`). `qc_export.py:84` compose déjà `Test Name` sous la forme exacte
`TRA_<id>_<nom>__<refs>` ; `qc_export.py:85-87` compose déjà `Description` sous la forme exacte
`<description>\nExigences validées : <refs>`. `qc_export.py:71-73` gère déjà le cas sans
référence en mettant `"INCONNU"`.

### Data Model (excerpt)
`test["id"]`, `test["name"]`, `test["description"]`, `test["requirement_refs"]`.

### Decisions That Govern This Story
- **DEC-021** (spec §17) : "La composition `Test Name`... est conservée telle quelle plutôt que
  modifiée pour correspondre littéralement à l'exemple email, parce que le code actuel
  satisfait déjà la règle écrite dans #11... l'écart avec l'exemple est documenté comme TBD-001
  plutôt que résolu par supposition. Implemented by: FR-NEW-068." Ne PAS réécrire `Test Name`
  pour coller à l'exemple email, c'est un TBD ouvert, pas une implémentation à deviner.
- **DEC-027** (spec §17) : classification et nommage d'onglet factorisés, `onglet_type_name`
  vient de `workbook.py` (US-0002), `classification_of` de `classification.py` (US-0001).

### Applicable NFRs
Aucune.

### Bounded Context
Export QC : `qc_export.py`. Entité : ligne QC (Subject, Test Name, Description, Step).

## Functional Requirements

### FR-NEW-068 [EARS-U]: Vérifier et figer le séparateur Test Name de l'export QC
> THE `qc_export.py` SHALL composer `Test Name` comme `TRA_<ID test>_<Nom du test>__<Exigences
> validées jointes par ", ">`, avec exactement les séparateurs `_`, `_`, `__` dans cet ordre, en
> confirmant la forme déjà en place (`qc_export.py:84`).

- **Inputs:** `test["id"]`, `test["name"]`, `test["requirement_refs"]`.
- **Outputs:** chaîne `Test Name` inchangée dans sa forme, verrouillée par un test de
  non-régression explicite.
- **Business Rules:** aucun changement de comportement ; cette exigence documente et fige ce
  que #11 demandait déjà, l'écart avec l'exemple email étant noté TBD-001 (section 15 de la
  spec) plutôt que mis en œuvre sans confirmation de Véronique.
- **Priority:** Should-have (déjà conforme ; exigence de verrouillage)

### FR-NEW-069 [EARS-U]: Vérifier et figer la composition Description de l'export QC
> THE `qc_export.py` SHALL composer `Description` comme `<Description du test>` suivi, si des
> exigences sont liées, d'un saut de ligne et de `Exigences validées : <refs jointes par ", ">`,
> confirmant la forme déjà en place (`qc_export.py:85-87`).

- **Inputs:** `test["description"]`, `test["requirement_refs"]`.
- **Outputs:** inchangé, verrouillé par un test de non-régression.
- **Priority:** Should-have (déjà conforme ; exigence de verrouillage)

### FR-NEW-070 [EARS-E]: Subject de l'export QC aligné sur l'intitulé d'onglet du type d'exigence
> WHEN `qc_export.py` compose la colonne `Subject` d'une ligne THE système SHALL utiliser la
> même règle de nommage que celle utilisée pour l'intitulé de l'onglet du type d'exigence
> majoritaire du test dans le classeur recette, au lieu de la composition actuelle
> `{container}-{type_}_{use_case_title}_{scenario_id}`.

- **Inputs:** `test["requirement_refs"]`, la fonction `onglet_type_name` (US-0002).
- **Outputs:** `Subject` = `IHM_E04` pour un test dont la première exigence est de type IHM
  rattachée à l'écran E04 ; `Subject` = `EU01.CU01-RM` pour un test dont la première exigence est
  de type RM rattachée au cas d'utilisation `EU01.CU01` ; `Subject` = `F01.EU02.CU03-EMOE` pour
  une exigence EMOE.
- **Business Rules:** le type et la référence utilisés sont ceux de la **première** référence de
  `test["requirement_refs"]`, comme aujourd'hui (`qc_export.py:70-77`) ; aucun test n'a ses
  exigences réparties sur plusieurs Subject.
- **Exact names:** importer `onglet_type_name(ref: str, grammar: Grammar) -> str` depuis
  `workbook.py`, pour que les deux modules ne divergent jamais.
- **Priority:** Must-have

### FR-NEW-076 [EARS-U]: Nouvelle colonne "Classification" dans l'export QC
> THE export QC SHALL porter une colonne "Classification" après "Description" et avant "Step
> Name".

- **Inputs:** sortie de `classification_of` (US-0001).
- **Outputs:** `_HEADER` (`qc_export.py:12`) étendu : `["Subject", "Test Name", "Description",
  "Classification", "Step Name", "Step Description", "Expected Results"]`.
- **Business Rules:** répétée sur chaque ligne de step du même test, comme `Subject`/`Test Name`
  aujourd'hui.
- **Exact names:** en-tête exact "Classification".
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| test avec ref RM | `{"id": "TEST-2101", "name": "Visualiser les notes", "requirement_refs": ["EU01.CU01.RM02"]}` | fixture test | ready |
| test avec description | `{"description": "Vérifier que l'utilisateur peut accéder aux interactions via la fiche d'un contact.", "requirement_refs": ["EU01.CU01.RM05"]}` | fixture test | ready |
| test ref IHM en premier | première ref `E04.M01` | fixture test | ready |
| test sans ref | `requirement_refs: []` | fixture test | ready |

### E2E-NEW-007: Test Name de l'export QC reste `TRA_<id>_<nom>__<refs>`
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-068
- **Driver:** direct function call (`tgi.qc_export.build_qc_workbook`)
- **Steps:**
  - Given un test `{"id": "TEST-2101", "name": "Visualiser les notes", "requirement_refs":
    ["EU01.CU01.RM02"]}`
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Test Name" de la ligne produite vaut exactement
    `"TRA_TEST-2101_Visualiser les notes__EU01.CU01.RM02"`
- **Cleanup:** aucun.
- **Priority:** Medium

### E2E-NEW-008: Description de l'export QC reste `<description>\nExigences validées : <refs>`
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-069
- **Driver:** direct function call
- **Steps:**
  - Given un test `{"description": "Vérifier que l'utilisateur peut accéder aux interactions via
    la fiche d'un contact.", "requirement_refs": ["EU01.CU01.RM05"]}`
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Description" vaut exactement `"Vérifier que l'utilisateur peut accéder aux
    interactions via la fiche d'un contact.\nExigences validées : EU01.CU01.RM05"`
- **Cleanup:** aucun.
- **Priority:** Medium

### E2E-NEW-009: Subject de l'export QC suit la règle de nommage d'onglet du type majoritaire
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-070, FR-NEW-076
- **Driver:** direct function call
- **Steps:**
  - Given un test dont la première référence est `E04.M01` (IHM)
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Subject" vaut exactement `"IHM_E04"`
  - And pour un test dont la première référence est `EU01.CU01.RM02`, "Subject" vaut
    `"EU01.CU01-RM"`
  - And la colonne "Classification" est présente dans l'en-tête, après "Description"
- **Cleanup:** aucun.
- **Priority:** High

### E2E-NEW-015: Subject reste "INCONNU" pour un test sans référence
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-070
- **Driver:** direct function call
- **Steps:**
  - Given un test sans `requirement_refs`
  - When `build_qc_workbook(state)` est appelé
  - Then "Subject" vaut `"INCONNU"` et un avertissement est ajouté à la liste de warnings
    retournée (comportement déjà existant, `qc_export.py:71-73`, vérifié non régressé)
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/workbook.py` (consommateur de `classification_of`, fournisseur de `onglet_type_name`,
déjà fait en US-0001/US-0002 — cette story importe, ne redéfinit pas).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas réécrire `Test Name` pour coller à l'exemple email de la demande #11 (DEC-021, TBD-001).
Ne pas dupliquer `_TYPE_BY_PREFIX` : le retirer et utiliser `classification_of`/
`onglet_type_name`.

### Scope Boundary
Cette story ne modifie pas le format des colonnes "Step Name", "Step Description", "Expected
Results".

## Non Regression

### Existing Tests That Must Pass
`tests/test_qc_export.py` existants, adaptés pour la nouvelle colonne "Classification" et la
nouvelle règle Subject.

### Behaviors That Must Not Change
Le cas sans référence reste `"INCONNU"` avec son avertissement (E2E-NEW-015).

### API Contracts to Preserve
La signature `build_qc_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
