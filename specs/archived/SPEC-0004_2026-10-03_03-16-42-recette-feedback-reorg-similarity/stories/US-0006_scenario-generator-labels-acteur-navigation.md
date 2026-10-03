
# US-0006: Générateur de scénarios — libellés, acteur réel, navigation explicite

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 5
> Depends On: US-0005
> Complexity: M
> min_tier: 2
> Files touched: 3

## Objective
Faire écrire par le générateur de scénarios des étapes plus lisibles pour Véronique : libellés
en clair plutôt que références codées, acteur réel du scénario plutôt que "l'utilisateur"
générique, et navigation explicite entre écrans avec détail des données citées.

## Technical Context

### Stack
Python 3.13, agent LLM mocké dans les tests.

### Relevant File Structure
```
src/tgi/
  agents/scenario_generator.py   # generate() (95-134), user_content (103-114)
  prompts/scenario_generator.md  # prompt livré, modifié ici
tests/
  test_scenario_generator.py
```

### Existing Patterns
`scenario_generator.py:111` transmet déjà `scenario.actors` au prompt. `scenario_generator.py:
103-114` construit `user_content` par concatenation de blocs ; le nouveau bloc "Libellés
connus:" suit le même style (un bloc texte ajouté avant l'appel LLM, jamais un post-traitement
de la réponse).

### Data Model (excerpt)
`labels: dict[str, str]` produit par US-0005 (distillateur), transmis en paramètre à
`ScenarioGeneratorAgent.generate`. `scenario.actors: list[str]` (peut être vide).

### Decisions That Govern This Story
Aucune décision additionnelle au-delà de DEC-023 (déjà appliquée dans US-0005, `labels` est un
dict structuré) : cette story consomme `labels`, elle ne le redéfinit pas.

### Applicable NFRs
Section 7.5 : ne jamais tracer le contenu des prompts/réponses LLM.

### Bounded Context
Génération (prompts) : `scenario_generator.md`, `src/tgi/agents/scenario_generator.py`.

## Functional Requirements

### FR-NEW-065 [EARS-E]: Le générateur de scénarios utilise les libellés en clair
> WHEN le générateur de scénarios écrit une étape qui référence un écran, un objet, un message
> ou un email THE système SHALL utiliser le libellé en clair fourni par `labels` plutôt que la
> référence codée, quand ce libellé existe.

- **Inputs:** dictionnaire `labels` produit par US-0005, transmis à
  `ScenarioGeneratorAgent.generate`.
- **Outputs:** texte d'étape utilisant "l'écran de composition du portefeuille" plutôt que
  "E04".
- **Business Rules:** si aucun libellé n'existe pour une référence citée, le code codé reste
  utilisé tel quel (dégradation silencieuse, pas d'erreur).
- **Exact names:** nouveau paramètre `labels: dict[str, str]` sur `generate(...)`, propagé dans
  le prompt sous un bloc "Libellés connus:" ajouté à `user_content`.
- **Priority:** Must-have

### FR-NEW-066 [EARS-U]: Le prompt générateur de scénarios nomme l'acteur réel dans les étapes
> THE prompt `scenario_generator.md` SHALL demander que chaque étape utilise le nom de l'acteur
> du scénario (`scenario.actors`) plutôt que le mot générique "l'utilisateur", quand un acteur
> est précisé.

- **Inputs:** `scenario.actors`.
- **Outputs:** texte d'étape "Le RRC sélectionne..." plutôt que "L'utilisateur sélectionne...".
- **Business Rules:** si `scenario.actors` est vide, "l'utilisateur" reste le terme par défaut
  (aucune régression sur les scénarios sans acteur précisé).
- **Exact names:** n/a (modification de prompt texte uniquement).
- **Priority:** Must-have

### FR-NEW-067 [EARS-U]: Le prompt générateur de scénarios impose la navigation explicite entre écrans
> THE prompt `scenario_generator.md` SHALL demander que toute étape qui change l'écran affiché
> nomme explicitement l'écran de départ et l'écran d'arrivée, en clair (via `labels` quand
> disponible), et que toute étape listant une donnée issue d'une exigence détaille cette donnée
> dans le texte de l'étape plutôt que de citer seulement la référence de l'exigence.

- **Inputs:** `labels`, les exigences du scénario (`requirements`).
- **Outputs:** texte d'étape "Depuis l'écran de composition du portefeuille (E04),
  l'utilisateur accède à l'écran de détail du contact (E07)" plutôt que "L'utilisateur navigue
  vers E07".
- **Business Rules:** s'applique uniquement quand le scénario ou ses exigences impliquent un
  changement d'écran ou une donnée listée en exigence ; ne force pas une étape de navigation
  artificielle sur un scénario mono-écran.
- **Exact names:** n/a (prompt texte).
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| scénario sans acteur | `actors: []` | fixture test | ready |
| labels vides | `{}` | fixture test | ready |

### E2E-NEW-014: Un scénario sans acteur précisé garde "l'utilisateur" générique
- **Category:** Error (absence-of-regression)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-066, FR-NEW-067
- **Driver:** direct function call (`ScenarioGeneratorAgent.generate`, LLM mocké)
- **Preconditions:** un scénario avec `actors: []`.
- **Steps:**
  - Given un scénario avec `actors: []`
  - When `generate(...)` est appelé avec `labels={}` et que le LLM mocké renvoie un test
    utilisant "l'utilisateur"
  - Then le test produit est accepté sans erreur de validation
  - And l'appel transmet bien le paramètre `labels` (même vide) au prompt sans lever
    d'exception
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/agents/distiller.py` (US-0005 l'a déjà fait), `src/tgi/workbook.py`.

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas forcer une étape de navigation artificielle sur un scénario mono-écran (FR-NEW-067,
business rule explicite).

### Scope Boundary
Cette story ne modifie que le prompt et la signature de `generate()` pour transmettre `labels` ;
elle ne modifie pas `distiller.py`.

## Non Regression

### Existing Tests That Must Pass
`tests/test_scenario_generator.py` existants.

### Behaviors That Must Not Change
Un scénario sans acteur continue de produire un test valide avec "l'utilisateur" générique.

### API Contracts to Preserve
`generate(...)` gagne un paramètre `labels`, mais reste appelable (l'orchestrateur, modifié en
conséquence, doit le transmettre — hors scope de cette story si l'orchestrateur n'est pas listé
dans les fichiers touchés : vérifier lors de l'implémentation si `orchestrator.py` doit aussi
être retouché pour propager `labels` depuis l'état du distillateur vers l'appel à `generate`; si
oui, c'est un ajustement minimal et mécanique, pas une nouvelle décision).

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
