
# US-0010: Préfiltrage textuel des paires de scénarios + seuil de configuration

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 3
> Depends On: none
> Complexity: M
> min_tier: 2
> Files touched: 4

## Objective
Ajouter une fonction de préfiltrage textuel pur (sans appel LLM) qui identifie, parmi tous les
scénarios d'un projet (toutes fonctionnalités confondues), les paires candidates à la
similarité, bornées par un nouveau seuil de configuration. C'est l'étape qui borne le nombre
d'appels LLM que fera le juge de similarité (US-0011/US-0012), jamais l'inverse.

## Technical Context

### Stack
Python 3.13, `difflib.SequenceMatcher` (stdlib, déjà utilisé dans le projet).

### Relevant File Structure
```
src/tgi/
  testset.py    # similar_rule_pairs (testset.py:147-176) — modèle à suivre
  config.py      # Settings (config.py:95-172), env_prefix TGI_
tests/
  test_testset.py
  test_config.py
```

### Existing Patterns
`testset.py:147-176`, fonction `similar_rule_pairs`, est le modèle exact à suivre : comparaison
`SequenceMatcher` en O(n²), triée par ratio décroissant, avec une limite. La nouvelle fonction
compare sur l'ensemble du projet (toutes fonctionnalités), à la différence de
`_is_near_duplicate` (`testset.py:72-85`) qui exige `rule_ids_of(candidate) ==
rule_ids_of(kept)` — cette contrainte ne s'applique **pas** ici.

`config.py:95-172`, classe `Settings`, `env_prefix` déjà `TGI_` : un nouveau champ suit le même
style que les champs existants (type, défaut, description).

### Data Model (excerpt)
Scénario : dict avec `id: str`, `title/name` et `tests: list[dict]` (chaque test a un `name`).
Sortie attendue : `list[tuple[str, str, float]]` = `(scenario_id_a, scenario_id_b, ratio)`.

### Decisions That Govern This Story
- **DEC-028** (spec §17, Phase 2) : "Approche A (retenue) : comparaison textuelle exhaustive en
  O(n²) sur `SequenceMatcher`, sur le modèle déjà en place pour `similar_rule_pairs`... sans
  dépendance nouvelle... Implemented by: FR-NEW-082." L'approche B (clustering/embeddings) est
  explicitement écartée, ne pas l'introduire.

### Applicable NFRs
Section 7.1 : "Le préfiltrage de FR-NEW-082 est en O(n²) sur le nombre de scénarios du projet,
pur Python (`SequenceMatcher`), donc négligeable même pour plusieurs centaines de scénarios."

### Bounded Context
Génération (prompts) : agents dans `src/tgi/agents/` ; Configuration : `config.py` (`Settings`),
entité `TGI_SCENARIO_SIMILARITY_THRESHOLD`.

## Functional Requirements

### FR-NEW-082 [EARS-E]: Préfiltrage textuel des paires de scénarios candidates à la similarité
> WHEN la phase 3bis démarre pour une version THE système SHALL calculer, pour chaque paire de
> scénarios du projet (toutes fonctionnalités confondues), une similarité textuelle sur la
> concaténation du titre du scénario et des noms de ses tests, et SHALL ne retenir que les
> paires dont la similarité dépasse `settings.scenario_similarity_threshold`.

- **Inputs:** `state["scenarios"]`, chaque scénario avec son titre et ses tests.
- **Outputs:** liste de paires `(scenario_id_a, scenario_id_b, ratio)`, triée par ratio
  décroissant.
- **Business Rules:** comparaison en O(n²) sur l'ensemble des scénarios du projet. Préfiltrage
  pur Python (`SequenceMatcher`), sans appel LLM à ce stade.
- **Exact names:** nouvelle fonction `similar_scenario_pairs(scenarios, threshold, limit)` dans
  `testset.py`, sur le modèle de `similar_rule_pairs` (`testset.py:147-176`).
- **Priority:** Must-have

### FR-NEW-087 [EARS-U]: Nouveau paramètre `TGI_SCENARIO_SIMILARITY_THRESHOLD`
> THE `Settings` (`src/tgi/config.py:95-172`) SHALL porter un champ
> `scenario_similarity_threshold: float = 0.9`, lu depuis la variable d'environnement
> `TGI_SCENARIO_SIMILARITY_THRESHOLD`.

- **Inputs:** variable d'environnement ou `.env`.
- **Outputs:** `settings.scenario_similarity_threshold`, consommé par `similar_scenario_pairs`.
- **Business Rules:** pilote uniquement le seuil de **préfiltrage textuel** (le nombre de paires
  envoyées au juge), jamais le seuil de décision du juge lui-même.
- **Exact names:** `TGI_SCENARIO_SIMILARITY_THRESHOLD`, champ Python
  `scenario_similarity_threshold`.
- **Priority:** Must-have

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| 3 scénarios | ratios de similarité textuelle 0.85, 0.92, 0.98 entre les paires | fixture test (titres/tests construits pour produire ces ratios réels via `SequenceMatcher`) | ready |

### E2E-NEW-021: Le seuil `TGI_SCENARIO_SIMILARITY_THRESHOLD` change le nombre de paires préfiltrées
- **Category:** Edge
- **Scenario:** SC-003
- **Requirements:** FR-NEW-087
- **Driver:** direct function call (`testset.similar_scenario_pairs`)
- **Preconditions:** 3 scénarios avec des ratios de similarité textuelle de 0.85, 0.92, 0.98
  entre les paires.
- **Steps:**
  - Given 3 scénarios avec des ratios de similarité textuelle de 0.85, 0.92, 0.98 entre les
    paires
  - When `similar_scenario_pairs(scenarios, threshold=0.9)` est appelé
  - Then exactement 2 paires sont retournées (celles à 0.92 et 0.98)
  - And `similar_scenario_pairs(scenarios, threshold=0.99)` retourne 0 paire
- **Cleanup:** aucun.
- **Priority:** Medium

## Constraints

### Files Not to Touch
`src/tgi/agents/similarity_judge.py` (US-0011), `src/tgi/agents/orchestrator.py` (US-0012) : cette
story ne câble rien, elle produit seulement la fonction de préfiltrage et le paramètre.

### Dependencies Not to Add
Aucune nouvelle dépendance externe ; `SequenceMatcher` est stdlib.

### Patterns to Avoid
Ne pas implémenter de clustering ou d'embedding (DEC-028, approche B explicitement écartée).

### Scope Boundary
Pas d'appel LLM dans cette story.

## Non Regression

### Existing Tests That Must Pass
`tests/test_testset.py` et `tests/test_config.py` existants.

### Behaviors That Must Not Change
`similar_rule_pairs` et `_is_near_duplicate` (dédoublonnage par mêmes références d'exigences)
restent inchangés : `similar_scenario_pairs` est une fonction nouvelle, pas une modification de
l'existant.

### API Contracts to Preserve
Aucune signature existante n'est modifiée.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
