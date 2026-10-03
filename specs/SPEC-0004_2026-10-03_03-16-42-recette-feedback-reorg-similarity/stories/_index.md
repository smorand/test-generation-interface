# User Stories Index

> Spec ID: SPEC-0004
> Source Specification: specs/SPEC-0004_2026-10-03_03-16-42-recette-feedback-reorg-similarity/spec.md
> Nature: FEAT
> Depth: L
> Generated on: 2026-10-03
> Target tier: 2 (standard frontier), resolved from default (no --tier flag, no .spec.json)
> Total: 13 stories in 0 epics (tier 2 — epic level collapsed into the story, per budget table)

## Slicing Verdict
| Verdict | SLICEABLE |
|---|---|
| Epics refused at this tier | none |
| Carried drift entries | none — source spec Implementability Gate verdict is IMPLEMENTABLE, 0 F / 0 A, Drift registered: none |

## Implementation Order
| Order | ID | Epic | Title | FRs | Scenarios | Tests | Files | Depends On | min_tier | Status |
|-------|----|----|-------|-----|-----------|-------|-------|------------|----------|--------|
| 1 | US-0001 | n/a | Module `classification.py` (MOA/MOE) | FR-NEW-074 | SC-001, SC-002 | E2E-NEW-005, E2E-NEW-016 | 2 | none | 2 | todo |
| 2 | US-0005 | n/a | Distillateur : `source_section` + glossaire `labels` | FR-NEW-063, FR-NEW-064 | SC-001 | E2E-NEW-013 | 3 | none | 2 | todo |
| 3 | US-0010 | n/a | Préfiltrage `similar_scenario_pairs` + seuil config | FR-NEW-082, FR-NEW-087 | SC-003 | E2E-NEW-021 | 4 | none | 2 | todo |
| 4 | US-0002 | n/a | Classeur recette : réorganisation par type d'exigence | FR-NEW-077, FR-MOD-001, FR-NEW-079 | SC-001 | E2E-NEW-001, 003, 012, 023 | 2 | US-0001 | 2 | todo |
| 5 | US-0006 | n/a | Générateur de scénarios : libellés, acteur, navigation | FR-NEW-065, 066, 067 | SC-001 | E2E-NEW-014 | 3 | US-0005 | 2 | todo |
| 6 | US-0011 | n/a | Prompt + agent `similarity_judge`, 4e clé | FR-NEW-083, FR-NEW-084 | SC-003 | E2E-NEW-020, 022 | 4 | none | 2 | todo |
| 7 | US-0003 | n/a | Vidage métadonnées lignes 2+ et colonne Classification | FR-NEW-075, 080, 081 | SC-001 | E2E-NEW-002, 011, MOD-001 | 2 | US-0002 | 2 | todo |
| 8 | US-0004 | n/a | Onglet "Jeux de données" | FR-NEW-078 | SC-001 | E2E-NEW-004 | 2 | US-0002 | 2 | todo |
| 9 | US-0007 | n/a | Onglet "Analyse" | FR-NEW-073 | SC-001 | E2E-NEW-010 | 2 | US-0002, US-0005 | 2 | todo |
| 10 | US-0008 | n/a | Légende onglets + renvoi croisé Synthèse→Traçabilité | FR-NEW-071, 072 | SC-001 | E2E-NEW-006 | 2 | US-0002 | 2 | todo |
| 11 | US-0009 | n/a | Export QC : Classification, Subject, verrouillage Test Name/Description | FR-NEW-068, 069, 070, 076 | SC-002 | E2E-NEW-007, 008, 009, 015 | 2 | US-0001, US-0002 | 2 | todo |
| 12 | US-0012 | n/a | Orchestrateur Phase 3bis : marquage `merged_into`, invariant couverture | FR-NEW-085, 086 | SC-003 | E2E-NEW-017, 018, 019, 024 | 2 | US-0010, US-0011 | 2 | todo |
| 13 | US-0013 | n/a | Accordéon prompts : 4e entrée `similarity_judge` | FR-NEW-088 | SC-003 | aucun E2E dédié dans le spec (note explicite dans la story) | 1 | US-0011 | 2 | todo |

## Dependency Graph
```
US-0001 ─┬─> US-0002 ─┬─> US-0003
         │            ├─> US-0004
         │            ├─> US-0007 <── US-0005
         │            ├─> US-0008
         │            └─> US-0009 <── US-0001
US-0005 ─┴─> US-0006

US-0010 ─┬─> US-0012
US-0011 ─┴─> US-0012
US-0011 ──> US-0013
```

## Coverage Verification (Phase 5 gate)
- Requirements in spec (`FR-NEW-`/`FR-MOD-`): 27 (26 FR-NEW-063..088 + 1 FR-MOD-001) | assigned: 27 | unassigned: none
- Tests in spec (`E2E-NEW-`/`E2E-MOD-`): 25 (24 E2E-NEW-001..024 + 1 E2E-MOD-001) | assigned: 24 (E2E-NEW-088 has no dedicated test, see US-0013 note) + 1 orphan test authored at implementation (FR-NEW-088) | unassigned: none (FR-NEW-088 has no spec-provided E2E id; its story documents this explicitly and instructs the implementer to author one minimal test from the EARS statement, per T2 budget — not a new technical decision)
- Scenarios in spec: 3 (SC-001, SC-002, SC-003) | covered: 3 | uncovered: none
- SC-orphan FRs homed: none (every FR appears in the section 11 matrix)
- Matrix-unassigned tests homed: 7 (E2E-NEW-004 → US-0004, E2E-NEW-005 → US-0001, E2E-NEW-006 → US-0008, E2E-NEW-022 → US-0011, E2E-NEW-023 → US-0002, E2E-NEW-024 → US-0012, E2E-MOD-001 → US-0003) — not listed by id in spec section 11's table, but their Scenario/FR are known from section 12.1 and homed accordingly.
