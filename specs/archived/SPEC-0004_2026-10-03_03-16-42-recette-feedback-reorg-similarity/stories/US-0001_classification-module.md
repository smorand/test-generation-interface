
# US-0001: Module partagé de classification MOA/MOE

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 1
> Depends On: none
> Complexity: S
> min_tier: 2
> Files touched: 2

## Objective
Introduire un module partagé qui calcule, de façon purement déterministe (aucun appel LLM), la
classification MOA/MOE/MOA-MOE/INCONNU d'un test à partir de ses références d'exigences. Ce
module est le socle que `workbook.py` (US-0002, US-0003) et `qc_export.py` (US-0009)
consommeront pour afficher la colonne "Classification".

## Technical Context

### Stack
Python 3.13, src/ package layout (`src/tgi`). Tests avec `pytest`.

### Relevant File Structure
```
src/tgi/
  grammar.py          # Grammar.kind_of(ref) -> type d'exigence (existe déjà)
  qc_export.py         # _TYPE_BY_PREFIX, _requirement_type (duplication à ne PAS copier ici)
  classification.py    # NOUVEAU
tests/
  test_classification.py  # NOUVEAU
```

### Existing Patterns
`grammar.py:136-137` expose déjà `Grammar.kind_of(ref)`, qui renvoie le type d'une référence
(`RM`, `EM`, ou une famille IHM selon le préfixe). `qc_export.py:26-32` a aujourd'hui son propre
mapping `_TYPE_BY_PREFIX` / `_requirement_type`, qui ne doit **pas** être dupliqué dans ce
nouveau module : ce module l'appelle, il ne le recopie pas. La signature doit utiliser
`grammar.kind_of(ref)` directement.

### Data Model (excerpt)
Un test porte `test["requirement_refs"]: list[str]`, une liste de références d'exigences
(peut être vide).

### Decisions That Govern This Story
- **DEC-027** (spec §17) : "La classification MOA/MOE et le nommage d'onglet par type sont
  factorisés dans un nouveau module `src/tgi/classification.py` partagé entre `workbook.py` et
  `qc_export.py`, plutôt que dupliqués... Implemented by: FR-NEW-070, FR-NEW-074, FR-NEW-077."
  Cette story implémente la partie `classification_of` de ce module ; `onglet_type_name` est
  implémenté dans US-0002 (il vit dans `workbook.py` d'après FR-NEW-070/077, pas dans
  `classification.py`).

### Applicable NFRs
Aucun appel LLM, calcul en mémoire, coût négligeable (section 7.1 de la spec).

### Bounded Context
Couverture (inchangé) : `coverage_report.py`, `grammar.py` — scope : statut de couverture, type
d'exigence (RM/IHM/EMOE). Ce module lit `grammar.py` mais ne touche jamais `coverage_report.py`.

## Functional Requirements

### FR-NEW-074 [EARS-E]: Classification MOA/MOE dérivée du type d'exigence
> WHEN un test est écrit dans le classeur recette ou l'export QC THE système SHALL calculer sa
> classification comme `MOA` si toutes ses exigences liées sont de type IHM, `MOE` si toutes ses
> exigences liées sont de type RM ou EMOE, ou `MOA/MOE` si ses exigences liées couvrent les deux
> familles.

- **Inputs:** `test["requirement_refs"]`, `grammar.kind_of(ref)` pour chaque référence.
- **Outputs:** une valeur `"MOA"`, `"MOE"`, ou `"MOA/MOE"` par test. Un test sans aucune référence
  produit `"INCONNU"`.
- **Business Rules:** calcul purement déterministe, aucun appel LLM. IHM = type `M`, `N` ou `T`
  (famille écran/batch, déjà mappée vers `"IHM"` dans `qc_export.py:26-32`) ; MOE = type `RM` ou
  `EM`.
- **Exact names:** fonction `classification_of(refs: list[str], grammar: Grammar) -> str` dans
  `src/tgi/classification.py`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec. Exécuter via `make test` (ou
> la cible Makefile du projet), jamais un run ad hoc.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| refs IHM seules | `["E04.M01"]` | fixture test | ready |
| refs RM seules | `["EU01.CU01.RM02"]` | fixture test | ready |
| refs mixtes | `["EU01.CU01.RM01", "E04.M01"]` | fixture test | ready |
| refs vides | `[]` | fixture test | ready |

### E2E-NEW-005 (partiel): La classification MOA/MOE est correcte sur un test mixte
- **Category:** Happy
- **Scenario:** SC-001
- **Requirements:** FR-NEW-074
- **Preconditions:** une instance `Grammar` connaissant `EU01.CU01.RM01` (RM) et `E04.M01` (IHM).
- **Steps:**
  - Given `refs = ["EU01.CU01.RM01", "E04.M01"]`
  - When `classification_of(refs, grammar)` est appelé
  - Then le résultat vaut exactement `"MOA/MOE"`
  - And `classification_of(["EU01.CU01.RM02"], grammar)` vaut `"MOE"`
  - And `classification_of(["E04.M02"], grammar)` vaut `"MOA"`
- **Cleanup:** aucun.
- **Priority:** High

### E2E-NEW-016: Classification "INCONNU" pour un test sans référence
- **Category:** Edge
- **Scenario:** SC-002
- **Requirements:** FR-NEW-074
- **Preconditions:** aucune.
- **Steps:**
  - Given `refs = []`
  - When `classification_of([], grammar)` est appelé
  - Then le résultat vaut exactement `"INCONNU"`
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/qc_export.py`, `src/tgi/workbook.py`, `src/tgi/coverage_report.py` — cette story crée
uniquement le module et son test, elle ne branche rien encore (le branchement est fait par
US-0002/US-0003/US-0009).

### Dependencies Not to Add
Aucune nouvelle dépendance externe.

### Patterns to Avoid
Ne pas dupliquer `_TYPE_BY_PREFIX` de `qc_export.py` dans ce module : appeler `grammar.kind_of`.

### Scope Boundary
Pas de colonne ajoutée nulle part dans cette story — seulement la fonction pure.

## Non Regression

### Existing Tests That Must Pass
Toute la suite existante (`make test`), inchangée par cette story.

### Behaviors That Must Not Change
`qc_export.py` continue de produire son comportement actuel tel quel (`_TYPE_BY_PREFIX` reste en
place jusqu'à US-0009).

### API Contracts to Preserve
Aucune API publique existante n'est modifiée.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
