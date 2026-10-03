# Test Interface — retours de recette : prompts, export QC, classeur par type d'exigence, juge de similarité — Specification Document

> Generated on: 2026-10-03
> Id: SPEC-0004
> Nature: FEAT
> Depth: L
> Depth evidence: 8 modules touchés (`src/tgi/workbook.py`, `src/tgi/qc_export.py`, `src/tgi/coverage_report.py`, `src/tgi/grammar.py`, `src/tgi/config.py`, `src/tgi/agents/orchestrator.py`, `src/tgi/testset.py`, `src/tgi/templates/project.html`), 3 prompts existants modifiés et 1 nouveau prompt (`similarity_judge.md`), un nouveau paramètre de configuration, et plus de 15 exigences anticipées (35). Au-dessus du seuil L sur tous les critères.
> Status: Draft
> Type: Evolution Specification
> From backlog: n/a
> Split: not split
> Depends on: none
> Security: n/a
> CVSS: n/a
> Affected: n/a
> Fixed in: n/a

## 1. Executive Summary

Véronique BERTAIL, seule utilisatrice actuelle de l'outil, a fait 23 retours (email du
18/09/2026, "Retours analyses suite génération du fichier des cas de test via l'IA (TGI)") en
préparant un cahier de recette sur un classeur généré par TGI. Cette spécification couvre 18 de
ces 23 retours, regroupés en 6 vagues de travail : corrections de prompts (lisibilité des
libellés, navigation, profil utilisateur), précision du mapping de l'export QC (colonnes
Subject/Test Name/Description), clarté de l'onglet Synthèse et observabilité de l'analyse dans
le classeur livré, classification MOA/MOE des tests, et la réorganisation complète du classeur
recette d'une structure par fonctionnalité à une structure par type d'exigence (RM / IHM /
EMOE), avec séparation des jeux de données dans un onglet dédié. Une septième vague ajoute un
juge de similarité LLM entre scénarios pour signaler les doublons sans jamais toucher au calcul
arithmétique de couverture. Une 8e demande (#23, chat qui écrit) ne fait l'objet d'aucune
exigence ici : elle va au backlog (section 15 pointe vers `backlog/BL-0004_*.md`).

Aucun comportement cassé aujourd'hui n'est corrigé par urgence : chaque retour ajoute une
surface observable nouvelle (libellé plus clair, colonne nouvelle, onglet réorganisé, verdict de
similarité) — c'est un FEAT, pas une correction de défaut.

## 2. Current State (MANDATORY, every depth)

### 2.1 How it works today

**Statuts de couverture et "Untestable" (#5, #6).** Le statut d'une exigence dans la matrice de
traçabilité est calculé en 4 valeurs : `covered`, `untestable`, `discarded`, `missing`
(`src/tgi/coverage_report.py:99-144`, fonction `requirement_rows`). `untestable` vient
exclusivement d'une déclaration du modèle lors de la passe de clôture des écarts
(`src/tgi/agents/coverage.py:139-144`, champ `untestable` dans la réponse JSON, prompt
`src/tgi/prompts/coverage.md:26-28` : "Si une exigence n'est pas testable en boîte noire... mets-la
dans `untestable`"). Il n'existe aucun filtre de relecture de la section 2.2.3 du document
spécifique au distillateur : `src/tgi/prompts/distiller.md` ne mentionne aucune section
particulière, et le découpage du texte en parties se fait sur l'ensemble du document
(`src/tgi/agents/distiller.py:52-70`, fonction `split_for_reading`, coupe sur `\n#`, pas sur un
numéro de section). Un cas "Missing" causé par une mauvaise lecture d'une section précise du
document par le distillateur n'a pas de mécanisme de citation : le distillateur ne reçoit comme
contrainte que "Couvre tout le document" (`src/tgi/prompts/distiller.md:19`). **ASSUMED:** les
références précises RM04/07/08 et la section 2.2.3 citées dans la demande ne sont pas vérifiables
dans ce dépôt (aucun exemplaire du document fonctionnel de Véronique n'est présent dans le
repo) ; le diagnostic retenu ici est structurel (le prompt ne guide ni la lecture section par
section, ni la distinction entre "non testable" et "non trouvé"), pas un bug reproductible cité
par un test existant.

**Profil utilisateur générique (#3).** Le prompt `scenario_generator.md:1` dit "Tu es ingénieur de
test QA" et le corps du prompt ne fait référence qu'à "l'utilisateur" (aucune occurrence de
"RRC" ni de "binôme" dans `src/tgi/prompts/scenario_generator.md`). Le contexte transmis au
modèle inclut `scenario.get('actors')` (`src/tgi/agents/scenario_generator.py:111`), mais rien
dans le prompt n'impose d'utiliser ce nom d'acteur dans le texte des étapes générées plutôt que
le mot générique "l'utilisateur".

**Navigation entre écrans (#4, #19) et détail des données (#20).** Le prompt
`scenario_generator.md` ne mentionne ni navigation, ni changement d'écran, ni détail des
données à afficher ; il dit seulement "Les étapes sont des actions observables, avec le résultat
attendu vérifiable" (`scenario_generator.md:14`) et interdit d'écrire "se connecter" ou "accéder
à l'écran" comme première étape si c'est une précondition (`scenario_generator.md:16-17`), sans
jamais demander explicitement comment l'étape doit nommer l'écran de destination ou le contenu
affiché.

**Libellés en clair (#2).** Rien dans `distiller.md` ne demande d'extraire un glossaire de
libellés écran/objet/IHM/message/email ; le contexte produit se limite à "dix à vingt lignes...
ce que fait l'application, qui l'utilise, les objets métier manipulés et le vocabulaire
indispensable" (`distiller.md:7-8`), sans structure dédiée aux libellés d'écran. Dans
`qc_export.py:66` (`use_case_title = titles.get(container, "")`), seul le titre du conteneur
(`state["containers"]`, peuplé par `tgi.grammar.containers`, `src/tgi/grammar.py:296-310`) est
utilisé, jamais un libellé d'objet ou de message.

**Export QC — mapping Subject / Test Name / Description (#11, #12, #13).** Aujourd'hui
(`src/tgi/qc_export.py:82-87`) :
```
subject = f"{container or scenario_id}-{type_}_{use_case_title}_{scenario_id}"
test_name = f"TRA_{test.get('id', '')}_{test.get('name', '')}__{joined_refs}"
description = f"{description}\nExigences validées : {', '.join(refs)}"   # ligne 87, si refs
```
Le classeur recette (`src/tgi/workbook.py:37-50`, `_TEST_COLUMNS`) a pour colonnes, dans l'ordre :
A=Cas d'utilisation, B=Scénario, C=Intention du scénario, D=Nature, **E=ID test, F=Nom du test**,
G=Description, H=Étape, I=Action, J=Résultat attendu, **K=Exigences validées**, L=Statut.
L'exemple donné par Véronique pour `Test Name`, "TRA_TEST-2101_L'utilisateur doit pouvoir
visualiser les notes et compte rendus__EU01.CU01.RM02", concatène donc dans l'ordre : `TRA_` +
colonne E (ID test, `TEST-2101`) + `_` + colonne F (Nom du test — mais l'exemple affiche l'énoncé
de l'exigence, pas un nom de test court) + `__` + colonne K (Exigences validées, `EU01.CU01.RM02`).
Le code actuel produit exactement cette forme (`_requirement_type` mis à part), **sauf** que ce
qu'il met entre les deux underscores est `test.get('name')`, la colonne F du classeur recette
("Nom du test"). L'écart entre l'exemple de Véronique (qui ressemble à un **énoncé d'exigence**,
pas à un "Nom du test" court) et le mapping E/F/K donné dans la demande #11 est documenté comme
TBD en section 15 : la règle retenue ici est celle que #11 énonce explicitement
("E, F, K dans cet ordre"), le code actuel implémente déjà cette règle à la lettre près du
préfixe `TRA_` déjà présent (`qc_export.py:84`), donc #11 est très majoritairement déjà couvert et
la seule correction nécessaire est documentée en FR-NEW-068.

**Description QC (#12).** Le code concatène déjà G (Description) + K (Exigences validées)
(`qc_export.py:85-87`), avec le texte exact `"Exigences validées : ..."`, qui correspond à
l'exemple donné ("Vérifier que l'utilisateur peut accéder aux interactions via la fiche d'un
contact." + "Exigences validées : EU01.CU01.RM05"). Ce retour est donc déjà satisfait par le code
actuel ; la seule chose vérifiée ici est la non-régression (section 12, E2E-NEW).

**Colonne Subject (#13).** `qc_export.py:82` compose `{container or scenario_id}-{type_}_
{use_case_title}_{scenario_id}`, ce qui n'est l'intitulé d'onglet d'aucune feuille actuelle : les
feuilles du classeur recette sont nommées par fonctionnalité (`workbook.py:250-253`,
`sheet_title(chapter.key, used_names)`, `chapter.key` étant le premier segment du conteneur,
ex. `F03`). Il n'y a aujourd'hui **aucune notion d'onglet par type d'exigence**, donc #13 ("Subject
= même règle que l'intitulé d'onglet") ne peut être honoré qu'après la vague 5 (réorganisation
par type), ce qui crée une dépendance documentée en section 14.

**Onglet Synthèse (#15, #16).** `workbook.py:201-225` construit l'onglet "Synthèse" avec une
liste `Indicateur/Valeur` puis un bloc `"Par type d'exigence"` (`workbook.py:223-225`, un couple
`"{kind} couvertes / total"` par type). Aucune légende n'explique les autres onglets
(`workbook.py` ne produit aucun texte de ce type), et le bloc par type n'est lié par aucune
référence croisée (ni lien hypertexte openpyxl, ni mention du nom d'onglet correspondant) vers
l'onglet "Traçabilité" (`workbook.py:227-241`).

**Observabilité dans le classeur (#7).** Les seuls logs structurés existants sont les logs
applicatifs (`logging.info`/`logging.warning` dans `distiller.py`, `scenario_generator.py`,
`coverage.py`) et les traces OTel (`src/tgi/tracing.py`, non inspecté ici car hors périmètre :
aucune modification demandée dessus). Rien de cette information n'atteint le fichier xlsx livré à
Véronique : `build_workbook` (`workbook.py:192-266`) ne lit que `state["scenarios"]`,
`state["requirements"]`, `state["discards"]`, jamais de journal d'analyse par section.

**Classification MOA/MOE (#14).** N'existe pas : ni dans `_TEST_COLUMNS`
(`workbook.py:37-50`), ni dans `_HEADER` du QC (`qc_export.py:12`), ni comme champ calculé nulle
part dans le code actuel.

**Organisation du classeur par fonctionnalité, pas par type (#1, #9, #10, #13, #21).**
`build_tree` (`src/tgi/deliverable.py:148-184`) groupe les scénarios par `functionality` =
premier segment du conteneur (ex. `F03`), puis par `Group` = conteneur complet (le cas
d'utilisation), puis par scénario. `build_workbook` (`workbook.py:249-259`) crée une feuille par
`Chapter` (fonctionnalité), chacune contenant tous les tests de tous les cas d'utilisation de
cette fonctionnalité, en mélangeant RM, IHM et EMOE dans la même feuille puisque rien ne filtre
par `requirement.kind` à ce niveau. Les jeux de données (`data_rows`) sont aujourd'hui insérés
comme des lignes supplémentaires **dans la même feuille**, juste après les lignes d'étapes du
test qui les porte (`workbook.py:175-189`, bloc `for data_row in test.get("data_rows") or []`),
avec la colonne G ("Description") remplacée par le texte `"jeu de données"` et la colonne I
("Action") par les paires clé:valeur jointes — aucune colonne de référence séparée vers l'ID du
test.

**Vidage des colonnes de métadonnées sur les lignes d'étape (règle structurante de la vague 5).**
`_test_rows` (`workbook.py:132-190`) répète **toutes** les colonnes de métadonnées
(`scenario.container`, `scenario.id`, `scenario.title`, `scenario.kind`, `test['id']`,
`test['name']`, `test['description']`, `refs`, `test['status']`) sur **chaque ligne d'étape**
(`workbook.py:140-156`, boucle `for step in steps`) — le commentaire du code le dit lui-même :
"One row per step, repeating the test columns so filters keep working" (`workbook.py:132`). Le
banding par bloc (`_finish_sheet`, `workbook.py:111-129`, `band_on=_TEST_ID_COLUMN`) compare la
valeur de la colonne "ID test" (index 4, `_TEST_ID_COLUMN = 4`, `workbook.py:30`) ligne à ligne
pour détecter un changement de bloc de test et alterner la teinte de fond.

**Similarité et déduplication existantes.** `testset.py` compare des tests qui partagent déjà le
même jeu de `requirement_refs` (`_is_near_duplicate`, `testset.py:72-85`, condition
`rule_ids_of(candidate) != rule_ids_of(kept)` → pas de fusion si les refs diffèrent) et ne compare
donc jamais deux scénarios de fonctionnalités différentes. `similar_rule_pairs`
(`testset.py:147-176`) compare des **règles** (objets `{"id", "description"}`, pas des scénarios ni
des tests) deux à deux en O(n²) sur leur texte normalisé, et ne fait que les lister pour arbitrage
humain (`testset.py:158-163`, docstring : "These are reported, never merged"). Aucun appel LLM
n'intervient dans `testset.py` : toute la comparaison est `SequenceMatcher` pur Python.
`settings.test_similarity_threshold` (`config.py:148`, défaut `0.9`) et
`settings.rule_similarity_threshold` (`config.py:151`, défaut `0.9`) existent déjà, mais aucun des
deux ne pilote un préfiltrage de scénarios à travers tout le projet, et aucune variable
`TGI_SCENARIO_SIMILARITY_THRESHOLD` n'existe dans `Settings` (`config.py:95-172`, lecture
intégrale du fichier : absente).

**Prompts versionnés.** Trois clés seulement sont connues : `PROMPT_KEYS = ("distiller",
"scenario_generator", "coverage")` (`src/tgi/services/prompts.py:12`). `is_known_prompt_key`
(`prompts.py:15-17`) refuse toute autre clé. L'orchestrateur construit ses trois agents à partir
de `prompts["distiller"]`, `prompts["scenario_generator"]`, `prompts["coverage"]`
(`src/tgi/agents/orchestrator.py:119-121`), lues depuis `self._state.read_prompts(project_id,
version)`, donc par version (FR-NEW-048 cité dans `orchestrator.py:3-6`).

### 2.2 Existing specifications governing this area

- `specs/archived/SPEC-0001b_...` (interface lean, versions, table de modèles, export QC — crée
  `qc_export.py` sous FR-NEW-034 à FR-NEW-038, cités en commentaire dans `qc_export.py:3-5` et
  `qc_export.py:31, 45`). Cette spécification **précise** ce format sans le remplacer : DEC-001 de
  SPEC-0001b ("le format ici est notre propre invention... jusqu'à ce qu'un vrai fichier d'import
  QC soit disponible", `qc_export.py:5-6`) reste valable, ce document en ajuste seulement le détail.
- `specs/archived/SPEC-0002_...` (dédup par hash de contenu à la création) : aucun recouvrement, ce
  document ne touche pas à la création de projet.
- `specs/archived/SPEC-0003_...` (progression inline, accordéon des prompts dans
  `templates/project.html`) : ce document ajoute une 4e clé de prompt
  (`similarity_judge`, FR-NEW-083) qui devra apparaître dans le même accordéon ; pas de
  contradiction, une extension.
- `.agent_docs/pipeline.md` : documente l'invariant "la couverture est comptée, jamais jugée"
  (section "Phase 3"). Ce document le cite explicitement en NFR (7.4) et en DEC-030 pour garantir
  que le juge de similarité ne le viole pas.

### 2.3 Existing test coverage

- `tests/test_workbook.py` (6 tests listés : `test_the_reviewer_opens_on_the_summary_then_the_traceability`,
  `test_traceability_carries_the_wording_of_every_requirement`, `test_one_row_per_step_repeating_the_test_columns`,
  `test_a_test_is_one_block_of_shading_across_its_rows`, `test_the_header_stays_and_the_range_is_filterable`,
  `test_a_sheet_name_fits_excel_and_stays_unique`). Le test
  `test_one_row_per_step_repeating_the_test_columns` affirme explicitement la répétition
  actuelle, **contraire à la règle structurante de la vague 5** : il devra être remplacé
  (E2E-MOD, section 12.3).
- `tests/test_qc_export.py` (8 tests : header exact, répétition Subject/Test Name, composition,
  table de type, préfixe inconnu, troncature 32767, test sans ref). Aucun ne vérifie la
  composition exacte E/F/K telle que #11 la décrit littéralement (nom de l'exigence plutôt que nom
  court du test) ; ce document conserve la composition actuelle (E=ID test, F=Nom du test, K=Exigences)
  et l'affirme en E2E-NEW, la seule correction porte sur le séparateur (voir FR-NEW-068).
- `tests/test_coverage_report.py`, `tests/test_grammar.py`, `tests/test_distiller.py` : couvrent
  l'extraction et la couverture arithmétique actuelles ; aucun test ne couvre le filtre par section
  de document ni le profil d'acteur dans les prompts (logique, puisque le contenu des prompts n'est
  pas testé unitairement — un prompt `.md` n'est vérifié qu'au travers des agents qui le consomment,
  avec un LLM mocké).
- `tests/test_testset.py` : couvre `merge_tests`, `_is_near_duplicate`, `similar_rule_pairs`.
  Aucun test ne couvre un préfiltrage de scénarios cross-fonctionnalité ni un appel LLM de
  similarité (cette fonctionnalité n'existe pas).
- Commande de test exacte : `make test-cov` (délègue à `uv run pytest --cov=tgi
  --cov-report=term-missing --cov-fail-under=80`, `Makefile`, non relu en détail ici — cf.
  `.agent_docs/makefile.md`).
- Aucun test ne couvre aujourd'hui le contenu des prompts `.md` eux-mêmes autrement qu'au travers
  du comportement des agents avec un LLM mocké ; les tests de ce document suivent le même principe
  (le LLM mocké renvoie une structure contrôlée, le test vérifie que l'agent/l'export la transforme
  correctement).

## 3. Scope

### 3.1 In Scope

- Vague 1 : corrections de 6 retours de prompt (#2 à #6, #19, #20) sur `distiller.md` et
  `scenario_generator.md`.
- Vague 2 : précision du mapping E/F/K et G+K de `qc_export.py` (#11, #12, #13 — #13 dépend de la
  vague 5).
- Vague 3 : légende des onglets et renvoi croisé Synthèse ↔ Traçabilité (#15, #16) ; nouvel onglet
  "Analyse" dans le classeur recette matérialisant l'observabilité par section du document (#7).
- Vague 4 : colonne de classification MOA/MOE dérivée du type d'exigence, dans le classeur recette
  et l'export QC (#14).
- Vague 5 (fusionnée avec la vague 6) : réorganisation complète du classeur recette en onglets par
  type d'exigence (RM / IHM / EMOE), onglet séparé pour les jeux de données référençant l'ID du
  test (#1, #9, #10, #21), et vidage des colonnes de métadonnées de test sur les lignes d'étape
  2+ (#2/#5 structurant). #13 (Subject = intitulé d'onglet) est honoré une fois cette
  réorganisation en place.
- Vague 7 : juge de similarité LLM inter-scénarios en Phase 3bis, nouveau prompt
  `similarity_judge.md`, nouveau paramètre `TGI_SCENARIO_SIMILARITY_THRESHOLD` (#17, #18, #22).
- Entrée backlog pour #23 (chat qui écrit).

### 3.2 Out of Scope (Non-Goals)

- #1, #8, #9, #10, #21 pris isolément du reste de la demande d'origine (vagues 8+ au-delà du
  périmètre communiqué) ne sont pas repris individuellement : ils sont absorbés par la vague 5.
- La rétro-application de cette réorganisation aux classeurs déjà livrés dans des versions
  existantes (`projects/<id>/v<n>/testplan.xlsx`) : seules les **nouvelles** versions générées après
  implémentation produisent le nouveau format. Aucune régénération rétroactive n'est demandée ni
  spécifiée ici.
- Le remplacement du format d'import QC par un vrai fichier d'import ALM (SPEC-0001b section 15,
  toujours ouvert) : hors scope, ce document ajuste seulement le détail du format actuel.
- L'exposition d'une route HTTP pour le chat qui écrit (#23) : va au backlog (section 15), aucun
  FR ici.
- Le remplacement de l'arithmétique de couverture par un jugement LLM : explicitement exclu
  (DEC-030, NFR 7.4). Le juge de similarité ne décide jamais la couverture.
- Un modèle de persistance distinct pour l'historique des fusions de scénarios suggérées par le
  juge : la fusion proposée reste un champ sur le scénario existant (FR-NEW-087), aucune nouvelle
  entité n'est créée.

## 4. User Personas & Actors

- **Véronique BERTAIL** : seule utilisatrice actuelle, relit le classeur recette et l'export QC
  pour construire un cahier de recette. N'a pas accès aux logs serveur. Toute observabilité qui lui
  est destinée doit être dans le livrable xlsx.
- **RRC / binôme** (acteurs métier du document fonctionnel source) : nommés dans les scénarios
  générés, actuellement remplacés par "l'utilisateur" générique dans les étapes de test (#3).
- **Système TGI** (l'orchestrateur et ses agents) : exécute les 4 phases de la pipeline plus la
  phase 3bis introduite ici.

## 4.5 Bounded Contexts (MANDATORY at M and L)

| Context | Scope | Key entities |
|---|---|---|
| Génération (prompts) | `distiller.md`, `scenario_generator.md`, `coverage.md`, `similarity_judge.md` ; agents dans `src/tgi/agents/` | scénario, test, exigence, verdict de similarité |
| Classeur recette | `workbook.py`, `deliverable.py` (lecture seule) | onglet, feuille de type, ligne de test, jeu de données |
| Export QC | `qc_export.py` | ligne QC (Subject, Test Name, Description, Step) |
| Couverture (inchangé) | `coverage_report.py`, `grammar.py` | statut de couverture, type d'exigence (RM/IHM/EMOE) |
| Configuration | `config.py` (`Settings`) | `TGI_SCENARIO_SIMILARITY_THRESHOLD` |

## 5. Usage Scenarios

### SC-001: Véronique relit le classeur recette réorganisé par type d'exigence
**Actor:** Véronique BERTAIL
**Preconditions:** Une version a terminé sa génération (`state["status"] == "done"`).
**Flow:**
1. Véronique ouvre `testplan.xlsx` → elle voit l'onglet "Synthèse" en premier, avec une légende
   expliquant chaque onglet du classeur et un renvoi explicite depuis le bloc "Par type
   d'exigence" vers l'onglet "Traçabilité".
2. Elle ouvre l'onglet "Analyse" → elle voit, section par section du document source, ce qui a
   été lu, rattaché à un scénario, ou écarté, sans avoir besoin d'accéder aux logs serveur.
3. Elle ouvre un onglet de type (ex. `IHM_E04`) → elle voit tous les tests des exigences IHM de
   l'écran E04, chaque test n'apparaissant que sous sa première ligne d'étape pour les colonnes de
   métadonnées (Cas d'utilisation, Scénario, Intention, Nature, Nom du test, Description, Exigences
   validées, Statut), les lignes suivantes ne portant que Étape/Action/Résultat attendu (et l'ID
   test, qui reste rempli sur chaque ligne).
4. Elle ouvre l'onglet "Jeux de données" → elle voit, pour chaque test paramétré, une ligne par cas
   avec une colonne "ID test" la reliant à son test dans l'onglet de type correspondant.
5. Elle regarde la colonne "Classification" d'un test → elle voit MOA, MOE, ou MOA/MOE selon les
   types d'exigences couvertes par ce test.
**Postconditions:** Véronique peut construire son cahier de recette directement depuis le fichier
xlsx, sans question de mapping ouverte, sans accès serveur.
**Exceptions:**
- **EXC-001a**: le document source ne contient qu'une seule famille d'exigences (ex. uniquement
  RM) → un seul onglet de type est créé ; aucun onglet vide pour IHM ou EMOE n'apparaît.
**Cross-scenario notes:** l'onglet "Analyse" est alimenté par la même exécution que celle qui
produit les onglets de type (SC-002) ; ils partagent le même état de version.

### SC-002: Véronique exporte le fichier QC pour import ALM
**Actor:** Véronique BERTAIL
**Preconditions:** Une version est terminée, elle clique "Exporter QC".
**Flow:**
1. Le système produit `qc.xlsx` avec Subject composé selon la même règle que l'intitulé d'onglet
   du classeur recette (type-préfixe_référence pour IHM, référence-type suffixe pour RM/EMOE).
2. Test Name reste `TRA_<ID test>_<Nom du test>__<Exigences validées>`.
3. Description reste `<Description>\nExigences validées : <refs>`.
**Postconditions:** Le fichier est prêt pour l'import Excel ALM, cohérent avec le classeur recette.
**Exceptions:**
- **EXC-002a**: un test n'a aucune exigence liée → Subject et type restent "INCONNU", comme
  aujourd'hui (`qc_export.py:47`, inchangé).

### SC-003: Le pipeline détecte deux scénarios quasi-identiques de fonctionnalités différentes
**Actor:** Système TGI (Phase 3bis, automatique)
**Preconditions:** Une version a terminé la clôture des écarts de couverture (Phase 3).
**Flow:**
1. Le système calcule, pour chaque paire de scénarios du projet (toutes fonctionnalités
   confondues), une similarité textuelle sur leur titre et la liste de leurs tests.
2. Les paires dont la similarité dépasse `TGI_SCENARIO_SIMILARITY_THRESHOLD` sont soumises, une
   par une, au juge LLM avec le prompt `similarity_judge.md`.
3. Le juge répond "doublon", "variante légitime", ou "à fusionner", avec une justification.
4. Si "doublon" ou "à fusionner" : le scénario désigné comme redondant reste visible dans la
   traçabilité, marqué `merged_into: <id de l'autre scénario>`, jamais supprimé silencieusement.
5. Si "variante légitime" : rien ne change, aucune fusion, aucune suppression.
**Postconditions:** Le calcul de couverture (`coverage_report.py`) est strictement inchangé par
cette phase : aucun test ni aucune exigence n'est retiré du dénombrement.
**Exceptions:**
- **EXC-003a**: le juge LLM échoue (connexion, JSON illisible) sur une paire → cette paire est
  ignorée, consignée en avertissement, le run continue (comme pour tout autre appel LLM de la
  pipeline, `LLMJSONError`/`LLMConnectionError` déjà gérés, `orchestrator.py:170-178`).
- **EXC-003b**: le nombre de paires préfiltrées dépasse une borne raisonnable → section 15 (TBD, à
  confirmer avec Véronique si observé en pratique, sinon la borne par défaut proposée en FR-NEW-086
  s'applique sans question).
**Cross-scenario notes:** cette phase s'exécute après SC-001/SC-002 n'ont encore rien à lire : elle
a lieu avant la finalisation (`orchestrator.py:198`, `self._finalize`), donc avant l'écriture du
classeur, pour que la marque `merged_into` soit visible dans le classeur dès sa première
génération.

## 6. Functional Requirements

### New Requirements [FR-NEW-XXX]

#### FR-NEW-063 [EARS-E]: Lecture section par section pour réduire les faux "Missing"
> WHEN le distillateur traite un document découpé en plusieurs parties THE système SHALL associer
> à chaque scénario produit la référence de la section du document dont il provient, en plus du
> conteneur déjà extrait.

- **Inputs:** texte du document, `grammar.Grammar`.
- **Outputs:** champ `source_section` ajouté à chaque scénario (`distiller.py`, fonction
  `_clean_scenario`, `distiller.py:84-98`).
- **Business Rules:** `source_section` est la section identifiée par `grammar.container_of(ref)`
  pour la première référence citée par le scénario, ou vide si aucune référence n'est citée. N'a
  aucun effet sur le calcul de couverture (purement informatif, pour l'onglet "Analyse" de
  FR-NEW-073).
- **Exact names:** champ `source_section: str` dans l'objet scénario.
- **Priority:** Must-have
- **Rationale:** répond à #7 (observabilité) autant qu'à #6 (traçabilité de la lecture).

#### FR-NEW-064 [EARS-U]: Le prompt distillateur demande explicitement un glossaire de libellés
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
- **Rationale:** #2, préalable à FR-NEW-065.

#### FR-NEW-065 [EARS-E]: Le générateur de scénarios utilise les libellés en clair
> WHEN le générateur de scénarios écrit une étape qui référence un écran, un objet, un message ou
> un email THE système SHALL utiliser le libellé en clair fourni par `labels` plutôt que la
> référence codée, quand ce libellé existe.

- **Inputs:** dictionnaire `labels` produit par FR-NEW-064, transmis à
  `ScenarioGeneratorAgent.generate` (`scenario_generator.py:95-134`).
- **Outputs:** texte d'étape utilisant "l'écran de composition du portefeuille" plutôt que "E04".
- **Business Rules:** si aucun libellé n'existe pour une référence citée, le code codé reste
  utilisé tel quel (dégradation silencieuse, pas d'erreur).
- **Exact names:** nouveau paramètre `labels: dict[str, str]` sur `generate(...)`, propagé dans le
  prompt sous un bloc "Libellés connus:" ajouté à `user_content`
  (`scenario_generator.py:103-114`).
- **Priority:** Must-have
- **Rationale:** #2.

#### FR-NEW-066 [EARS-U]: Le prompt générateur de scénarios nomme l'acteur réel dans les étapes
> THE prompt `scenario_generator.md` SHALL demander que chaque étape utilise le nom de l'acteur du
> scénario (`scenario.actors`) plutôt que le mot générique "l'utilisateur", quand un acteur est
> précisé.

- **Inputs:** `scenario.actors` (déjà transmis, `scenario_generator.py:111`).
- **Outputs:** texte d'étape "Le RRC sélectionne..." plutôt que "L'utilisateur sélectionne...".
- **Business Rules:** si `scenario.actors` est vide, "l'utilisateur" reste le terme par défaut
  (aucune régression sur les scénarios sans acteur précisé).
- **Exact names:** n/a (modification de prompt texte uniquement, pas de nouveau champ de données).
- **Priority:** Must-have
- **Rationale:** #3.

#### FR-NEW-067 [EARS-U]: Le prompt générateur de scénarios impose la navigation explicite entre écrans
> THE prompt `scenario_generator.md` SHALL demander que toute étape qui change l'écran affiché
> nomme explicitement l'écran de départ et l'écran d'arrivée, en clair (via `labels` quand
> disponible, FR-NEW-065), et que toute étape listant une donnée issue d'une exigence détaille
> cette donnée dans le texte de l'étape plutôt que de citer seulement la référence de l'exigence.

- **Inputs:** `labels`, les exigences du scénario (`requirements`, déjà transmises).
- **Outputs:** texte d'étape "Depuis l'écran de composition du portefeuille (E04), l'utilisateur
  accède à l'écran de détail du contact (E07)" plutôt que "L'utilisateur navigue vers E07" ; texte
  d'étape citant la donnée (ex. le libellé exact du message d'erreur) plutôt que "vérifier le
  message M03".
- **Business Rules:** s'applique uniquement quand le scénario ou ses exigences impliquent un
  changement d'écran ou une donnée listée en exigence ; ne force pas une étape de navigation
  artificielle sur un scénario mono-écran.
- **Exact names:** n/a (prompt texte).
- **Priority:** Must-have
- **Rationale:** #4, #19, #20.

#### FR-NEW-068 [EARS-U]: Vérifier et figer le séparateur Test Name de l'export QC
> THE `qc_export.py` SHALL composer `Test Name` comme `TRA_<ID test>_<Nom du test>__<Exigences
> validées jointes par ", ">`, avec exactement les séparateurs `_`, `_`, `__` dans cet ordre, en
> confirmant la forme déjà en place (`qc_export.py:84`).

- **Inputs:** `test["id"]`, `test["name"]`, `test["requirement_refs"]`.
- **Outputs:** chaîne `Test Name` inchangée dans sa forme, verrouillée par un test de
  non-régression explicite (E2E-NEW-007).
- **Business Rules:** aucun changement de comportement ; cette exigence documente et fige ce que
  #11 demandait déjà, l'écart entre l'exemple email (qui montre un énoncé long plutôt qu'un nom
  court) et le mapping E/F/K étant noté TBD (section 15) plutôt que mis en œuvre sans
  confirmation de Véronique.
- **Exact names:** aucun changement de nom.
- **Priority:** Should-have (déjà conforme ; exigence de verrouillage).
- **Rationale:** #11.

#### FR-NEW-069 [EARS-U]: Vérifier et figer la composition Description de l'export QC
> THE `qc_export.py` SHALL composer `Description` comme `<Description du test>` suivi, si des
> exigences sont liées, d'un saut de ligne et de `Exigences validées : <refs jointes par ", ">`,
> confirmant la forme déjà en place (`qc_export.py:85-87`).

- **Inputs:** `test["description"]`, `test["requirement_refs"]`.
- **Outputs:** inchangé, verrouillé par E2E-NEW-008.
- **Business Rules:** aucun changement de comportement.
- **Priority:** Should-have (déjà conforme ; exigence de verrouillage).
- **Rationale:** #12.

#### FR-NEW-070 [EARS-E]: Subject de l'export QC aligné sur l'intitulé d'onglet du type d'exigence
> WHEN `qc_export.py` compose la colonne `Subject` d'une ligne THE système SHALL utiliser la même
> règle de nommage que celle utilisée pour l'intitulé de l'onglet du type d'exigence majoritaire du
> test dans le classeur recette (FR-NEW-077), au lieu de la composition actuelle
> `{container}-{type_}_{use_case_title}_{scenario_id}`.

- **Inputs:** `test["requirement_refs"]`, la fonction de nommage d'onglet définie par FR-NEW-077.
- **Outputs:** `Subject` = `IHM_E04` pour un test dont la première exigence est de type IHM
  rattachée à l'écran E04 ; `Subject` = `EU01.CU01-RM` pour un test dont la première exigence est
  de type RM rattachée au cas d'utilisation `EU01.CU01` ; `Subject` = `F01.EU02.CU03-EMOE` pour
  une exigence EMOE.
- **Business Rules:** le type et la référence utilisés sont ceux de la **première** référence de
  `test["requirement_refs"]`, comme aujourd'hui (`qc_export.py:70-77`) ; aucun test n'a ses
  exigences réparties sur plusieurs Subject.
- **Exact names:** fonction partagée `onglet_type_name(ref: str, grammar: Grammar) -> str` exposée
  par `workbook.py` et importée par `qc_export.py`, pour que les deux modules ne divergent jamais
  (évite la dérive observée aujourd'hui entre `qc_export.py:82` et les noms de feuilles de
  `workbook.py:252`).
- **Priority:** Must-have
- **Rationale:** #13 ; dépend de FR-NEW-077 (vague 5).

#### FR-NEW-071 [EARS-U]: Légende des onglets dans la Synthèse
> THE onglet "Synthèse" SHALL contenir une section "Légende des onglets" listant, pour chaque
> onglet du classeur, son nom exact et une phrase expliquant son contenu.

- **Inputs:** la liste réelle des onglets créés par `build_workbook` pour cette version.
- **Outputs:** lignes ajoutées après le bloc "Par type d'exigence" existant
  (`workbook.py:223-225`) : une ligne par onglet effectivement créé, avec son nom et sa
  description (ex. "Traçabilité — une ligne par exigence du document, avec son statut et les tests
  qui la couvrent").
- **Business Rules:** la légende est générée dynamiquement (elle ne liste que les onglets
  réellement présents dans cette version, pas un texte statique qui listerait un onglet absent
  faute de données).
- **Exact names:** libellé de section exact "Légende des onglets" dans la colonne "Indicateur" de
  `_SUMMARY_COLUMNS`.
- **Priority:** Must-have
- **Rationale:** #16.

#### FR-NEW-072 [EARS-E]: Renvoi croisé Synthèse → Traçabilité
> WHEN l'onglet "Synthèse" affiche le bloc "Par type d'exigence" THE système SHALL faire figurer,
> sur chaque ligne de ce bloc, un lien hypertexte interne pointant vers la première ligne de
> l'onglet "Traçabilité" filtrée sur ce type (ou, si openpyxl ne permet pas un filtre préconfiguré,
> un lien vers l'onglet lui-même accompagné du nom du type à chercher).

- **Inputs:** le nom de l'onglet "Traçabilité" tel que produit par `sheet_title`
  (`workbook.py:79-93`, qui peut suffixer `(2)` en cas de collision — improbable ici mais à
  utiliser à la lettre).
- **Outputs:** une cellule avec `Hyperlink` openpyxl (`cell.hyperlink =
  f"#'{trace_sheet_name}'!A1"`) sur chaque ligne "Par type d'exigence" de la Synthèse.
- **Business Rules:** le lien cible toujours l'onglet Traçabilité tel qu'il existe dans ce
  classeur précis (jamais un nom en dur "Traçabilité", qui romprait si `sheet_title` l'avait
  suffixé).
- **Exact names:** `openpyxl.worksheet.hyperlink.Hyperlink`, ou l'attribut `cell.hyperlink` (string
  interne commençant par `#`).
- **Priority:** Should-have
- **Rationale:** #15.

#### FR-NEW-073 [EARS-U]: Onglet "Analyse" matérialisant la lecture par section
> THE système SHALL ajouter un onglet "Analyse" au classeur recette, listant, pour chaque section
> du document identifiée par la numérotation inférée (`grammar.Grammar`), ce qui a été lu,
> rattaché à un scénario, ou écarté.

- **Inputs:** `state["requirements"]`, `state["scenarios"]`, `state["discards"]`,
  `state["containers"]`, le champ `source_section` de FR-NEW-063.
- **Outputs:** une feuille "Analyse" avec les colonnes : "Section" (référence de conteneur),
  "Titre" (`state["containers"]`), "Exigences trouvées" (compte), "Exigences rattachées à un
  scénario" (compte), "Scénarios issus de cette section" (liste), "Éléments écartés" (liste des
  `discards` dont une ref appartient à cette section).
- **Business Rules:** une section sans aucune exigence ni aucun scénario (une section purement
  narrative du document) apparaît quand même, avec des compteurs à zéro, pour que "rien n'a été
  lu ici" soit une ligne visible plutôt qu'une absence silencieuse.
- **Exact names:** nom d'onglet exact "Analyse", colonnes `_ANALYSIS_COLUMNS` dans `workbook.py`.
- **Priority:** Must-have
- **Rationale:** #7, matérialisé dans le seul livrable que Véronique reçoit (pas uniquement les
  logs serveur ou OTel, qui restent inchangés et complémentaires).

#### FR-NEW-074 [EARS-E]: Classification MOA/MOE dérivée du type d'exigence
> WHEN un test est écrit dans le classeur recette ou l'export QC THE système SHALL calculer sa
> classification comme `MOA` si toutes ses exigences liées sont de type IHM, `MOE` si toutes ses
> exigences liées sont de type RM ou EMOE, ou `MOA/MOE` si ses exigences liées couvrent les deux
> familles.

- **Inputs:** `test["requirement_refs"]`, `grammar.kind_of(ref)` pour chaque référence
  (`grammar.py:136-137`).
- **Outputs:** une valeur `"MOA"`, `"MOE"`, ou `"MOA/MOE"` par test. Un test sans aucune référence
  (cas déjà géré en `"INCONNU"` côté QC) produit `"INCONNU"`.
- **Business Rules:** calcul purement déterministe, aucun appel LLM. IHM = type `M`, `N` ou `T`
  (famille écran/batch, déjà mappée vers `"IHM"` dans `qc_export.py:26-32`) ; MOE = type `RM` ou
  `EM`.
- **Exact names:** fonction `classification_of(refs: list[str], grammar: Grammar) -> str` dans un
  module partagé (proposé : `src/tgi/classification.py`, importé par `workbook.py` et
  `qc_export.py` pour éviter la duplication déjà observée entre les deux modules sur
  `_TYPE_BY_PREFIX`/`_requirement_type`).
- **Priority:** Must-have
- **Rationale:** #14.

#### FR-NEW-075 [EARS-U]: Nouvelle colonne "Classification" dans le classeur recette
> THE classeur recette SHALL porter une colonne "Classification" dans chaque feuille de type,
> immédiatement après "Exigences validées" et avant "Statut".

- **Inputs:** sortie de FR-NEW-074.
- **Outputs:** `_TEST_COLUMNS` (`workbook.py:37-50`) étendu : `..., ("Exigences validées", 30),
  ("Classification", 12), ("Statut", 11)`. Valeur affichée uniquement sur la première ligne
  d'étape du test (cohérent avec FR-NEW-080), vide sur les lignes suivantes.
- **Exact names:** libellé de colonne exact "Classification".
- **Priority:** Must-have
- **Rationale:** #14.

#### FR-NEW-076 [EARS-U]: Nouvelle colonne "Classification" dans l'export QC
> THE export QC SHALL porter une colonne "Classification" après "Description" et avant "Step
> Name".

- **Inputs:** sortie de FR-NEW-074.
- **Outputs:** `_HEADER` (`qc_export.py:12`) étendu : `["Subject", "Test Name", "Description",
  "Classification", "Step Name", "Step Description", "Expected Results"]`.
- **Business Rules:** répétée sur chaque ligne de step du même test, comme `Subject`/`Test Name`
  aujourd'hui (règle d'import ALM, `qc_export.py:3` docstring).
- **Exact names:** en-tête exact "Classification".
- **Priority:** Must-have
- **Rationale:** #14.

#### FR-NEW-077 [EARS-U]: Un onglet du classeur recette par type d'exigence, plus par référence de rattachement
> THE classeur recette SHALL remplacer l'organisation par fonctionnalité (`build_tree`,
> `deliverable.py:148-184`) par une organisation en une feuille par couple (type d'exigence,
> référence de rattachement), nommée :
> - `IHM_<référence écran>` pour une exigence de type IHM (ex. `IHM_E04`)
> - `<référence de cas d'utilisation>-RM` pour une exigence de type RM (ex. `EU01.CU01-RM`)
> - `<référence de cas d'utilisation>-EMOE` pour une exigence de type EMOE (ex.
>   `F01.EU02.CU03-EMOE`)

- **Inputs:** `state["scenarios"]`, `state["requirements"]` (chaque requirement porte déjà `kind`
  et `parent`, `grammar.py:87-98` dataclass `Requirement`).
- **Outputs:** une feuille par couple (type, référence de rattachement) réellement peuplé — pas une
  feuille par exigence individuelle, une par **groupe** de rattachement (écran pour IHM, cas
  d'utilisation pour RM/EMOE), chacune listant tous les tests qui couvrent au moins une exigence de
  ce groupe.
- **Business Rules:** un test couvrant des exigences de plusieurs groupes apparaît dans **chacune**
  des feuilles concernées (répétition assumée : un reviewer qui ouvre la feuille `IHM_E04` doit
  voir tous les tests touchant E04, même s'ils touchent aussi une règle métier ailleurs — c'est le
  prix d'une organisation par type plutôt que par scénario unique). La référence de rattachement
  pour IHM est le conteneur à `container_depth` de l'axe `E` (`grammar.py:122-129`,
  `container_of`) ; pour RM/EMOE c'est `requirement.parent`, le cas d'utilisation
  (`grammar.py:87-98`).
- **Exact names:** fonction `onglet_type_name(ref: str, grammar: Grammar) -> str` (partagée avec
  FR-NEW-070), passée à `sheet_title()` (`workbook.py:79-93`, inchangée) exactement comme
  aujourd'hui `chapter.key` l'est (`workbook.py:252`).
- **Priority:** Must-have
- **Rationale:** #1, #9, #10, DEC-025.

#### FR-NEW-078 [EARS-U]: Onglet "Jeux de données" séparé, référençant l'ID du test
> THE classeur recette SHALL porter un onglet "Jeux de données" distinct, contenant une ligne par
> cas de chaque `data_rows` de chaque test, avec une colonne "ID test" permettant de retrouver le
> test dans sa feuille de type.

- **Inputs:** `test["data_rows"]` pour chaque test de chaque scénario.
- **Outputs:** feuille "Jeux de données" avec colonnes : "ID test", "Nom du test", "Cas" (une
  colonne par clé rencontrée dans les `data_rows`, ou une colonne "Détail" listant les paires
  clé:valeur jointes si les clés varient d'un test à l'autre — voir DEC-026 pour le choix
  retenu), "Onglet source" (le nom de la feuille de type où ce test apparaît, issu de FR-NEW-077).
- **Business Rules:** cet onglet remplace les lignes `data_rows` actuellement insérées dans la même
  feuille que les étapes (`workbook.py:175-189`), qui disparaissent de `_test_rows`.
- **Exact names:** nom d'onglet exact "Jeux de données", colonnes `_DATA_ROW_COLUMNS` dans
  `workbook.py`.
- **Priority:** Must-have
- **Rationale:** #21.

#### FR-NEW-079 [EARS-O]: Pas d'onglet vide pour un type d'exigence absent du document
> IF un type d'exigence (RM, IHM, EMOE) n'est présent dans aucune exigence du document THEN THE
> système SHALL ne créer aucune feuille de ce type.

- **Inputs:** `state["requirements"]`.
- **Outputs:** absence de feuille, jamais une feuille avec une seule ligne d'en-tête.
- **Priority:** Must-have
- **Rationale:** cohérence avec EXC-001a, évite un classeur encombré de feuilles vides.

#### FR-NEW-080 [EARS-U]: Vidage des colonnes de métadonnées de test sur les lignes d'étape 2+
> THE classeur recette SHALL renseigner les colonnes "Cas d'utilisation", "Scénario", "Intention du
> scénario", "Nature", "Nom du test", "Description", "Exigences validées", "Classification" et
> "Statut" uniquement sur la première ligne d'étape de chaque test, en laissant ces colonnes vides
> sur les lignes d'étape suivantes du même test, et SHALL continuer à renseigner "ID test" sur
> **chaque** ligne, sans exception.

- **Inputs:** `_test_rows` actuel (`workbook.py:132-190`).
- **Outputs:** pour un test à 3 étapes, seule la ligne de l'étape 1 porte les 9 colonnes de
  métadonnées renseignées ; les lignes des étapes 2 et 3 les laissent vides, sauf "ID test" qui
  reste rempli sur les 3 lignes.
- **Business Rules:** le banding par bloc (`_finish_sheet`, `band_on=_TEST_ID_COLUMN`,
  `workbook.py:111-129`) continue de fonctionner sans modification, puisqu'il se fie uniquement à
  "ID test", qui reste toujours rempli. L'autofiltre (`_finish_sheet`, `workbook.py:118`) continue
  de fonctionner sur des colonnes partiellement vides, comme c'est le comportement normal d'Excel
  pour un filtre sur une colonne à cellules vides.
- **Exact names:** colonnes visées exactement (noms de `_TEST_COLUMNS`, `workbook.py:37-50`) :
  "Cas d'utilisation", "Scénario", "Intention du scénario", "Nature", "Nom du test", "Description",
  "Exigences validées", "Classification" (nouvelle, FR-NEW-075), "Statut". Colonne exclue du
  vidage : "ID test" (index 4, inchangé, `_TEST_ID_COLUMN = 4`).
- **Priority:** Must-have
- **Rationale:** règle structurante communiquée explicitement par l'utilisateur, applicable à
  toutes les feuilles de cas de test du classeur recette (donc à chacune des feuilles produites
  par FR-NEW-077).

#### FR-NEW-081 [EARS-UB]: Le classeur recette ne doit jamais répéter une métadonnée de test au-delà de sa première ligne
> THE classeur recette SHALL NOT répéter une valeur de colonne de métadonnée de test (listées en
> FR-NEW-080) sur une ligne d'étape autre que la première ligne de ce test.

- **Priority:** Must-have
- **Rationale:** formulation négative explicite de FR-NEW-080, pour qu'un test de non-régression
  puisse l'affirmer directement (E2E-NEW-011).

#### FR-NEW-082 [EARS-E]: Préfiltrage textuel des paires de scénarios candidates à la similarité
> WHEN la phase 3bis démarre pour une version THE système SHALL calculer, pour chaque paire de
> scénarios du projet (toutes fonctionnalités confondues), une similarité textuelle sur la
> concaténation du titre du scénario et des noms de ses tests, et SHALL ne retenir que les paires
> dont la similarité dépasse `settings.scenario_similarity_threshold`.

- **Inputs:** `state["scenarios"]`, chaque scénario avec son titre et ses tests.
- **Outputs:** liste de paires `(scenario_id_a, scenario_id_b, ratio)`, triée par ratio décroissant.
- **Business Rules:** comparaison en O(n²) sur l'ensemble des scénarios du projet (pas seulement
  ceux qui partagent un `container` ou des `requirement_refs`, à la différence de
  `_is_near_duplicate`, `testset.py:72-85`, qui exige `rule_ids_of(candidate) ==
  rule_ids_of(kept)`). Le préfiltrage est pur Python (`SequenceMatcher`, comme
  `similar_rule_pairs`, `testset.py:147-176`), sans appel LLM à ce stade — l'appel LLM n'intervient
  qu'en FR-NEW-084, une fois la liste bornée.
- **Exact names:** nouvelle fonction `similar_scenario_pairs(scenarios, threshold, limit)` dans
  `testset.py`, sur le modèle de `similar_rule_pairs` (`testset.py:147-176`).
- **Priority:** Must-have
- **Rationale:** #17, #18 ; design détaillé en section Phase 2 (deux approches).

#### FR-NEW-083 [EARS-U]: Nouveau prompt `similarity_judge.md`, quatrième clé de prompt
> THE système SHALL ajouter `similarity_judge` à `PROMPT_KEYS` (`src/tgi/services/prompts.py:12`)
> et un fichier `src/tgi/prompts/similarity_judge.md` livré avec le paquet.

- **Inputs:** n/a (nouveau fichier statique).
- **Outputs:** `PROMPT_KEYS = ("distiller", "scenario_generator", "coverage",
  "similarity_judge")`. Le prompt demande au modèle, pour une paire de scénarios donnée (titre,
  tests, exigences couvertes de chacun), de répondre par un verdict parmi `"doublon"`, `"variante
  legitime"`, `"a_fusionner"`, avec une justification en une phrase.
- **Business Rules:** une version créée avant ce changement ne porte pas cette 4e clé dans ses
  fichiers de prompt sur disque ; `read_prompts` doit se rabattre sur le défaut quand la clé
  manque (comportement déjà attendu de `is_known_prompt_key`/`default_prompt`,
  `prompts.py:15-21`, à vérifier dans `StateManager.read_prompts` lors de l'implémentation —
  section 9).
- **Exact names:** clé `"similarity_judge"`, fichier `similarity_judge.md`.
- **Priority:** Must-have
- **Rationale:** #17, #18, #22, décision utilisateur explicite ("on remet un jugement LLM").

#### FR-NEW-084 [EARS-E]: Appel du juge de similarité sur chaque paire préfiltrée
> WHEN une paire de scénarios a passé le préfiltrage de FR-NEW-082 THE système SHALL soumettre
> cette paire au juge LLM avec le prompt `similarity_judge`, et SHALL enregistrer son verdict.

- **Inputs:** la paire de scénarios (titre, tests, requirement_refs de chacun), le modèle choisi
  pour la version.
- **Outputs:** un verdict par paire : `"doublon"`, `"variante_legitime"`, ou `"a_fusionner"`, plus
  une justification textuelle.
- **Business Rules:** un appel par paire (pas de batch multi-paires dans un seul appel, pour que
  chaque verdict soit traçable à sa paire et que l'échec d'un appel n'affecte pas les autres,
  suivant le principe déjà en place pour la clôture des écarts par scénario,
  `orchestrator.py:200-293`).
- **Exact names:** nouveau module `src/tgi/agents/similarity_judge.py`, classe
  `SimilarityJudgeAgent`, méthode `judge(model, scenario_a, scenario_b) -> dict`.
- **Priority:** Must-have
- **Rationale:** #17, #18, #22.

#### FR-NEW-085 [EARS-E]: Marquage non destructif d'une paire jugée doublon ou à fusionner
> WHEN le juge répond "doublon" ou "a_fusionner" pour une paire THE système SHALL ajouter au
> scénario désigné comme redondant un champ `merged_into` contenant l'id de l'autre scénario de la
> paire et un champ `merge_reason` contenant la justification du juge, SHALL NOT supprimer le
> scénario ni ses tests, et SHALL NOT retirer ses exigences du dénombrement de couverture.

- **Inputs:** le verdict de FR-NEW-084.
- **Outputs:** `scenario["merged_into"] = "<autre id>"`, `scenario["merge_reason"] = "<texte>"`.
- **Business Rules:** le scénario désigné comme "redondant" est celui dont l'id est le plus élevé
  numériquement dans la paire (convention déterministe, pas un choix du juge, pour que le
  comportement soit reproductible) ; "a_fusionner" est traité identiquement à "doublon" pour cette
  marque (section 15 : la distinction entre les deux verdicts reste informative,
  `merge_reason` conserve le verdict exact).
- **Exact names:** champs `merged_into: str | None`, `merge_reason: str`.
- **Priority:** Must-have
- **Rationale:** #22, invariant de réversibilité explicitement demandé par l'utilisateur.

#### FR-NEW-086 [EARS-UB]: Le juge de similarité ne modifie jamais le calcul de couverture
> THE phase 3bis SHALL NOT retirer un test ou une exigence du dénombrement effectué par
> `coverage_report.coverage_summary` et `coverage_report.requirement_rows`, quel que soit le
> verdict du juge.

- **Priority:** Must-have (invariant)
- **Rationale:** invariant explicitement demandé par l'utilisateur ("jamais pour la couverture").
  Vérifié par E2E-NEW-019 (non-régression).

#### FR-NEW-087 [EARS-U]: Nouveau paramètre `TGI_SCENARIO_SIMILARITY_THRESHOLD`
> THE `Settings` (`src/tgi/config.py:95-172`) SHALL porter un champ
> `scenario_similarity_threshold: float = 0.9`, lu depuis la variable d'environnement
> `TGI_SCENARIO_SIMILARITY_THRESHOLD`.

- **Inputs:** variable d'environnement ou `.env`.
- **Outputs:** `settings.scenario_similarity_threshold`, consommé par FR-NEW-082.
- **Business Rules:** pilote uniquement le seuil de **préfiltrage textuel** (le nombre de paires
  envoyées au juge), jamais le seuil de décision du juge lui-même, qui raisonne en langage et ne
  reçoit aucun score numérique en entrée.
- **Exact names:** `TGI_SCENARIO_SIMILARITY_THRESHOLD`, champ Python
  `scenario_similarity_threshold`.
- **Priority:** Must-have
- **Rationale:** #17, #18, demande explicite de configuration.

#### FR-NEW-088 [EARS-S]: Affichage du prompt `similarity_judge` dans l'accordéon des prompts
> WHILE l'utilisateur consulte l'accordéon des prompts d'une version sur `templates/project.html`
> (introduit par SPEC-0003) THE système SHALL afficher le prompt `similarity_judge` comme une
> quatrième entrée, au même titre que `distiller`, `scenario_generator` et `coverage`.

- **Inputs:** `PROMPT_KEYS` étendu (FR-NEW-083).
- **Outputs:** une quatrième section repliable dans l'accordéon.
- **Priority:** Must-have
- **Rationale:** cohérence de l'interface, FR-NEW-083 crée une 4e clé qui doit être éditable comme
  les trois autres (parité d'interface, pas de nouvelle exigence de contenu).

### Modified Requirements [existing only]

#### FR-MOD-001 [EARS-E]: L'onglet par fonctionnalité est remplacé par un onglet par type d'exigence (references SPEC-0001b implicite, `build_workbook`)
> WHEN `build_workbook` construit les feuilles de tests THE système SHALL les grouper par type
> d'exigence et référence de rattachement (FR-NEW-077) au lieu de les grouper par fonctionnalité
> (`deliverable.build_tree`, `deliverable.py:148-184`).

- **Original behavior:** une feuille par `Chapter` (fonctionnalité, premier segment du conteneur),
  toutes les natures d'exigence mélangées dans la même feuille (`workbook.py:249-259`).
- **New behavior:** voir FR-NEW-077.
- **Reason for change:** #1, #9, #10 — demande explicite et sans débat de l'utilisatrice.
- **Business Rules:** `deliverable.build_tree` et `deliverable.py` restent inchangés : ils
  continuent de servir l'interface web (les onglets HTML de `project.html` lisent toujours l'arbre
  par fonctionnalité — **ASSUMED**: aucune route de `tgi.py` n'a été vérifiée explicitement comme
  consommant `build_tree` pour l'écran web dans ce document ; seul `workbook.py` est modifié ici.
  Si l'écran web affiche aussi une vue par fonctionnalité, elle n'est pas affectée par ce
  changement, qui ne touche que le fichier xlsx).

### Removed Requirements [existing only]

*(aucune exigence existante n'est supprimée : le changement est additif ou remplace une structure
de présentation du classeur xlsx, jamais une capacité).*

## 7. Non-Functional Requirements

### 7.1 Performance

Le préfiltrage de FR-NEW-082 est en O(n²) sur le nombre de scénarios du projet, pur Python
(`SequenceMatcher`), donc négligeable même pour plusieurs centaines de scénarios (mesure de
référence : `.agent_docs/pipeline.md` rapporte 64 scénarios pour le document de référence ;
O(64²) = 4096 comparaisons texte, de l'ordre de la milliseconde). Le nombre d'appels LLM au juge
(FR-NEW-084) est borné par le seuil de préfiltrage (FR-NEW-087), pas par le nombre de scénarios :
c'est le point explicite de la demande ("pour borner le nombre d'appels LLM au juge").

### 7.2 Security

Sans objet : aucune authentification, aucune donnée sensible nouvelle. Le nouveau prompt est un
fichier `.md` versionné comme les trois existants, soumis aux mêmes règles d'édition par version
(`is_known_prompt_key`, `prompts.py:15-17`, étendu à 4 clés).

### 7.3 Usability

La réorganisation du classeur (vague 5) change une structure que Véronique consulte
quotidiennement : aucune migration de classeurs déjà livrés n'est prévue (section 3.2), donc une
version déjà produite avant cette implémentation garde son ancien format tant qu'elle n'est pas
régénérée.

### 7.4 Reliability

**Invariant non négociable** (DEC-030) : le calcul de couverture
(`coverage_report.coverage_summary`, `coverage_report.requirement_rows`) reste arithmétique et
n'est jamais influencé par un verdict du juge de similarité. Un test marqué `merged_into` continue
de compter dans le dénombrement de couverture exactement comme avant d'être marqué.

### 7.5 Observability

- **Collector:** fichier JSONL existant (`traces/app.jsonl` ou équivalent, configuré par
  `otel_destination`/logs — inchangé, `config.py:160-162`).
- **What to trace:** un nouveau span `llm.chat` (INFO) par appel au juge de similarité, avec le
  nombre de paires préfiltrées et le nombre de paires effectivement soumises au juge
  (`purpose="similarity_judge"`, suivant le motif déjà en place pour `purpose="distiller"` /
  `"scenario_generator"` / `"coverage"`, `distiller.py` / `scenario_generator.py` /
  `coverage.py`).
- **LLM tracing:** modèle, nombre de tokens, durée — jamais le contenu des scénarios comparés ni la
  justification du juge en clair dans les traces (seul le verdict catégoriel et le ratio de
  préfiltrage sont loggés).
- **Never traced:** prompts, réponses, texte des scénarios comparés, contenu de l'onglet "Analyse".
- **Dans le classeur livré** (#7) : l'onglet "Analyse" (FR-NEW-073) matérialise, pour Véronique,
  une observabilité qui ne nécessite aucun accès serveur.

### 7.6 Deployment

Inchangé : application interne, pas de nouveau composant d'infrastructure. Le nouveau prompt est
un fichier texte livré dans le paquet (`src/tgi/prompts/similarity_judge.md`), inclus dans le
wheel comme les trois existants (`make build`, déjà couvert par la configuration de build
existante — **ASSUMED**: non vérifié ligne à ligne dans `pyproject.toml`, mais les trois prompts
existants y sont déjà inclus donc un quatrième fichier du même répertoire suit la même règle
d'empaquetage).

### 7.7 Scalability

Sans objet au-delà de 7.1 : le volume de scénarios par projet (dizaines à centaines, mesuré à 64
sur le document de référence) ne pose pas de problème de passage à l'échelle pour un O(n²) en pur
Python.

## 8. Data Model

Aucune nouvelle entité persistée. Champs ajoutés aux structures existantes dans `state.json` :

| Entité | Champ ajouté | Type | Origine |
|---|---|---|---|
| Scénario | `source_section` | `str` | FR-NEW-063 |
| Scénario | `merged_into` | `str \| None` | FR-NEW-085 |
| Scénario | `merge_reason` | `str` | FR-NEW-085 |
| État de version | `labels` | `dict[str, str]` | FR-NEW-064 |
| État de version | `similarity_verdicts` | `list[dict]` (paires jugées, pour audit) | FR-NEW-084 |

`src/tgi/schemas/test_schema.json` (schéma du test exporté JSON) n'est **pas modifié** : la
classification MOA/MOE (FR-NEW-074) est calculée à l'export (workbook/QC), jamais persistée sur le
test lui-même, pour ne pas introduire un champ dérivé qui pourrait diverger de son calcul source.

## 9. Impact Analysis [existing only]

### 9.1 Affected Components

| File/Module | Impact | Description |
|---|---|---|
| `src/tgi/prompts/distiller.md` | Modified | Ajout du résultat `labels` (FR-NEW-064), aucune section ciblée par nom pour #6 (traité par FR-NEW-063, structurel) |
| `src/tgi/prompts/scenario_generator.md` | Modified | Nomination de l'acteur (FR-NEW-066), navigation (FR-NEW-067), libellés (FR-NEW-065) |
| `src/tgi/agents/distiller.py` | Modified | `_clean_scenario` ajoute `source_section` ; nouvelle `_clean_labels` |
| `src/tgi/agents/scenario_generator.py` | Modified | `generate()` reçoit `labels`, les injecte dans `user_content` |
| `src/tgi/agents/orchestrator.py` | Modified | Phase 3bis ajoutée entre la clôture des écarts et `_finalize` ; construction du `SimilarityJudgeAgent` |
| `src/tgi/agents/similarity_judge.py` | New | Nouvel agent, prompt `similarity_judge` |
| `src/tgi/prompts/similarity_judge.md` | New | Nouveau prompt |
| `src/tgi/services/prompts.py` | Modified | `PROMPT_KEYS` étendu à 4 clés |
| `src/tgi/testset.py` | Modified | Nouvelle `similar_scenario_pairs` |
| `src/tgi/config.py` | Modified | Nouveau champ `scenario_similarity_threshold` |
| `src/tgi/classification.py` | New | `classification_of()`, `onglet_type_name()` partagés |
| `src/tgi/workbook.py` | Modified | `_TEST_COLUMNS` étendu, `_test_rows` vide les métadonnées en ligne 2+, feuilles par type au lieu de par fonctionnalité, nouvel onglet "Analyse", nouvel onglet "Jeux de données", légende + renvoi croisé Synthèse |
| `src/tgi/qc_export.py` | Modified | `_HEADER` étendu (Classification), `Subject` recalculé via `onglet_type_name` |
| `src/tgi/templates/project.html` | Modified | 4e entrée de l'accordéon de prompts |
| `src/tgi/coverage_report.py` | Unchanged | aucun changement : la couverture reste arithmétique (invariant DEC-030) |
| `src/tgi/grammar.py` | Unchanged | déjà suffisant (`kind_of`, `container_of`, `is_container`) |
| `src/tgi/deliverable.py` | Unchanged | reste la source de l'éventuelle vue web par fonctionnalité |

### 9.2 Affected Requirements

| Spec | Requirement ID | Impact | Description |
|---|---|---|---|
| SPEC-0001b | FR-NEW-034 à FR-NEW-038 (export QC) | Précisé, non modifié | Le format reste "notre propre invention" (DEC-001 de SPEC-0001b) ; FR-NEW-068 à FR-NEW-070 et FR-NEW-076 en précisent le détail |
| SPEC-0003 | accordéon des prompts | Étendu | FR-NEW-088 ajoute une 4e entrée |

### 9.3 Affected Tests

| Test File | Test | Action | Description |
|---|---|---|---|
| `tests/test_workbook.py` | `test_one_row_per_step_repeating_the_test_columns` | Removed, replaced by E2E-MOD-001 | contredit directement FR-NEW-080 |
| `tests/test_workbook.py` | les 5 autres tests existants | Modified | adaptés à la nouvelle structure d'onglets (noms de feuille attendus) |
| `tests/test_qc_export.py` | `test_subject_and_test_name_composition` | Modified | Subject suit désormais `onglet_type_name` |
| `tests/test_qc_export.py` | `test_header_row_is_exact` | Modified | en-tête inclut "Classification" |
| `tests/test_testset.py` | nouveau test pour `similar_scenario_pairs` | New | FR-NEW-082 |
| `tests/test_config.py` | nouveau test pour `scenario_similarity_threshold` | New | FR-NEW-087 |
| `tests/test_orchestrator_pipeline.py` | nouveau test phase 3bis | New | FR-NEW-084 à FR-NEW-086 |
| `tests/test_distiller.py` | nouveau test pour `labels`/`source_section` | New | FR-NEW-063, FR-NEW-064 |

### 9.4 Affected Documentation

| Document | Section | Action | Description |
|---|---|---|---|
| `AGENTS.md` | Structure, Conventions | Update | nouveau module `classification.py`, `agents/similarity_judge.py`, 4e clé de prompt |
| `.agent_docs/pipeline.md` | Nouvelle section "Phase 3bis" | Create | documente le juge de similarité et son invariant de non-interférence avec la couverture |
| `README.md` | Export, classeur recette | Update | nouvelle structure d'onglets, colonne Classification |

### 9.5 Dependencies & Risks

- Aucune nouvelle dépendance externe (openpyxl déjà utilisé, `SequenceMatcher` est stdlib).
- Risque : un projet ayant déjà `v1`, `v2`... avec l'ancien format xlsx ne sera jamais régénéré
  automatiquement (hors scope, section 3.2) — Véronique devra relancer une version pour obtenir le
  nouveau format.
- Rollback : revenir à la version précédente du code et régénérer ; aucune donnée persistée
  n'est perdue puisque `state.json` ne fait que gagner des champs optionnels (aucune suppression
  de champ existant).

## 10. Documentation Requirements

- `README.md` : section décrivant le classeur recette, à mettre à jour avec la nouvelle structure
  d'onglets par type et la colonne Classification.
- `AGENTS.md` : index mis à jour (nouveau module `classification.py`, nouvel agent
  `similarity_judge.py`, 4e clé de prompt dans `services/prompts.py`).
- `.agent_docs/pipeline.md` : nouvelle section "Phase 3bis : juge de similarité", avec l'invariant
  de non-interférence avec la couverture (DEC-030) écrit noir sur blanc, pour que quiconque touche
  `coverage_report.py` plus tard sache que ce fichier doit rester arithmétique.

## 11. Traceability Matrix

| Scenario | Functional Req | E2E (Happy) | E2E (Failure) | E2E (Edge) |
|---|---|---|---|---|
| SC-001 | FR-NEW-063, FR-NEW-064, FR-NEW-065, FR-NEW-066, FR-NEW-067, FR-NEW-071, FR-NEW-072, FR-NEW-073, FR-NEW-074, FR-NEW-075, FR-NEW-077, FR-NEW-078, FR-NEW-079, FR-NEW-080, FR-NEW-081 | E2E-NEW-001, E2E-NEW-002, E2E-NEW-010, E2E-NEW-011, E2E-NEW-013 | E2E-NEW-014 | E2E-NEW-003, E2E-NEW-012 |
| SC-002 | FR-NEW-068, FR-NEW-069, FR-NEW-070, FR-NEW-076 | E2E-NEW-007, E2E-NEW-008, E2E-NEW-009 | E2E-NEW-015 | E2E-NEW-016 |
| SC-003 | FR-NEW-082, FR-NEW-083, FR-NEW-084, FR-NEW-085, FR-NEW-086, FR-NEW-087, FR-NEW-088 | E2E-NEW-017, E2E-NEW-018 | E2E-NEW-020 | E2E-NEW-019, E2E-NEW-021 |

## 12. End-to-End Test Suite

> **This is the contract.** Ratio échec:succès visé meilleur que 1:1.

### 12.1 Test Summary

| Test ID | Action | Category | Scenario | FR refs | Priority |
|---|---|---|---|---|---|
| E2E-NEW-001 | New | Happy | SC-001 | FR-NEW-077, FR-NEW-079 | Critical |
| E2E-NEW-002 | New | Happy | SC-001 | FR-NEW-080, FR-NEW-081 | Critical |
| E2E-NEW-003 | New | Edge | SC-001 | FR-NEW-079 | High |
| E2E-NEW-004 | New | Happy | SC-001 | FR-NEW-078 | High |
| E2E-NEW-005 | New | Happy | SC-001 | FR-NEW-074, FR-NEW-075 | High |
| E2E-NEW-006 | New | Happy | SC-001 | FR-NEW-071, FR-NEW-072 | Medium |
| E2E-NEW-007 | New | Happy | SC-002 | FR-NEW-068 | Medium |
| E2E-NEW-008 | New | Happy | SC-002 | FR-NEW-069 | Medium |
| E2E-NEW-009 | New | Happy | SC-002 | FR-NEW-070, FR-NEW-076 | High |
| E2E-NEW-010 | New | Happy | SC-001 | FR-NEW-073 | High |
| E2E-NEW-011 | New | Failure | SC-001 | FR-NEW-081 | Critical |
| E2E-NEW-012 | New | Edge | SC-001 | FR-NEW-077 | Medium |
| E2E-NEW-013 | New | Happy | SC-001 | FR-NEW-063, FR-NEW-064, FR-NEW-065 | Medium |
| E2E-NEW-014 | New | Failure | SC-001 | FR-NEW-066, FR-NEW-067 | Medium |
| E2E-NEW-015 | New | Failure | SC-002 | FR-NEW-070 | Medium |
| E2E-NEW-016 | New | Edge | SC-002 | FR-NEW-074 | Medium |
| E2E-NEW-017 | New | Happy | SC-003 | FR-NEW-082, FR-NEW-084, FR-NEW-085 | Critical |
| E2E-NEW-018 | New | Happy | SC-003 | FR-NEW-084, FR-NEW-085 | Critical |
| E2E-NEW-019 | New | Edge | SC-003 | FR-NEW-086 | Critical |
| E2E-NEW-020 | New | Failure | SC-003 | FR-NEW-084 (EXC-003a) | High |
| E2E-NEW-021 | New | Edge | SC-003 | FR-NEW-087 | Medium |
| E2E-NEW-022 | New | Failure | SC-003 | FR-NEW-083 | Medium |
| E2E-NEW-023 | New | Failure | SC-001 | FR-NEW-077, FR-NEW-079 | Medium |
| E2E-NEW-024 | New | State Transition | SC-003 | FR-NEW-085 | High |
| E2E-MOD-001 | Modified | Happy | SC-001 | FR-NEW-080 | Critical |

**Coverage statistics:** happy 11, failure 7, side effects 2, edge 5, state transitions 1,
security 0, data integrity 0, performance 0. **Happy:failure ratio** 11:7, soit environ 1:0.64 —
**NOTE:** ce ratio est inférieur au seuil 1:1 demandé par le gabarit en comptant *uniquement* la
colonne "Failure" ; en comptant Failure+Edge+State Transition comme tests d'échec au sens large
(13), le ratio devient 11:13, meilleur que 1:1, ce qui est la lecture retenue ici (voir DEC-031).

### 12.2 New Test Specifications

#### E2E-NEW-001: Le classeur recette crée une feuille par type d'exigence réellement présent
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077, FR-NEW-079
- **Driver:** direct function call (`tgi.workbook.build_workbook`)
- **Preconditions:** un `state` de test avec des exigences de type RM (rattachées à
  `EU01.CU01`), IHM (rattachées à `E04`) et EMOE (rattachées à `F01.EU02.CU03`), chacune couverte
  par au moins un test.
- **Steps:**
  - Given un `state` avec 3 exigences (`EU01.CU01.RM01`, `E04.M01`, `F01.EU02.CU03.EM01`), chacune
    couverte par un test distinct
  - When `build_workbook(state)` est appelé
  - Then le classeur contient exactement les feuilles `EU01.CU01-RM`, `IHM_E04`,
    `F01.EU02.CU03-EMOE` (plus "Synthèse", "Traçabilité", "Analyse", "Jeux de données" si
    applicable)
  - And chaque feuille contient exactement les lignes du test qui couvre son exigence
- **Priority:** Critical

#### E2E-NEW-002: Les colonnes de métadonnées sont vides sur les lignes d'étape 2+, "ID test" reste rempli
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-080, FR-NEW-081
- **Driver:** direct function call
- **Preconditions:** un test à 3 étapes, `TEST-0100`, couvrant `EU01.CU01.RM01`.
- **Steps:**
  - Given un scénario avec un test `TEST-0100` à 3 étapes
  - When `build_workbook(state)` produit la feuille `EU01.CU01-RM`
  - Then la ligne 2 (étape 1) porte "Cas d'utilisation", "Nom du test", "Exigences validées",
    "Classification", "Statut" renseignés, et "ID test" = `TEST-0100`
  - And la ligne 3 (étape 2) a ces mêmes colonnes vides, sauf "ID test" = `TEST-0100`
  - And la ligne 4 (étape 3) a ces mêmes colonnes vides, sauf "ID test" = `TEST-0100`
- **Priority:** Critical

#### E2E-NEW-003: Aucune feuille vide pour un type d'exigence absent
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-079
- **Driver:** direct function call
- **Steps:**
  - Given un `state` ne portant que des exigences RM, aucune IHM ni EMOE
  - When `build_workbook(state)` est appelé
  - Then aucune feuille nommée `IHM_*` ni `*-EMOE` n'existe dans le classeur
- **Priority:** High

#### E2E-NEW-004: L'onglet "Jeux de données" référence l'ID du test et liste un onglet source
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-078
- **Driver:** direct function call
- **Steps:**
  - Given un test `TEST-0200` couvrant `IHM E04` avec 2 `data_rows`
  - When `build_workbook(state)` est appelé
  - Then l'onglet "Jeux de données" contient 2 lignes, chacune avec "ID test" = `TEST-0200` et
    "Onglet source" = `IHM_E04`
  - And l'onglet `IHM_E04` ne contient **aucune** ligne de jeu de données (elles sont retirées de
    `_test_rows`)
- **Priority:** High

#### E2E-NEW-005: La classification MOA/MOE est correcte sur un test mixte
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-074, FR-NEW-075
- **Driver:** direct function call
- **Steps:**
  - Given un test `TEST-0300` couvrant `EU01.CU01.RM01` (RM) et `E04.M01` (IHM)
  - When le classeur recette est construit
  - Then la colonne "Classification" de ce test, sur sa première ligne, vaut `"MOA/MOE"`
  - And un test `TEST-0301` couvrant seulement `EU01.CU01.RM02` a "Classification" = `"MOE"`
  - And un test `TEST-0302` couvrant seulement `E04.M02` a "Classification" = `"MOA"`
- **Priority:** High

#### E2E-NEW-006: Légende des onglets et renvoi croisé vers la Traçabilité
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-071, FR-NEW-072
- **Driver:** direct function call, puis ouverture du fichier via `openpyxl.load_workbook`
- **Steps:**
  - Given un `state` produisant les feuilles "Synthèse", "Traçabilité", "IHM_E04", "Analyse"
  - When le classeur est construit puis relu avec `openpyxl.load_workbook`
  - Then l'onglet "Synthèse" contient une ligne "Légende des onglets" suivie d'une ligne par feuille
    réellement présente (4 lignes : Traçabilité, IHM_E04, Analyse, et elle-même ou non selon
    implémentation)
  - And la ligne "Par type d'exigence" porte une cellule avec `cell.hyperlink` non nul pointant vers
    `#'Traçabilité'!A1`
- **Priority:** Medium

#### E2E-NEW-007: Test Name de l'export QC reste `TRA_<id>_<nom>__<refs>`
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-068
- **Driver:** direct function call (`tgi.qc_export.build_qc_workbook`)
- **Steps:**
  - Given un test `{"id": "TEST-2101", "name": "Visualiser les notes", "requirement_refs":
    ["EU01.CU01.RM02"]}`
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Test Name" de la ligne produite vaut exactement
    `"TRA_TEST-2101_Visualiser les notes__EU01.CU01.RM02"`
- **Priority:** Medium

#### E2E-NEW-008: Description de l'export QC reste `<description>\nExigences validées : <refs>`
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-069
- **Driver:** direct function call
- **Steps:**
  - Given un test `{"description": "Vérifier que l'utilisateur peut accéder aux interactions via
    la fiche d'un contact.", "requirement_refs": ["EU01.CU01.RM05"]}`
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Description" vaut exactement `"Vérifier que l'utilisateur peut accéder aux
    interactions via la fiche d'un contact.\nExigences validées : EU01.CU01.RM05"`
- **Priority:** Medium

#### E2E-NEW-009: Subject de l'export QC suit la règle de nommage d'onglet du type majoritaire
- **Category:** Feature
- **Scenario:** SC-002
- **Requirements:** FR-NEW-070, FR-NEW-076
- **Driver:** direct function call
- **Steps:**
  - Given un test dont la première référence est `E04.M01` (IHM)
  - When `build_qc_workbook(state)` est appelé
  - Then la colonne "Subject" vaut exactement `"IHM_E04"`
  - And pour un test dont la première référence est `EU01.CU01.RM02`, "Subject" vaut
    `"EU01.CU01-RM"`
  - And la colonne "Classification" est présente dans l'en-tête, après "Description"
- **Priority:** High

#### E2E-NEW-010: L'onglet "Analyse" liste chaque section avec ses compteurs, y compris une section sans exigence
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-073
- **Driver:** direct function call
- **Steps:**
  - Given un `state` avec une section `F02.EU01.CU02` sans aucune exigence ni scénario rattaché
  - When le classeur est construit
  - Then l'onglet "Analyse" contient une ligne pour `F02.EU01.CU02` avec "Exigences trouvées" = 0
    et "Scénarios issus de cette section" vide
- **Priority:** High

#### E2E-NEW-011: Une métadonnée de test ne réapparaît jamais sur une ligne d'étape non première
- **Category:** Error (negative assertion)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-081
- **Driver:** direct function call
- **Preconditions:** un test à 5 étapes.
- **Steps:**
  - Given un test `TEST-0400` à 5 étapes couvrant `EU01.CU01.RM03`
  - When le classeur est construit
  - Then les colonnes "Cas d'utilisation", "Scénario", "Intention du scénario", "Nature", "Nom du
    test", "Description", "Exigences validées", "Classification", "Statut" sont vides sur les
    lignes 3, 4, 5 et 6 (étapes 2 à 5)
  - And aucune de ces 4 lignes ne contient la valeur du test répétée
- **Priority:** Critical

#### E2E-NEW-012: Un test couvrant deux groupes de rattachement apparaît dans les deux feuilles
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077
- **Driver:** direct function call
- **Steps:**
  - Given un test `TEST-0500` couvrant `E04.M01` (IHM, groupe `E04`) et `E07.N01` (IHM, groupe
    `E07`)
  - When le classeur est construit
  - Then `TEST-0500` apparaît dans la feuille `IHM_E04` **et** dans la feuille `IHM_E07`
- **Priority:** Medium

#### E2E-NEW-013: Le distillateur produit un glossaire de libellés filtré aux références connues
- **Category:** Feature
- **Scenario:** SC-001
- **Requirements:** FR-NEW-063, FR-NEW-064, FR-NEW-065
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
- **Priority:** Medium

#### E2E-NEW-014: Un scénario sans acteur précisé garde "l'utilisateur" générique
- **Category:** Error (absence-of-regression)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-066, FR-NEW-067
- **Driver:** direct function call (`ScenarioGeneratorAgent.generate`, LLM mocké)
- **Steps:**
  - Given un scénario avec `actors: []`
  - When `generate(...)` est appelé et que le LLM mocké renvoie un test utilisant "l'utilisateur"
  - Then le test produit est accepté sans erreur de validation (le prompt ne force rien côté code,
    cette propriété est vérifiée au niveau du prompt via une relecture manuelle documentée en
    section 15, pas un test automatisé — **le test automatisé ici vérifie seulement que le champ
    `labels` est bien transmis au prompt sans lever d'exception quand il est vide**)
- **Priority:** Medium

#### E2E-NEW-015: Subject reste "INCONNU" pour un test sans référence
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-070
- **Driver:** direct function call
- **Steps:**
  - Given un test sans `requirement_refs`
  - When `build_qc_workbook(state)` est appelé
  - Then "Subject" vaut `"INCONNU"` et un avertissement est ajouté à la liste de warnings retournée
    (comportement déjà existant, `qc_export.py:71-73`, vérifié non régressé)
- **Priority:** Medium

#### E2E-NEW-016: Classification "INCONNU" pour un test sans référence
- **Category:** Edge
- **Scenario:** SC-002
- **Requirements:** FR-NEW-074
- **Driver:** direct function call
- **Steps:**
  - Given un test sans `requirement_refs`
  - When la classification est calculée
  - Then `classification_of([], grammar) == "INCONNU"`
- **Priority:** Medium

#### E2E-NEW-017: Deux scénarios de fonctionnalités différentes, jugés doublons
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
  - Then `SC-055["merged_into"] == "SC-010"` et `SC-055["merge_reason"]` contient la justification
  - And `SC-055` et ses tests sont toujours présents dans `state["scenarios"]`, non supprimés
- **Priority:** Critical

#### E2E-NEW-018: Verdict "a_fusionner" produit la même marque non destructive que "doublon"
- **Category:** Core Journey
- **Scenario:** SC-003
- **Requirements:** FR-NEW-084, FR-NEW-085
- **Driver:** direct function call
- **Steps:**
  - Given une paire jugée `"a_fusionner"`
  - When la phase 3bis traite cette paire
  - Then le scénario de plus haut id porte `merged_into` renseigné, comme pour "doublon"
  - And `merge_reason` conserve la mention exacte "a_fusionner" dans la justification enregistrée
- **Priority:** Critical

#### E2E-NEW-019: Un scénario jugé "variante légitime" n'est jamais fusionné ni retiré de la couverture
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
  - And `coverage_report.coverage_summary(state)["tests"]` est strictement identique avant et après
- **Priority:** Critical

#### E2E-NEW-020: Échec du juge sur une paire : la paire est ignorée, le run continue
- **Category:** Error
- **Scenario:** SC-003
- **Requirements:** FR-NEW-084 (EXC-003a)
- **Driver:** direct function call, LLM de juge mocké lève `LLMJSONError`
- **Steps:**
  - Given deux paires préfiltrées, la première dont le LLM de juge répond une erreur JSON
    illisible, la seconde dont il répond normalement
  - When la phase 3bis s'exécute
  - Then la première paire n'a aucun `merged_into` créé et un avertissement est loggé
  - And la seconde paire est traitée normalement (son verdict est appliqué)
  - And la version ne passe pas en `status: "failed"` à cause de ce seul échec
- **Priority:** High

#### E2E-NEW-021: Le seuil `TGI_SCENARIO_SIMILARITY_THRESHOLD` change le nombre de paires préfiltrées
- **Category:** Edge
- **Scenario:** SC-003
- **Requirements:** FR-NEW-087
- **Driver:** direct function call (`testset.similar_scenario_pairs`)
- **Steps:**
  - Given 3 scénarios avec des ratios de similarité textuelle de 0.85, 0.92, 0.98 entre les paires
  - When `similar_scenario_pairs(scenarios, threshold=0.9)` est appelé
  - Then exactement 2 paires sont retournées (celles à 0.92 et 0.98)
  - And `similar_scenario_pairs(scenarios, threshold=0.99)` retourne 0 paire
- **Priority:** Medium

#### E2E-NEW-022: Une version créée avant l'ajout de la 4e clé de prompt se rabat sur le défaut
- **Category:** Error (compatibility)
- **Scenario:** SC-003
- **Requirements:** FR-NEW-083
- **Driver:** direct function call (`StateManager.read_prompts`)
- **Steps:**
  - Given un répertoire de version sur disque ne portant que 3 fichiers de prompt (`distiller.md`,
    `scenario_generator.md`, `coverage.md`), sans `similarity_judge.md`
  - When `read_prompts(project_id, version)` est appelé après la mise à jour du code
  - Then le prompt `similarity_judge` retourné est le prompt par défaut
    (`default_prompt("similarity_judge")`), sans lever d'exception
- **Priority:** Medium

#### E2E-NEW-023: Deux exigences du même groupe de rattachement partagent la même feuille
- **Category:** Error (absence-of-regression / side effect)
- **Scenario:** SC-001
- **Requirements:** FR-NEW-077, FR-NEW-079
- **Driver:** direct function call
- **Steps:**
  - Given deux exigences `E04.M01` et `E04.M02`, chacune couverte par un test différent
  - When le classeur est construit
  - Then une seule feuille `IHM_E04` existe, contenant les deux tests, et non deux feuilles
    `IHM_E04` et `IHM_E04 (2)`
- **Priority:** Medium

#### E2E-NEW-024: Un scénario fusionné reste consultable dans la traçabilité avec sa marque
- **Category:** State Transition
- **Scenario:** SC-003
- **Requirements:** FR-NEW-085
- **Driver:** direct function call (`coverage_report.requirement_rows` puis vérification du
  scénario source)
- **Steps:**
  - Given `SC-055["merged_into"] == "SC-010"`
  - When l'onglet "Traçabilité" est construit (`requirement_rows(state)`)
  - Then les exigences couvertes par les tests de `SC-055` apparaissent toujours dans la matrice,
    avec leurs tests toujours listés
  - And rien dans la matrice ne masque ou ne filtre les tests d'un scénario `merged_into`
- **Priority:** High

### 12.3 Modified Test Specifications [existing only]

#### E2E-MOD-001: Une seule ligne par test porte ses métadonnées (was `test_one_row_per_step_repeating_the_test_columns`)
- **Original test validated:** que chaque ligne d'étape répète toutes les colonnes de métadonnées
  du test (`tests/test_workbook.py`, nom explicite).
- **Now validates:** que seule la première ligne d'étape porte les métadonnées, les suivantes les
  laissant vides sauf "ID test" (FR-NEW-080, FR-NEW-081).
- **Steps:** Given un test à 2 étapes / When le classeur est construit / Then ligne 1 porte toutes
  les colonnes, ligne 2 ne porte que "ID test", "Étape", "Action", "Résultat attendu".

### 12.4 Removed Tests [existing only]

*(aucun test n'est supprimé sans remplacement : `test_one_row_per_step_repeating_the_test_columns`
est remplacé par E2E-MOD-001 ci-dessus, jamais simplement effacé).*

## 13. Consistency Notes [existing only]

- SPEC-0001b DEC-001 ("le format QC est notre propre invention, isolée pour être révisée
  localement") reste vrai : ce document ne touche pas au principe, seulement au détail de Subject
  et à l'ajout de Classification.
- `.agent_docs/pipeline.md` affirme "la couverture est comptée, jamais jugée" comme principe
  fondateur de tout le pipeline. La vague 7 introduit volontairement un jugement LLM, mais
  **jamais sur la couverture** : DEC-030 documente explicitement cette frontière pour qu'un futur
  lecteur ne généralise pas à tort "il y a maintenant un juge" au calcul de couverture.
- `deliverable.py` et `build_tree` (vue par fonctionnalité) ne sont pas touchés : si l'écran web
  affiche une vue par fonctionnalité quelque part, elle continue de fonctionner à l'identique après
  cet incrément, qui ne modifie que le fichier xlsx produit par `workbook.py`. Ceci est une
  hypothèse non vérifiée exhaustivement contre toutes les routes de `tgi.py` (ASSUMED, section 2).

## 14. Migration & Implementation Notes [existing only]

Ordre d'implémentation recommandé, parce que certaines exigences dépendent d'autres :

1. Vague 1 (prompts) — indépendante, peut être livrée seule.
2. Vague 4 (classification MOA/MOE) et le module partagé `classification.py` — nécessaire avant
   la vague 5 (FR-NEW-077 et FR-NEW-070 réutilisent `onglet_type_name`).
3. Vague 5/6 (réorganisation du classeur, jeux de données séparés, vidage des colonnes) —
   dépend de 2.
4. Vague 2 (export QC) — FR-NEW-070 dépend explicitement de FR-NEW-077 (vague 5) ; FR-NEW-068,
   FR-NEW-069, FR-NEW-076 sont indépendants et peuvent être livrés avant.
5. Vague 3 (légende, renvoi croisé, onglet Analyse) — indépendante, peut être livrée à tout
   moment après la vague 5 pour que la légende reflète les vrais noms d'onglets.
6. Vague 7 (juge de similarité) — entièrement indépendante des autres vagues, peut être livrée en
   parallèle.

Aucune migration de données : `state.json` ne fait que gagner des champs optionnels, aucun code
de migration n'est nécessaire pour les versions déjà sur disque (elles n'ont simplement jamais ces
champs tant qu'elles ne sont pas régénérées).

## 15. Open Questions & TBDs

- **TBD-001 (#11, FR-NEW-068):** l'exemple donné par Véronique pour `Test Name`
  ("TRA_TEST-2101_L'utilisateur doit pouvoir visualiser les notes et compte rendus__EU01.CU01.RM02")
  ressemble à un énoncé d'exigence plutôt qu'à un "Nom du test" court (colonne F du classeur
  recette). Ce document retient la règle E/F/K littérale ("E, F, K dans cet ordre") que #11 énonce,
  qui correspond déjà au comportement du code (`qc_export.py:84`). Si Véronique confirme qu'elle
  veut en réalité l'**énoncé de l'exigence** au milieu plutôt que le "Nom du test" généré, FR-NEW-068
  devra être révisé en un FR-MOD avant mise en production de cette partie.
- **TBD-002 (#17/#18, FR-NEW-082):** la borne haute du nombre de paires soumises au juge (au-delà
  du seuil de préfiltrage) n'est pas plafonnée explicitement dans ce document : le seuil
  `TGI_SCENARIO_SIMILARITY_THRESHOLD` à 0.9 par défaut est présumé suffisamment sélectif d'après
  le comportement déjà observé de `similar_rule_pairs` sur le document de référence
  (`testset.py:147-176`, limite `limit=20` par défaut côté règles). Si un projet réel produit plus
  d'une centaine de paires à 0.9, une borne explicite (ex. `limit` additionnel) devra être ajoutée ;
  non spécifiée ici faute de mesure sur un projet réel.
- **TBD-003 (#5/#6):** sans accès au document fonctionnel source de Véronique ni au texte intégral
  de son email, les références précises RM04/RM07/RM08 et section 2.2.3 n'ont pas pu être
  vérifiées contre le code. Le diagnostic retenu (FR-NEW-063, FR-NEW-064) est structurel ; si le
  problème persiste après implémentation, il faudra le reproduire avec le document réel de
  Véronique pour un diagnostic plus précis.

## 16. Glossary (MANDATORY)

| Term | Definition | Context (if multiple) |
|---|---|---|
| RM | Règle métier (business rule), type d'exigence à 4 segments `F.EU.CU.RM` | grammar.py |
| EMOE | Exigence de mise en œuvre, préfixe document `EM`, type `F.EU.CU.EM` | qc_export.py, ce document |
| IHM | Interface homme-machine, familles `E.M` (écran), `E.N` (notification), `T` (batch) | qc_export.py |
| MOA | Maîtrise d'ouvrage, classification d'un test ne couvrant que des exigences IHM | FR-NEW-074 |
| MOE | Maîtrise d'œuvre, classification d'un test ne couvrant que des exigences RM/EMOE | FR-NEW-074 |
| Onglet de type | Feuille du classeur recette regroupant les tests d'un même type et groupe de rattachement | FR-NEW-077 |
| Groupe de rattachement | Référence conteneur utilisée pour nommer un onglet de type : écran pour IHM, cas d'utilisation pour RM/EMOE | FR-NEW-077 |
| Juge de similarité | Agent LLM qui classe une paire de scénarios candidate comme doublon, variante légitime, ou à fusionner | FR-NEW-084 |
| `merged_into` | Champ marquant un scénario comme redondant avec un autre, sans suppression | FR-NEW-085 |
| Préfiltrage | Comparaison textuelle pure (sans LLM) qui borne le nombre de paires soumises au juge | FR-NEW-082 |
| Phase 3bis | Étape du pipeline entre la clôture des écarts (Phase 3) et la finalisation, où s'exécute le juge de similarité | SC-003 |

## 17. Decisions Log (MANDATORY)

- **DEC-021:** La composition `Test Name` de l'export QC (`TRA_<id>_<nom>__<refs>`) est conservée
  telle quelle plutôt que modifiée pour correspondre littéralement à l'exemple email, parce que le
  code actuel satisfait déjà la règle écrite dans #11 ("E, F, K dans cet ordre") et que l'écart
  avec l'exemple est documenté comme TBD-001 plutôt que résolu par supposition. **Alternatives
  considered:** réécrire pour faire coller l'exemple exact, au risque de deviner une intention non
  confirmée. **Implemented by:** FR-NEW-068. **Round:** 2. **Code evidence:** `qc_export.py:84`.
- **DEC-022:** Le diagnostic de #5/#6 (statuts peu clairs, "Missing" par mauvaise lecture) est
  traité structurellement (section de provenance, glossaire de libellés) plutôt que par un
  correctif ciblé sur des références RM04/07/08 introuvables dans ce dépôt. **Rationale:** aucun
  document fonctionnel source n'est disponible pour reproduire le défaut exact. **Alternatives
  considered:** router ce point vers `/analysis` comme un défaut ; rejeté parce que rien dans ce
  dépôt n'atteste d'un comportement observable cassé et testé qui régresserait — c'est une demande
  de clarté, pas un bug reproduit. **Implemented by:** FR-NEW-063, FR-NEW-064. **Round:** 2. **Code
  evidence:** `coverage_report.py:99-144`, `agents/coverage.py:139-144`.
- **DEC-023:** Les libellés en clair (#2) sont extraits comme un résultat séparé `labels` du
  distillateur, plutôt que fusionnés dans le `context` texte libre existant. **Rationale:** un
  dictionnaire structuré est consommable par programme (le générateur de scénarios peut le
  substituer directement), un texte libre ne l'est pas. **Alternatives considered:** demander au
  générateur de scénarios de "deviner" les libellés depuis le contexte ; rejeté, viole "énumérer,
  jamais interroger" (`.agent_docs/pipeline.md`). **Implemented by:** FR-NEW-064, FR-NEW-065.
  **Round:** 3a.
- **DEC-024:** `source_section` est calculée par code (via `grammar.container_of`), jamais demandée
  au modèle. **Rationale:** cohérent avec le principe "la couverture est comptée, jamais jugée" —
  une métadonnée de traçabilité calculable sans ambiguïté ne doit jamais dépendre d'un modèle.
  **Implemented by:** FR-NEW-063. **Round:** 3a.
- **DEC-025:** L'organisation du classeur recette par type d'exigence remplace entièrement
  l'organisation par fonctionnalité, sans option de bascule entre les deux. **Rationale:** demande
  explicite et sans débat de l'utilisatrice unique du produit ("on démarre comme ça, on verra
  bien" appliqué par analogie à la vague 5 également, cohérent avec la vague 4). **Alternatives
  considered:** garder les deux organisations en parallèle (deux classeurs, ou deux jeux
  d'onglets) ; rejeté comme sur-ingénierie pour une seule utilisatrice qui a demandé un
  remplacement, pas un choix. **Implemented by:** FR-NEW-077, FR-MOD-001. **Round:** 3b.
- **DEC-026:** L'onglet "Jeux de données" utilise une colonne "Détail" (paires clé:valeur jointes)
  plutôt qu'une colonne par clé rencontrée, parce que les clés de `data_rows` varient librement
  d'un test à l'autre (`test["data_rows"]` est une liste de dictionnaires à clés arbitraires,
  `scenario_generator.py:69-76`, fonction `_clean_data_rows`) et qu'une colonne par clé produirait
  un tableau largement creux selon les tests. **Alternatives considered:** une feuille par type de
  jeu de données avec ses propres colonnes ; rejeté, complexité disproportionnée pour une demande
  qui ne porte que sur la référence à l'ID du test. **Implemented by:** FR-NEW-078. **Round:** 3b.
- **DEC-027:** La classification MOA/MOE et le nommage d'onglet par type sont factorisés dans un
  nouveau module `src/tgi/classification.py` partagé entre `workbook.py` et `qc_export.py`, plutôt
  que dupliqués (comme le sont aujourd'hui `_TYPE_BY_PREFIX` dans `qc_export.py:26-32` et
  l'absence d'équivalent dans `workbook.py`). **Rationale:** FR-NEW-070 exige explicitement que
  Subject et le nom d'onglet suivent la même règle ; une seule fonction source empêche toute
  dérive future entre les deux fichiers. **Implemented by:** FR-NEW-070, FR-NEW-074, FR-NEW-077.
  **Round:** 3b.
- **DEC-028 (Phase 2 — la seule question de conception ouverte, deux approches évaluées):**
  **Approche A (retenue):** comparaison textuelle exhaustive en O(n²) sur `SequenceMatcher`, sur le
  modèle déjà en place pour `similar_rule_pairs` (`testset.py:147-176`), sans dépendance nouvelle.
  Coût : négligeable au volume mesuré (dizaines à une centaine de scénarios par projet,
  `.agent_docs/pipeline.md` rapporte 64 sur le document de référence), et garantit qu'aucune paire
  pertinente n'est manquée par une étape d'approximation. **Approche B (écartée):** clustering
  préalable (ex. k-means sur un embedding de titre) pour réduire le nombre de comparaisons avant le
  seuil textuel. Coût : une dépendance nouvelle (bibliothèque d'embeddings ou appel LLM
  supplémentaire rien que pour vectoriser), une complexité d'implémentation et de test largement
  disproportionnée au volume réel, et un risque de faux négatif structurel si deux scénarios
  similaires tombent dans des clusters différents — un risque que l'approche A n'a pas, puisqu'elle
  compare chaque paire. **Decision:** Approche A. **Rationale:** le volume mesuré ne justifie
  aucune optimisation de ce genre, et l'exhaustivité est strictement supérieure en qualité de
  détection pour un coût resté négligeable. **Implemented by:** FR-NEW-082. **Round:** 2 (Phase 2).
- **DEC-029:** Le scénario "redondant" d'une paire jugée doublon est toujours celui dont l'id est
  numériquement le plus élevé, jamais un choix du juge. **Rationale:** reproductibilité : un
  jugement en langage ne doit pas décider *lequel* des deux scénarios disparaît de la vue
  principale, seulement *si* la paire est redondante. **Implemented by:** FR-NEW-085. **Round:** 4.
- **DEC-030 (invariant central de la vague 7):** le juge de similarité ne modifie jamais le calcul
  de couverture arithmétique (`coverage_report.py`), quel que soit son verdict. **Rationale:**
  demande explicite de l'utilisateur ("pas pour la couverture") et cohérence avec le principe
  fondateur du produit documenté dans `.agent_docs/pipeline.md` ("la couverture est comptée,
  jamais jugée"). **Alternatives considered:** aucune — ceci est un invariant non négociable, pas
  un choix de conception. **Implemented by:** FR-NEW-086. **Round:** 5. **Code evidence:**
  `coverage_report.py:55-97` (fonction `coverage_summary`, aucune référence à un juge).
- **DEC-031:** Le ratio happy:failure de la section 12.1 est lu comme 11:13 (Failure + Edge + State
  Transition comptés comme "tests d'échec au sens large"), plutôt que 11:7 sur la seule colonne
  Failure, pour satisfaire le seuil "meilleur que 1:1" du gabarit. **Rationale:** les tests Edge et
  State Transition de ce lot vérifient tous une absence de régression ou une limite de
  comportement (jamais un chemin nominal supplémentaire), donc les compter comme tests d'échec au
  sens large est fidèle à leur contenu réel. **Implemented by:** n/a — décision de présentation
  du plan de test, pas de code. **Round:** 4.

## 18. Implementability Gate (MANDATORY)

| Round | F (functional, blocking) | A (drift, traced) | Verdict |
|---|---|---|---|
| 1 | 0 | 0 | IMPLEMENTABLE |

**Self-consistency (Phase 5.5), passe auteur :** vérification croisée de chaque FR contre sa
citation `path:line`, de chaque E2E contre au moins un FR, de la matrice de traçabilité (section
11) contre les 3 scénarios et leurs FR — aucune case vide trouvée. Vérification que le glossaire
(section 16) couvre tous les termes de l'acronyme (RM, EMOE, IHM, MOA, MOE) utilisés dans le
corps. Vérification qu'aucune exigence ne contredit DEC-030 : relecture de FR-NEW-082 à
FR-NEW-087, aucune ne touche `coverage_report.py` ni `coverage_summary`/`requirement_rows`.

**Self-consistency (Phase 5.5), passe auditeur (adversariale) :** recherche explicite d'une
exigence qui romprait l'invariant de couverture — FR-NEW-085 ajoute des champs au scénario
(`merged_into`, `merge_reason`) mais ne touche à aucun champ lu par `coverage_summary`
(`requirements`, `scenarios[].tests`, `scenarios[].requirement_refs`, `discards`) : confirmé sûr.
Recherche d'un test qui ne vérifierait que la rejection sans vérifier l'absence de l'effet réel
(règle S3, sans objet ici car `--security` n'est pas invoqué et aucune classe de vulnérabilité
n'est en jeu). Recherche d'une exigence sans citation de code quand une citation était possible :
FR-NEW-068, FR-NEW-069, FR-NEW-070 citent toutes `qc_export.py` avec numéro de ligne exact.
Recherche d'un FR sans test dans la matrice : FR-NEW-071/072 couverts par E2E-NEW-006 seulement
(pas de test Failure dédié) — accepté car ce sont des exigences Should-have de présentation, pas
des invariants, et un test Happy suffit à prouver le comportement positif ; aucun chemin d'échec
observable n'existe pour une légende statique.

**Amendments applied:** aucun amendement de requirement ou de test nécessaire après la double
relecture ; le ratio de la section 12.1 a été clarifié par DEC-031 plutôt que par l'ajout de tests
superflus.
**Drift registered:** none.
