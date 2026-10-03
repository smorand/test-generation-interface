---
id: BL-0004
title: Exposer une route HTTP pour le chat qui écrit (génération ciblée depuis le chat)
kind: idea
origin: Retour #23, email Véronique BERTAIL du 18/09/2026
created: 2026-10-03
---

## What

Le code du chat qui répond sur le document, les exigences, les tests et le run existe déjà :
`Orchestrator.handle_chat` (`src/tgi/agents/orchestrator.py:295-308`), avec ses fonctions de
contexte `_chat_context` et `_chat_summary` (`orchestrator.py:311` et suivantes), et son prompt
`src/tgi/prompts/chat.md`. `tests/test_chat_context.py` couvre ce contexte. Mais c'est un chat
**en lecture seule par construction** (`orchestrator.py:296-298`, docstring : "Read only by
design: nothing here modifies the project"), et surtout **aucune route HTTP ne l'expose
aujourd'hui** : `handle_chat` n'est appelée par aucun chemin de `src/tgi/tgi.py` (le tab de chat a
été retiré par DEC-003, cité en commentaire dans `orchestrator.py:298`).

Cette entrée couvre, si elle est un jour reprise : une route HTTP qui expose ce chat, et son
extension pour qu'il puisse **écrire** sur demande explicite — "génère moi deux ou trois tests de
plus sur ce scénario ou cette exigence" — avec les outils nécessaires (générer des tests pour une
cible nommée, les attacher au scénario, committer l'état).

Ce point est déjà documenté dans `BACKLOG.md` section 4 ("Chat that writes, not only reads"), qui
pose les contraintes à respecter : chaque écriture passe par le verrou d'état existant
(`src/tgi/locks.py`) et produit une mise à jour cohérente de l'état, la déduplication
(`testset.merge_tests`) et la cible de volume (`settings.tests_per_scenario`) s'appliquent à ce
que le chat ajoute comme à un run normal, et la réponse doit dire explicitement ce qui a changé et
où le relire. Le contrat lecture seule reste le défaut : écrire n'a lieu que sur demande explicite
nommant un scénario ou une exigence.

## Why

Router cette demande vers `/spec-feat` lorsqu'elle sera reprise : exposer une route change le
comportement observable (une capacité nouvelle apparaît côté interface), et lui faire accepter des
écritures change le contrat "lecture seule" documenté en commentaire aujourd'hui — ce sont deux
FR distinctes (exposition, puis écriture), pas une correction de défaut. Ce n'est pas repris dans
SPEC-0004 parce que le périmètre communiqué pour cette spécification s'arrête aux vagues 1 à 7 ;
#23 a été explicitement mis en attente par l'utilisateur ("vague 8 au standby").

## Notes

À router par `/spec-feat` si retenu, avec au moins deux décisions produit à trancher avant
l'interview : (1) la route expose-t-elle le chat en lecture seule d'abord, en incrément séparé de
l'écriture, ou les deux sont-elles spécifiées ensemble ; (2) quelles cibles de génération le chat
peut nommer (un scénario par id, une exigence par référence, les deux) et ce qu'il refuse
(générer sur tout le projet depuis le chat, par exemple, qui recrée un run complet par une porte
dérobée).
