
# US-0005: Distillateur — `source_section` et glossaire `labels`

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 2
> Depends On: none
> Complexity: M
> min_tier: 2
> Files touched: 3

## Objective
Faire porter à chaque scénario produit par le distillateur la section du document dont il
provient (`source_section`, calculée par code, jamais demandée au modèle), et faire extraire par
le modèle un glossaire `labels` (référence courte → libellé en clair), filtré aux seules
références réellement présentes dans le document.

## Technical Context

### Stack
Python 3.13, agents LLM mockés dans les tests (`LLMClient` factice, aucun réseau).

### Relevant File Structure
```
src/tgi/
  agents/distiller.py     # fonction _clean_scenario (distiller.py:84-98), split_for_reading (52-70)
  grammar.py               # Grammar.container_of(ref), keep_known_references
  prompts/distiller.md     # prompt livré, modifié ici
tests/
  test_distiller.py
```

### Existing Patterns
`distiller.py:84-98`, fonction `_clean_scenario`, filtre déjà les références citées par un
scénario contre `keep_known_references` (`grammar.py`). Le même filtre doit s'appliquer au
nouveau dictionnaire `labels`. `grammar.py:122-129` expose `container_of(ref)` pour retrouver la
section conteneur d'une référence.

### Data Model (excerpt)
Scénario produit par le distillateur : dict avec (entre autres) `requirement_refs: list[str]`.
Nouveau champ à ajouter : `source_section: str` (vide si aucune référence citée). Nouvelle clé
JSON du distillateur : `labels: dict[str, str]`.

### Decisions That Govern This Story
- **DEC-023** (spec §17) : "Les libellés en clair (#2) sont extraits comme un résultat séparé
  `labels` du distillateur, plutôt que fusionnés dans le `context` texte libre existant...
  Implemented by: FR-NEW-064, FR-NEW-065." → `labels` est une clé JSON structurée, jamais du
  texte libre à parser.
- **DEC-024** (spec §17) : "`source_section` est calculée par code (via `grammar.container_of`),
  jamais demandée au modèle... Implemented by: FR-NEW-063." → ne JAMAIS demander `source_section`
  au LLM dans le prompt, la calculer en Python après réception de la réponse.

### Applicable NFRs
Section 7.5 : ne jamais tracer le contenu des prompts/réponses LLM dans les logs/traces.

### Bounded Context
Génération (prompts) : `distiller.md` ; agents dans `src/tgi/agents/`. Entités : scénario, test,
exigence, verdict de similarité (ce dernier hors scope ici).

## Functional Requirements

### FR-NEW-063 [EARS-E]: Lecture section par section pour réduire les faux "Missing"
> WHEN le distillateur traite un document découpé en plusieurs parties THE système SHALL
> associer à chaque scénario produit la référence de la section du document dont il provient, en
> plus du conteneur déjà extrait.

- **Inputs:** texte du document, `grammar.Grammar`.
- **Outputs:** champ `source_section` ajouté à chaque scénario, dans `_clean_scenario`.
- **Business Rules:** `source_section` est la section identifiée par `grammar.container_of(ref)`
  pour la première référence citée par le scénario, ou vide si aucune référence n'est citée.
  N'a aucun effet sur le calcul de couverture (purement informatif).
- **Exact names:** champ `source_section: str` dans l'objet scénario.
- **Priority:** Must-have

### FR-NEW-064 [EARS-U]: Le prompt distillateur demande explicitement un glossaire de libellés
> THE prompt `distiller.md` SHALL demander un quatrième résultat, `labels`, un dictionnaire des
> libellés en clair (écran, objet, message, email) rencontrés dans le document, indexé par leur
> référence courte.

- **Inputs:** le document source.
- **Outputs:** clé `labels` dans le JSON retourné par le distillateur :
  `{"E04": "Écran de composition du portefeuille", "N03": "Notification de clôture", ...}`.
- **Business Rules:** seules les références déjà connues du document (vérifiées par
  `keep_known_references`, `grammar.py`) peuvent être clés de ce dictionnaire ; une référence non
  trouvée dans le texte est filtrée, comme pour `requirement_refs`.
- **Exact names:** clé JSON `labels`, consommée dans `distiller.py` par une nouvelle fonction
  `_clean_labels(raw, text)` suivant le même filtre que `_clean_scenario`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| LLM mocké distillateur | renvoie `{"context": "...", "scenarios": [...], "discards": [], "labels": {"E04": "Écran de composition du portefeuille", "ZZZ99": "Référence inventée"}}` | fixture test | ready |
| document source | contient `E04` littéralement, ne contient pas `ZZZ99` | fixture test | ready |

### E2E-NEW-013: Le distillateur produit un glossaire de libellés filtré aux références connues
- **Category:** Happy
- **Scenario:** SC-001
- **Requirements:** FR-NEW-063, FR-NEW-064
- **Driver:** direct function call (`DistillerAgent.distil`, avec un `LLMClient` mocké)
- **Preconditions:** LLM mocké renvoie `{"context": "...", "scenarios": [...], "discards": [],
  "labels": {"E04": "Écran de composition du portefeuille", "ZZZ99": "Référence inventée"}}`, où
  `ZZZ99` n'apparaît pas dans le document source.
- **Steps:**
  - Given le document source contient la référence `E04` mais pas `ZZZ99`
  - When `distiller.distil(model, text)` est appelé
  - Then le résultat contient `labels == {"E04": "Écran de composition du portefeuille"}`
  - And `ZZZ99` est absent de `labels` (filtré par `keep_known_references`)
  - And chaque scénario produit porte un champ `source_section` non None quand son premier
    `requirement_refs` a un conteneur connu
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/agents/scenario_generator.py` (consommateur de `labels`, c'est US-0006, pas cette
story), `src/tgi/coverage_report.py`.

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne jamais demander `source_section` au modèle dans le prompt : c'est un champ calculé en Python
après réception de la réponse JSON (DEC-024).

### Scope Boundary
Cette story ne modifie pas `scenario_generator.py` : elle produit `labels` et `source_section`,
elle ne les consomme pas encore.

## Non Regression

### Existing Tests That Must Pass
Tous les tests existants de `tests/test_distiller.py`.

### Behaviors That Must Not Change
Le filtrage existant de `requirement_refs` via `keep_known_references` reste identique ;
`labels` suit exactement la même logique de filtre.

### API Contracts to Preserve
La signature de `distiller.distil(model, text)` ne change pas (pas de nouveau paramètre requis),
seul le dict retourné gagne les champs `labels` (niveau résultat) et `source_section` (par
scénario).

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
