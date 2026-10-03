
# US-0012: Orchestrateur Phase 3bis — marquage `merged_into` et invariant de couverture

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 12
> Depends On: US-0010, US-0011
> Complexity: L
> min_tier: 2
> Files touched: 2

## Objective
Câbler la Phase 3bis dans l'orchestrateur : prendre les paires préfiltrées (US-0010), les
soumettre au juge de similarité (US-0011), et marquer de façon non destructive le scénario
redondant d'une paire jugée "doublon" ou "a_fusionner" — sans jamais toucher au calcul de
couverture arithmétique.

## Technical Context

### Stack
Python 3.13, orchestrateur de pipeline (`Orchestrator.run`).

### Relevant File Structure
```
src/tgi/
  agents/orchestrator.py    # run() (31), clôture des écarts (200-293), _finalize (198), gestion d'erreur LLM (170-178)
  testset.py                  # similar_scenario_pairs (US-0010)
  agents/similarity_judge.py  # SimilarityJudgeAgent.judge (US-0011)
  coverage_report.py           # coverage_summary (55-97) — NE JAMAIS MODIFIER NI APPELER DEPUIS CETTE PHASE AUTREMENT QU'EN LECTURE DE VÉRIFICATION
tests/
  test_orchestrator_pipeline.py
```

### Existing Patterns
`orchestrator.py:170-178` gère déjà `LLMJSONError`/`LLMConnectionError` pour les autres appels
LLM de la pipeline (consignation d'un avertissement, le run continue) : la Phase 3bis suit
exactement ce même patron pour EXC-003a. `orchestrator.py:198`, `self._finalize`, est le point
d'ancrage : la Phase 3bis s'exécute **avant** lui, pour que la marque `merged_into` soit visible
dans le classeur dès sa première génération (cross-scenario note de SC-003).

### Data Model (excerpt)
`scenario["merged_into"]: str | None`, `scenario["merge_reason"]: str`.

### Decisions That Govern This Story
- **DEC-029** (spec §17) : "Le scénario 'redondant' d'une paire jugée doublon est toujours celui
  dont l'id est numériquement le plus élevé, jamais un choix du juge... Implemented by:
  FR-NEW-085." Ne jamais laisser le juge décider lequel des deux scénarios disparaît de la vue
  principale.
- **DEC-030** (spec §17, invariant central de la vague 7) : "le juge de similarité ne modifie
  jamais le calcul de couverture arithmétique (`coverage_report.py`), quel que soit son
  verdict... Alternatives considered : aucune — ceci est un invariant non négociable, pas un
  choix de conception. Implemented by: FR-NEW-086. Code evidence: `coverage_report.py:55-97`
  (fonction `coverage_summary`, aucune référence à un juge)." Cette story NE DOIT PAS modifier
  `coverage_report.py`, et la Phase 3bis ne doit retirer aucun test ni aucune exigence du
  dénombrement.

### Applicable NFRs
Section 7.5 : ne jamais tracer prompts/réponses LLM. Tracer l'appel (`trace_span`), jamais son
contenu.

### Bounded Context
Génération (prompts) : agents dans `src/tgi/agents/`, entité verdict de similarité. Couverture
(inchangé) : `coverage_report.py` — lu en vérification uniquement par les tests, jamais modifié
ni appelé en écriture par cette story.

## Functional Requirements

### FR-NEW-085 [EARS-E]: Marquage non destructif d'une paire jugée doublon ou à fusionner
> WHEN le juge répond "doublon" ou "a_fusionner" pour une paire THE système SHALL ajouter au
> scénario désigné comme redondant un champ `merged_into` contenant l'id de l'autre scénario de
> la paire et un champ `merge_reason` contenant la justification du juge, SHALL NOT supprimer le
> scénario ni ses tests, et SHALL NOT retirer ses exigences du dénombrement de couverture.

- **Inputs:** le verdict de `SimilarityJudgeAgent.judge` (US-0011).
- **Outputs:** `scenario["merged_into"] = "<autre id>"`, `scenario["merge_reason"] = "<texte>"`.
- **Business Rules:** le scénario désigné comme "redondant" est celui dont l'id est le plus
  élevé numériquement dans la paire (DEC-029) ; "a_fusionner" est traité identiquement à
  "doublon" pour cette marque (`merge_reason` conserve le verdict exact).
- **Exact names:** champs `merged_into: str | None`, `merge_reason: str`.
- **Priority:** Must-have

### FR-NEW-086 [EARS-UB]: Le juge de similarité ne modifie jamais le calcul de couverture
> THE phase 3bis SHALL NOT retirer un test ou une exigence du dénombrement effectué par
> `coverage_report.coverage_summary` et `coverage_report.requirement_rows`, quel que soit le
> verdict du juge.

- **Priority:** Must-have (invariant)

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| paire doublon | `SC-010` (fonctionnalité `F01`), `SC-055` (fonctionnalité `F09`), ratio 0.95, LLM juge mocké répond `{"verdict": "doublon", "justification": "même parcours, même écran"}` | fixture test | ready |
| paire a_fusionner | LLM juge mocké répond `{"verdict": "a_fusionner", ...}` | fixture test | ready |
| paire variante légitime | `SC-020`, `SC-021`, ratio 0.92, LLM juge mocké répond `{"verdict": "variante_legitime", "justification": "actes différents du même acteur"}` | fixture test | ready |
| paire en échec | LLM juge mocké lève `LLMJSONError` sur la première paire, répond normalement sur la seconde | fixture test | ready |

### E2E-NEW-017: Deux scénarios de fonctionnalités différentes, jugés doublons
- **Category:** Core Journey
- **Scenario:** SC-003
- **Requirements:** FR-NEW-082, FR-NEW-084, FR-NEW-085
- **Driver:** direct function call (`Orchestrator`, LLM de juge mocké)
- **Preconditions:** deux scénarios `SC-010` (fonctionnalité `F01`) et `SC-055` (fonctionnalité
  `F09`), titres et noms de tests quasi identiques (ratio > 0.9), aucune `requirement_refs`
  commune.
- **Steps:**
  - Given `SC-010` et `SC-055` avec un ratio de similarité textuelle de 0.95
  - And le LLM de juge mocké répond `{"verdict": "doublon", "justification": "même parcours,
    même écran"}`
  - When la phase 3bis s'exécute
  - Then `SC-055["merged_into"] == "SC-010"` et `SC-055["merge_reason"]` contient la
    justification
  - And `SC-055` et ses tests sont toujours présents dans `state["scenarios"]`, non supprimés
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-NEW-018: Verdict "a_fusionner" produit la même marque non destructive que "doublon"
- **Category:** Core Journey
- **Scenario:** SC-003
- **Requirements:** FR-NEW-084, FR-NEW-085
- **Driver:** direct function call
- **Steps:**
  - Given une paire jugée `"a_fusionner"`
  - When la phase 3bis traite cette paire
  - Then le scénario de plus haut id porte `merged_into` renseigné, comme pour "doublon"
  - And `merge_reason` conserve la mention exacte "a_fusionner" dans la justification
    enregistrée
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-NEW-019: Un scénario jugé "variante légitime" n'est jamais fusionné ni retiré de la couverture
- **Category:** Edge (negative assertion sur l'invariant)
- **Scenario:** SC-003
- **Requirements:** FR-NEW-086
- **Driver:** direct function call
- **Preconditions:** deux scénarios avec un ratio de préfiltrage de 0.92, le LLM de juge mocké
  répond `{"verdict": "variante_legitime", "justification": "actes différents du même acteur"}`.
- **Steps:**
  - Given `SC-020` et `SC-021`, préfiltrés avec ratio 0.92
  - And le LLM de juge mocké répond "variante_legitime"
  - When la phase 3bis s'exécute
  - Then ni `SC-020` ni `SC-021` ne portent de champ `merged_into`
  - And `coverage_report.coverage_summary(state)["covered"]` est strictement identique (même
    valeur) avant et après l'exécution de la phase 3bis
  - And `coverage_report.coverage_summary(state)["tests"]` est strictement identique avant et
    après
- **Cleanup:** aucun.
- **Priority:** Critical

### E2E-NEW-024: Un scénario fusionné reste consultable dans la traçabilité avec sa marque
- **Category:** State Transition
- **Scenario:** SC-003
- **Requirements:** FR-NEW-085
- **Driver:** direct function call (`coverage_report.requirement_rows` puis vérification du
  scénario source)
- **Steps:**
  - Given `SC-055["merged_into"] == "SC-010"`
  - When l'onglet "Traçabilité" est construit (`requirement_rows(state)`)
  - Then les exigences couvertes par les tests de `SC-055` apparaissent toujours dans la
    matrice, avec leurs tests toujours listés
  - And rien dans la matrice ne masque ou ne filtre les tests d'un scénario `merged_into`
- **Cleanup:** aucun.
- **Priority:** High

## Constraints

### Files Not to Touch
`src/tgi/coverage_report.py` (invariant DEC-030 : jamais modifié, jamais appelé en écriture).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne jamais laisser le verdict du juge décider lequel des deux scénarios de la paire est marqué
redondant (DEC-029 : toujours l'id numériquement le plus élevé).

### Scope Boundary
Cette story ne modifie pas `src/tgi/templates/project.html` (US-0013).

## Non Regression

### Existing Tests That Must Pass
`tests/test_orchestrator_pipeline.py` existants (19 tests orchestrateur mentionnés en Phase 0
de la spec).

### Behaviors That Must Not Change
`coverage_report.coverage_summary` et `coverage_report.requirement_rows` produisent exactement
les mêmes valeurs avant et après l'exécution de la Phase 3bis, quel que soit le verdict du juge
(E2E-NEW-019).

### API Contracts to Preserve
`Orchestrator.run(project_id, version, model, llm, text)` garde sa signature.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
