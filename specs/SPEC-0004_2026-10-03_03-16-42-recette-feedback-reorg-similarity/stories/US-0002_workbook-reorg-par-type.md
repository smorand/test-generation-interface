
# US-0002: Classeur recette — réorganisation par type d'exigence

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 4
> Depends On: US-0001
> Complexity: L
> min_tier: 2
> Files touched: 2

## Objective
Remplacer l'organisation actuelle du classeur recette (une feuille par fonctionnalité, toutes
natures d'exigence mélangées) par une organisation en une feuille par couple (type d'exigence,
référence de rattachement) : `IHM_<écran>`, `<cas d'utilisation>-RM`,
`<cas d'utilisation>-EMOE`. C'est le changement structurant de la vague 5 (demande explicite,
sans débat, de l'utilisatrice unique du produit).

## Technical Context

### Stack
Python 3.13, `openpyxl` pour l'écriture xlsx.

### Relevant File Structure
```
src/tgi/
  workbook.py        # build_workbook, sheet_title (79-93), _TEST_COLUMNS (37-50), _test_rows (132-190)
  classification.py   # classification_of (US-0001)
  grammar.py          # Grammar.kind_of, Grammar.container_of, Requirement.parent (87-98)
  deliverable.py      # build_tree (148-184) — reste INCHANGÉ, sert la vue web
tests/
  test_workbook.py
```

### Existing Patterns
`workbook.py:79-93`, `sheet_title()`, gère déjà la collision de noms de feuille (suffixe `(2)`
automatique) : la nouvelle fonction de nommage d'onglet doit lui être passée comme aujourd'hui
`chapter.key` l'est (`workbook.py:252`), jamais contourner cette fonction.

`grammar.py:87-98`, dataclass `Requirement`, porte déjà `kind` et `parent` : `parent` est le cas
d'utilisation pour RM/EMOE. `grammar.py:122-129`, `container_of(ref)`, donne le conteneur d'une
référence IHM à l'axe `E` (`container_depth`).

### Data Model (excerpt)
`state["scenarios"]` : scénarios avec `tests: list[dict]`, chaque test porte
`requirement_refs: list[str]`. `state["requirements"]` : liste de `Requirement` (ou équivalent
sérialisé) avec `kind` et `parent`.

### Decisions That Govern This Story
- **DEC-025** (spec §17) : "L'organisation du classeur recette par type d'exigence remplace
  entièrement l'organisation par fonctionnalité, sans option de bascule entre les deux...
  Implemented by: FR-NEW-077, FR-MOD-001." Pas de double organisation, pas de flag.
- **DEC-027** (spec §17) : `onglet_type_name` est exposée par `workbook.py`, importée par
  `qc_export.py` (US-0009) — ne pas la mettre dans `classification.py`.

### Applicable NFRs
Aucune (section 7 ne mentionne rien de spécifique pour cette story au-delà de la perf O(n²)
déjà traitée en US-0010).

### Bounded Context
Classeur recette : `workbook.py`, `deliverable.py` (lecture seule, **inchangé**). Entités :
onglet, feuille de type, ligne de test, jeu de données.

## Functional Requirements

### FR-NEW-077 [EARS-U]: Un onglet du classeur recette par type d'exigence, plus par référence de rattachement
> THE classeur recette SHALL remplacer l'organisation par fonctionnalité (`build_tree`,
> `deliverable.py:148-184`) par une organisation en une feuille par couple (type d'exigence,
> référence de rattachement), nommée :
> - `IHM_<référence écran>` pour une exigence de type IHM (ex. `IHM_E04`)
> - `<référence de cas d'utilisation>-RM` pour une exigence de type RM (ex. `EU01.CU01-RM`)
> - `<référence de cas d'utilisation>-EMOE` pour une exigence de type EMOE (ex.
>   `F01.EU02.CU03-EMOE`)

- **Inputs:** `state["scenarios"]`, `state["requirements"]`.
- **Outputs:** une feuille par couple (type, référence de rattachement) réellement peuplé — pas
  une feuille par exigence individuelle, une par **groupe** de rattachement.
- **Business Rules:** un test couvrant des exigences de plusieurs groupes apparaît dans
  **chacune** des feuilles concernées (répétition assumée). La référence de rattachement pour
  IHM est le conteneur à `container_depth` de l'axe `E` (`container_of`) ; pour RM/EMOE c'est
  `requirement.parent`, le cas d'utilisation.
- **Exact names:** fonction `onglet_type_name(ref: str, grammar: Grammar) -> str`, passée à
  `sheet_title()` (inchangée) exactement comme aujourd'hui `chapter.key` l'est.
- **Priority:** Must-have

### FR-MOD-001 [EARS-E]: L'onglet par fonctionnalité est remplacé par un onglet par type d'exigence (references `build_workbook`)
> WHEN `build_workbook` construit les feuilles de tests THE système SHALL les grouper par type
> d'exigence et référence de rattachement (FR-NEW-077) au lieu de les grouper par fonctionnalité
> (`deliverable.build_tree`, `deliverable.py:148-184`).

- **Original behavior:** une feuille par `Chapter` (fonctionnalité, premier segment du
  conteneur), toutes les natures d'exigence mélangées dans la même feuille
  (`workbook.py:249-259`).
- **New behavior:** voir FR-NEW-077.
- **Reason for change:** demande explicite et sans débat de l'utilisatrice.
- **Business Rules:** `deliverable.build_tree` et `deliverable.py` restent **inchangés** : ils
  continuent de servir l'interface web. Seul `workbook.py` est modifié ici.

### FR-NEW-079 [EARS-O]: Pas d'onglet vide pour un type d'exigence absent du document
> IF un type d'exigence (RM, IHM, EMOE) n'est présent dans aucune exigence du document THEN THE
> système SHALL ne créer aucune feuille de ce type.

- **Inputs:** `state["requirements"]`.
- **Outputs:** absence de feuille, jamais une feuille avec une seule ligne d'en-tête.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| state 3 exigences | `EU01.CU01.RM01` (RM), `E04.M01` (IHM), `F01.EU02.CU03.EM01` (EMOE), chacune couverte par un test distinct | fixture test | ready |
| state RM-only | exigences uniquement RM, aucune IHM ni EMOE | fixture test | ready |
| test multi-écran | `TEST-0500` couvrant `E04.M01` et `E07.N01` (deux groupes IHM) | fixture test | ready |
| deux exigences même groupe | `E04.M01` et `E04.M02`, chacune couverte par un test différent | fixture test | ready |

### E2E-NEW-001: Le classeur recette crée une feuille par type d'exigence réellement présent
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077, FR-NEW-079
- **Driver:** direct function call (`tgi.workbook.build_workbook`)
- **Preconditions:** un `state` de test avec des exigences de type RM (rattachées à
  `EU01.CU01`), IHM (rattachées à `E04`) et EMOE (rattachées à `F01.EU02.CU03`), chacune couverte
  par au moins un test.
- **Steps:**
  - Given un `state` avec 3 exigences (`EU01.CU01.RM01`, `E04.M01`, `F01.EU02.CU03.EM01`),
    chacune couverte par un test distinct
  - When `build_workbook(state)` est appelé
  - Then le classeur contient exactement les feuilles `EU01.CU01-RM`, `IHM_E04`,
    `F01.EU02.CU03-EMOE` (plus "Synthèse", "Traçabilité")
  - And chaque feuille contient exactement les lignes du test qui couvre son exigence
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-NEW-003: Aucune feuille vide pour un type d'exigence absent
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-079
- **Driver:** direct function call
- **Steps:**
  - Given un `state` ne portant que des exigences RM, aucune IHM ni EMOE
  - When `build_workbook(state)` est appelé
  - Then aucune feuille nommée `IHM_*` ni `*-EMOE` n'existe dans le classeur
- **Cleanup:** aucun.
- **Priority:** High

### E2E-NEW-012: Un test couvrant deux groupes de rattachement apparaît dans les deux feuilles
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077
- **Driver:** direct function call
- **Steps:**
  - Given un test `TEST-0500` couvrant `E04.M01` (IHM, groupe `E04`) et `E07.N01` (IHM, groupe
    `E07`)
  - When le classeur est construit
  - Then `TEST-0500` apparaît dans la feuille `IHM_E04` **et** dans la feuille `IHM_E07`
- **Cleanup:** aucun.
- **Priority:** Medium

### E2E-NEW-023: Deux exigences du même groupe de rattachement partagent la même feuille
- **Category:** Error (absence-of-regression / side effect)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077, FR-NEW-079
- **Driver:** direct function call
- **Steps:**
  - Given deux exigences `E04.M01` et `E04.M02`, chacune couverte par un test différent
  - When le classeur est construit
  - Then une seule feuille `IHM_E04` existe, contenant les deux tests, et non deux feuilles
    `IHM_E04` et `IHM_E04 (2)`
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/deliverable.py` (FR-MOD-001 l'exige explicitement inchangé — il sert l'interface web),
`src/tgi/coverage_report.py`, `src/tgi/grammar.py` (déjà suffisants d'après l'impact analysis de
la spec).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne jamais contourner `sheet_title()` pour la gestion de collision de noms de feuille.

### Scope Boundary
Cette story ne traite PAS : le vidage des colonnes de métadonnées sur les lignes 2+ (US-0003), ni
l'onglet "Jeux de données" (US-0004), ni l'onglet "Analyse" (US-0007), ni la légende (US-0008).
Elle pose uniquement la structure des feuilles par type.

## Non Regression

### Existing Tests That Must Pass
Les tests de `tests/test_workbook.py` qui ne portent pas spécifiquement sur l'organisation par
fonctionnalité doivent être adaptés (noms de feuille attendus) mais continuer de passer — c'est
une story qui modifie `tests/test_workbook.py` en profondeur, pas une story qui le laisse intact.

### Behaviors That Must Not Change
`deliverable.build_tree` et toute route de `tgi.py` qui en dépend pour l'écran web restent
strictement inchangés.

### API Contracts to Preserve
La signature `build_workbook(state)` ne change pas.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
