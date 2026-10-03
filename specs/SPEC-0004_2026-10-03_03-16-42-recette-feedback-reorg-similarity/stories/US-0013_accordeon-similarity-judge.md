
# US-0013: Accordéon des prompts — quatrième entrée `similarity_judge`

> Parent Spec: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Spec ID: SPEC-0004
> Epic: n/a
> Status: ready
> Priority: 13
> Depends On: US-0011
> Complexity: S
> min_tier: 2
> Files touched: 1

## Objective
Afficher le prompt `similarity_judge` comme une quatrième entrée de l'accordéon des prompts sur
`project.html`, au même titre que `distiller`, `scenario_generator` et `coverage` (parité
d'interface, pas de nouvelle exigence de contenu).

## Technical Context

### Stack
HTML templates servis par FastAPI (`templates/project.html`), IBM Carbon Design System (CSS +
Web Components via CDN, sans bundler).

### Relevant File Structure
```
src/tgi/templates/project.html   # accordéon des 3 prompts existants, introduit par SPEC-0003
```

### Existing Patterns
L'accordéon affiche aujourd'hui 3 sections repliables, une par clé de `PROMPT_KEYS`
(`distiller`, `scenario_generator`, `coverage`), introduites par SPEC-0003. La 4e section suit
exactement le même motif HTML/Carbon que les trois existantes.

### Data Model (excerpt)
`PROMPT_KEYS` étendu à 4 clés par US-0011 : `("distiller", "scenario_generator", "coverage",
"similarity_judge")`.

### Decisions That Govern This Story
Aucune décision additionnelle : parité d'interface pure, FR-NEW-088 ne porte aucune règle de
contenu nouvelle.

### Applicable NFRs
Section 7.3 (usabilité) : cohérence de présentation avec les 3 entrées existantes.

### Bounded Context
Génération (prompts) : `PROMPT_KEYS` (déjà étendu par US-0011), consommé ici côté template.

## Functional Requirements

### FR-NEW-088 [EARS-S]: Affichage du prompt `similarity_judge` dans l'accordéon des prompts
> WHILE l'utilisateur consulte l'accordéon des prompts d'une version sur `templates/
> project.html` (introduit par SPEC-0003) THE système SHALL afficher le prompt
> `similarity_judge` comme une quatrième entrée, au même titre que `distiller`,
> `scenario_generator` et `coverage`.

- **Inputs:** `PROMPT_KEYS` étendu (US-0011, FR-NEW-083).
- **Outputs:** une quatrième section repliable dans l'accordéon.
- **Priority:** Must-have
- **Rationale:** cohérence de l'interface, FR-NEW-083 crée une 4e clé qui doit être éditable
  comme les trois autres.

## Acceptance Tests

> **100% must pass.** Boucle fix / run / check jusqu'à zéro échec, via la cible Makefile du
> projet.

> **Note de couverture (gate Phase 5, transparence) :** FR-NEW-088 n'a aucun E2E dédié dans le
> document de spécification (ni en section 12.1, ni en section 18 self-consistency, qui couvre
> explicitement ce point pour FR-NEW-071/072 mais pas pour FR-NEW-088). C'est une caractéristique
> du document source, pas un défaut de ce découpage. Le test ci-dessous est écrit par
> l'implémenteur à partir du seul EARS disponible (budget T2 : "designs tests from Given/When/
> Then"), sans introduire de décision technique absente du spec — il vérifie uniquement la
> présence de la 4e section, un fait d'interface déjà entièrement décrit par FR-NEW-088.

### Test Data
| Data | Description | Source | Status |
|------|-------------|--------|--------|
| version avec 4 prompts | `PROMPT_KEYS` étendu par US-0011, prompts lus pour une version | fixture test | ready |

### Test à écrire (pas d'ID E2E-XXX dans le spec — voir note ci-dessus)
- **Category:** Feature
- **Scenario:** SC-003 (cohérence d'interface pour le même changement)
- **Requirements:** FR-NEW-088
- **Driver:** HTTP client (requête sur la route qui rend `project.html` pour une version), ou test
  de rendu direct du template si le projet a déjà ce patron pour SPEC-0003.
- **Steps:**
  - Given une version dont `PROMPT_KEYS` comprend les 4 clés
  - When la page du projet est rendue
  - Then le HTML contient une section repliable pour `similarity_judge`, au même niveau que les
    3 sections existantes (`distiller`, `scenario_generator`, `coverage`)
- **Cleanup:** aucun.
- **Priority:** Must-have

## Constraints

### Files Not to Touch
`src/tgi/services/prompts.py` (déjà étendu par US-0011), `src/tgi/agents/`.

### Dependencies Not to Add
Aucune.

### Patterns to Avoid
Ne pas introduire de logique de contenu différente pour cette 4e section : elle doit être
strictement symétrique aux trois existantes.

### Scope Boundary
Cette story ne touche que `project.html`.

## Non Regression

### Existing Tests That Must Pass
Les tests existants sur l'accordéon de SPEC-0003 (3 entrées).

### Behaviors That Must Not Change
Les 3 entrées existantes gardent leur comportement d'édition identique.

### API Contracts to Preserve
Aucune route modifiée.

## Self-Review Checklist
Full 4-axis self-review per `/implement` Phase 3.3 Step 5.
