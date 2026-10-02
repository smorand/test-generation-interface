---
id: BL-0001
title: infer_grammar lève ValueError sur un document à un seul cas d'utilisation
kind: bug
origin: relevé hors périmètre par l'audit d'implémentabilité de SPEC-0001a, round 4
created: 2026-10-01
---

## What

`infer_grammar()` lève `ValueError: max() iterable argument is empty` à
`src/tgi/grammar.py:184` lorsque le document d'entrée ne porte qu'un seul cas d'utilisation.
La distillation tourne en tâche de fond et l'exception n'est pas rattrapée, donc le projet
reste bloqué dans son état de départ sans que rien ne le signale à l'utilisatrice.

## Why

Deux défauts se composent, et le second est le plus grave :

1. `max()` est appelé sur un itérable qui peut être vide quand le document n'offre pas assez
   de matière pour inférer une profondeur.
2. La tâche de fond n'a pas de gestionnaire d'exception, donc une erreur de distillation ne
   produit ni état `failed`, ni message, ni trace visible. Le projet paraît simplement figé.

Le second défaut dépasse ce cas précis : toute exception de distillation se comporte ainsi
aujourd'hui.

## Evidence

- `src/tgi/grammar.py:184`, l'appel à `max()`.
- `src/tgi/tgi.py:306-308`, la création de la tâche de fond sans rattrapage.
- Reproduit pendant l'audit de SPEC-0001a round 4, sur un document d'essai à un cas
  d'utilisation.

## Notes

Ne relève pas de la classe CWE-22 de SPEC-0001a et n'y a donc pas été traité.
Recoupe partiellement SPEC-0001b FR-NEW-024 et FR-NEW-050, qui imposent qu'une distillation
en échec fasse passer la version en `failed` avec un message nommé : si SPEC-0001b est
implémentée, le second défaut est fermé par elle et il ne reste que le `max()` à corriger.
À router par `/analysis` plutôt que par `/spec-feat`, le comportement observable étant
défectueux et non manquant.
