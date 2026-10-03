
# US-0011: Prompt et agent `similarity_judge`, quatrième clé de prompt

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 6
> Depends On: none
> Complexity: M
> min_tier: 2
> Files touched: 4

## Objective
Ajouter `similarity_judge` comme quatrième clé de prompt (au même titre que `distiller`,
`scenario_generator`, `coverage`), livrer son prompt par défaut, et créer l'agent qui soumet une
paire de scénarios candidats au LLM et renvoie un verdict (`doublon`, `variante_legitime`,
`a_fusionner`) avec justification. Cette story ne câble pas encore l'appel dans l'orchestrateur
(US-0012).

## Technical Context

### Stack
Python 3.13, agents LLM mockés dans les tests (aucun réseau).

### Relevant File Structure
```
src/tgi/
  services/prompts.py          # PROMPT_KEYS (prompts.py:12), is_known_prompt_key, default_prompt (15-21)
  prompts/
    distiller.md
    scenario_generator.md
    coverage.md
    similarity_judge.md         # NOUVEAU
  agents/
    coverage.py                  # modèle de structure d'agent à suivre
    similarity_judge.py          # NOUVEAU
tests/
  test_similarity_judge.py       # NOUVEAU
```

### Existing Patterns
`services/prompts.py:12`, `PROMPT_KEYS = ("distiller", "scenario_generator", "coverage")` passe
à 4 éléments. `agents/coverage.py` est le modèle de structure d'agent LLM à suivre (classe avec
une méthode qui appelle le LLM et parse un JSON de réponse). La gestion d'erreur JSON illisible
ou de connexion suit `orchestrator.py:170-178` (`LLMJSONError`/`LLMConnectionError` déjà gérés).

### Data Model (excerpt)
Entrée de `judge()` : deux scénarios, chacun avec titre, tests, `requirement_refs`. Sortie :
`{"verdict": "doublon" | "variante_legitime" | "a_fusionner", "justification": str}`.

### Decisions That Govern This Story
- **DEC-030** (spec §17, invariant central) : "le juge de similarité ne modifie jamais le calcul
  de couverture arithmétique (`coverage_report.py`), quel que soit son verdict... Implemented
  by: FR-NEW-086." Cet agent ne doit JAMAIS importer ni appeler `coverage_report.py`.

### Applicable NFRs
Section 7.5 : ne jamais tracer prompts/réponses LLM. Tracer l'appel lui-même
(`trace_span("llm.chat")`), jamais son contenu.

### Bounded Context
Génération (prompts) : `similarity_judge.md` ; agents dans `src/tgi/agents/`. Entité : verdict
de similarité.

## Functional Requirements

### FR-NEW-083 [EARS-U]: Nouveau prompt `similarity_judge.md`, quatrième clé de prompt
> THE système SHALL ajouter `similarity_judge` à `PROMPT_KEYS`
> (`src/tgi/services/prompts.py:12`) et un fichier `src/tgi/prompts/similarity_judge.md` livré
> avec le paquet.

- **Inputs:** n/a (nouveau fichier statique).
- **Outputs:** `PROMPT_KEYS = ("distiller", "scenario_generator", "coverage",
  "similarity_judge")`. Le prompt demande au modèle, pour une paire de scénarios donnée (titre,
  tests, exigences couvertes de chacun), de répondre par un verdict parmi `"doublon"`, `"variante
  legitime"`, `"a_fusionner"`, avec une justification en une phrase.
- **Business Rules:** une version créée avant ce changement ne porte pas cette 4e clé dans ses
  fichiers de prompt sur disque ; `read_prompts` doit se rabattre sur le défaut quand la clé
  manque (comportement attendu de `is_known_prompt_key`/`default_prompt`, `prompts.py:15-21`, à
  vérifier dans `StateManager.read_prompts`).
- **Exact names:** clé `"similarity_judge"`, fichier `similarity_judge.md`.
- **Priority:** Must-have

### FR-NEW-084 [EARS-E]: Appel du juge de similarité sur chaque paire préfiltrée
> WHEN une paire de scénarios a passé le préfiltrage THE système SHALL soumettre cette paire au
> juge LLM avec le prompt `similarity_judge`, et SHALL enregistrer son verdict.

- **Inputs:** la paire de scénarios (titre, tests, requirement_refs de chacun), le modèle choisi
  pour la version.
- **Outputs:** un verdict par paire : `"doublon"`, `"variante_legitime"`, ou `"a_fusionner"`,
  plus une justification textuelle.
- **Business Rules:** un appel par paire (pas de batch multi-paires dans un seul appel), pour que
  chaque verdict soit traçable à sa paire et que l'échec d'un appel n'affecte pas les autres.
- **Exact names:** nouveau module `src/tgi/agents/similarity_judge.py`, classe
  `SimilarityJudgeAgent`, méthode `judge(model, scenario_a, scenario_b) -> dict`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| répertoire version 3 prompts | `distiller.md`, `scenario_generator.md`, `coverage.md`, sans `similarity_judge.md` | fixture test (répertoire temporaire) | ready |
| LLM juge mocké erreur JSON | lève `LLMJSONError` | fixture test | ready |
| LLM juge mocké réponse normale | renvoie un verdict valide | fixture test | ready |

### E2E-NEW-022: Une version créée avant l'ajout de la 4e clé de prompt se rabat sur le défaut
- **Category:** Error (compatibility)
- **Scenario:** SC-003
- **Requirements:** FR-NEW-083
- **Driver:** direct function call (`StateManager.read_prompts`)
- **Steps:**
  - Given un répertoire de version sur disque ne portant que 3 fichiers de prompt
    (`distiller.md`, `scenario_generator.md`, `coverage.md`), sans `similarity_judge.md`
  - When `read_prompts(project_id, version)` est appelé après la mise à jour du code
  - Then le prompt `similarity_judge` retourné est le prompt par défaut
    (`default_prompt("similarity_judge")`), sans lever d'exception
- **Cleanup:** aucun.
- **Priority:** Medium

### E2E-NEW-020: Échec du juge sur une paire : la paire est ignorée, le run continue
- **Category:** Error
- **Scenario:** SC-003
- **Requirements:** FR-NEW-084 (EXC-003a)
- **Driver:** direct function call, LLM de juge mocké lève `LLMJSONError`
- **Steps:**
  - Given un appel `SimilarityJudgeAgent.judge(...)` dont le LLM mocké lève `LLMJSONError`
  - When `judge(...)` est appelé
  - Then l'exception est propagée de façon identifiable (le type `LLMJSONError`, pour que
    l'appelant — câblé en US-0012 — puisse l'attraper et consigner un avertissement sans faire
    échouer tout le run)
- **Cleanup:** aucun.
- **Priority:** High

## Constraints

### Files Not to Touch
`src/tgi/agents/orchestrator.py` (câblage dans US-0012), `src/tgi/coverage_report.py` (DEC-030,
jamais importé ni appelé par cet agent).

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas batcher plusieurs paires dans un seul appel LLM (FR-NEW-084, business rule explicite).

### Scope Boundary
Cette story crée le prompt et l'agent, elle ne les branche pas dans le pipeline (c'est US-0012).

## Non Regression

### Existing Tests That Must Pass
`tests/test_prompts.py` (ou équivalent) existants, toute la suite `services/prompts.py`.

### Behaviors That Must Not Change
Les 3 clés de prompt existantes (`distiller`, `scenario_generator`, `coverage`) continuent de
fonctionner exactement comme avant.

### API Contracts to Preserve
Aucune signature existante modifiée (ajout pur).

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
