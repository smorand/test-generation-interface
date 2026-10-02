# Confinement des chemins : fermeture de la classe CWE-22

> Generated on: 2026-10-01
> Id: SPEC-0001a
> Nature: FEAT
> Depth: M
> Depth evidence: 2 modules touchés (`src/tgi/tgi.py`, `src/tgi/services/`), 9 exigences, aucun changement de modèle de données, aucun contrat public déplacé. Extrait de SPEC-0001 après trois rounds d'audit, cf. section 13.
> Status: Draft
> Type: Evolution Specification
> From backlog: n/a
> Split: not split
> Parent: SPEC-0001
> Depends on: none
> Security: internal finding
> CVSS: 8.8 — AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H sur le bind par défaut 127.0.0.1, atteignable en requête inter-site ; 8.4 en AV:L pour un attaquant déjà local ; 9.8 en AV:N sans UI:R sur un déploiement conteneur exposé
> Affected: tous les builds déployés à ce jour
> Fixed in: unreleased

## 1. Executive Summary

L'outil écrit sur le disque un fichier dont le nom vient entièrement du client, sans
authentification et sans assainissement. Il construit par ailleurs tous ses chemins de projet
par concaténation d'un identifiant reçu dans une URL, sans jamais vérifier sa forme.

Cet incrément ferme cette classe, **source non fiable atteignant une opération de système de
fichiers qui construit un chemin par concaténation (CWE-22)**, sur la totalité du code
existant, et livre la primitive de confinement que SPEC-0001b appliquera à ses nouvelles
routes.

C'est du durcissement, et il est séparé de SPEC-0001b pour la raison donnée en section 13 :
porté à l'intérieur d'un lot de refonte d'interface, il a absorbé trois rounds d'audit sans se
fermer.

**Trois comportements observables changent malgré tout**, et il vaut mieux les nommer que
prétendre à une invisibilité fausse : le corps du 404 sur projet inconnu passe de
`Project X not found` (`src/tgi/tgi.py:225`) à `{"detail": "projet inconnu: <id>"}` ; celui du
404 sur test inconnu passe de `Test X not found` (`src/tgi/tgi.py:402`) à
`{"detail": "test inconnu: <id>"}` ; et un dépôt de zéro octet passe de 422
(`src/tgi/tgi.py:291`) à 400. Aucun de ces trois n'est consommé par l'interface actuelle.

## 2. Current State

### 2.1 How it works today

**Le nom de fichier déposé.** `POST /upload` (`src/tgi/tgi.py:267`) lit `file.filename` et le
concatène directement : `file_path = upload_dir / (file.filename or "upload.txt")`
(`src/tgi/tgi.py:278`), puis écrit les octets reçus (`src/tgi/tgi.py:280-282`). Aucune
normalisation, aucune vérification de confinement. Le service ne porte aucune authentification,
ce que la section 7.2 de SPEC-0001 assume explicitement.

**Les identifiants d'URL.** `StateManager.project_dir()` fait
`Path(settings.projects_dir) / project_id` (`src/tgi/services/state_manager.py:66`), et
`GitService.repo_dir()` la même chose (`src/tgi/services/git_service.py:36`). **22** gestionnaires
prennent `project_id` directement du chemin d'URL et y aboutissent, de `src/tgi/tgi.py:312` à
`:678`.

**Et `project_dir()` crée le dossier qu'il résout** (`src/tgi/services/state_manager.py:67`),
y compris sur une simple lecture : sonder `GET /projects/ffffffffffff` crée
`projects/ffffffffffff/`. Une sonde laisse donc des traces écrites, ce qui est un effet de bord
que E2E-009 vérifie désormais.

**Un puits de sous-processus.** `GitService.rollback()` exécute `git reset --hard <hash>` avec
`cwd=repo_dir(project_id)` (`src/tgi/services/git_service.py:136` et `:41-44`), où `hash` vient
du corps de `POST /projects/{project_id}/rollback` (`src/tgi/tgi.py:455`). Un `project_id`
valant `..` fait donc tourner git dans le parent du répertoire des projets, qui avec le défaut
`"./projects"` (`src/tgi/config.py:139`) est le répertoire de travail du serveur, c'est-à-dire
la copie du code sous `make run`. C'est ce puits qui porte le `C:H` du vecteur CVSS. `update_test` construit
`self.tests_dir(project_id) / f"{test_id}.json"` (`src/tgi/services/state_manager.py:207`) à
partir du `test_id` de `PUT /projects/{project_id}/tests/{test_id}` (`src/tgi/tgi.py:396`).

**Aucune primitive de confinement n'existe.** Une recherche
`rg -n 'secure_filename|\.resolve\(\)|is_relative_to|commonpath|realpath' src/tgi/services src/tgi/tgi.py`
ne rend rien. Les seuls `.resolve()` du dépôt sont `src/tgi/stats.py:356`, un affichage de
commande, et `src/tgi/build.py:19`, une racine de dépôt. Il n'y a donc aucun contrôle à
contourner : il n'y en a pas.

### 2.2 Existing specifications governing this area

`SPEC-0001` est le parapluie dont ce document est extrait. Il conserve le périmètre complet de
l'incrément, et sa section 18 porte l'historique des trois rounds d'audit qui ont conduit à
cette extraction. Aucune spécification n'est modifiée par le présent document.

### 2.3 Existing test coverage

Commande exacte : `uv run pytest -v` (`Makefile:91-99`). Plancher de couverture 80,
`fail_under = 80` (`pyproject.toml:159`). 304 tests collectés, chiffre pris sur
`uv run pytest --collect-only -q`.

**Aucun test n'exerce cette classe.** Une recherche des charges de traversée dans `tests/` ne
rend rien : ni `..%2F`, ni `%2E%2E`, ni `../`, dans aucun fichier de test. Les 36 tests de
`tests/functional/test_api.py` n'envoient que des identifiants bien formés. La classe est donc
ouverte et non couverte, ce qui est la pire des deux combinaisons.

Les fichiers que cet incrément touche et leur couverture actuelle :
`tests/test_state_manager.py` 16 tests, `tests/test_git_service.py` 7,
`tests/functional/test_api.py` 36. Les 245 autres ne sont pas concernés et doivent passer
inchangés.

### 2.4 Class Sweep

**Class:** une donnée fournie par le client atteint une opération de système de fichiers qui
construit un chemin par concaténation (CWE-22).

L'énoncé ne nomme ni module, ni fichier, ni fonction, ni route : il nomme une source et un
puits, et c'est ce qui lui permet d'attraper les occurrences que l'auteur n'avait pas en tête.

**Searches run**, six, chacune couvrant un idiome distinct :

1. `rg -n 'Path\(.*\)\s*/\s*[a-z_"]' src/tgi/` — concaténation par l'opérateur `/` de `pathlib`,
   la forme employée partout ici. **4 occurrences.**
2. `rg -n 'filename|file\.filename|project_id|test_id|scenario_id' src/tgi/tgi.py src/tgi/services/` —
   part des sources non fiables elles-mêmes. **189 lignes sur 3 fichiers.**
3. `rg -n 'os\.path\.join|open\(|shutil\.|rmtree|unlink|mkdir\(' src/tgi/` — les puits.
   **21 occurrences.**
4. `rg -n '/\s*f"' src/tgi/` — chemin construit par f-string, que la classe de caractères de la
   recherche 1 ne peut pas atteindre. **5 occurrences.**
5. `rg -n 'project_dir\(|tests_dir\(|state_path\(|repo_dir\(' src/tgi/` — les aides de chemin,
   vues depuis la source. **12 occurrences.**
6. `rg -n 'read_text|write_text|read_bytes|write_bytes|\.glob\(|rglob|iterdir\(|\.rename\(|os\.remove' src/tgi/ -g '*.py'` —
   lectures et énumérations, que les cinq précédentes ne couvrent pas. **11 occurrences.**

Idiome non recherché et pourquoi : les gabarits Jinja ne construisent aucun chemin disque, ils
ne produisent que des URL ; `src/tgi/templates/` est hors périmètre.

| Occurrence | Verdict | Disposition |
|---|---|---|
| `src/tgi/tgi.py:276-282` — `projects/_uploads/<file.filename>` | **vulnérable** : `file.filename` vient du client, aucune normalisation | FR-NEW-001 |
| `src/tgi/services/state_manager.py:66` — `Path(settings.projects_dir) / project_id` | **vulnérable** : `project_id` vient du chemin d'URL sur 22 gestionnaires | FR-NEW-002 |
| `src/tgi/services/state_manager.py:70-71` et `:73-74` — `state_path()` et `tests_dir()` | **vulnérable par héritage** : les deux autres aides construites sur `project_id` | FR-NEW-002 |
| `src/tgi/services/state_manager.py:67`, `:75`, `:82`, `:93`, `:96`, `:186`, `:189`, `:208` — `mkdir()` et `open()` | **vulnérable par héritage** : mêmes sources | FR-NEW-002 |
| `src/tgi/services/state_manager.py:207` — `tests_dir / f"{test_id}.json"` | **vulnérable** : `test_id` vient du chemin d'URL (`src/tgi/tgi.py:396`) | FR-NEW-002 |
| `src/tgi/services/state_manager.py:188` — `tests_dir / f"{test.get('id')}.json"` | **vulnérable** : le segment vient de la **sortie du modèle**, hors de portée de FR-NEW-002 qui ne régit que le client | FR-NEW-003 |
| `src/tgi/services/git_service.py:35`, `:36`, `:40`, `:60`, `:61`, `:65` — `repo_dir()` et ses puits | **vulnérable par héritage** : même source | FR-NEW-002 |
| `src/tgi/services/state_manager.py:41` — `source.replace(target)` | **vulnérable par héritage** : les deux chemins viennent de `state_path()` (`src/tgi/services/state_manager.py:93-98`), lequel dérive de `project_id`, donnée client. Confiné par FR-NEW-005, non par une absence de source | FR-NEW-005 |
| `src/tgi/services/git_service.py:136` et `:41-44` — `git reset --hard <hash>` avec `cwd=repo_dir(project_id)` | **vulnérable** : puits de sous-processus, `project_id` venant de l'URL et `hash` du corps (`src/tgi/tgi.py:455`) | FR-NEW-005, test E2E-011 |
| `src/tgi/services/state_manager.py:248` — `base.iterdir()` dans `list_projects` | **vulnérable** : `base` vient bien de la configuration, mais **ce que ce dossier contient vient en partie du client**. Un dépôt nommé `state.json` fait apparaître `projects/_uploads/` comme un projet dont le client contrôle l'état (`src/tgi/tgi.py:276`). Et une fois FR-NEW-005 en place, ce même dossier fait lever `InvalidIdentifier` à chaque appel de `GET /`, qui n'attrape que `FileNotFoundError` et `JSONDecodeError` (`src/tgi/tgi.py:243-246`) : **le correctif créerait lui-même un déni de service permanent et non authentifié** | FR-NEW-009, test E2E-012 |
| `src/tgi/services/doc_parser.py:60-70` et `:120` — `parse()` puis `path.read_text()` | **sûr en soi** : ne concatène rien ; lit le chemin construit en `src/tgi/tgi.py:278` | couvert par FR-NEW-001 |
| `src/tgi/tgi.py:218` — `StaticFiles(directory=str(_STATIC_DIR))` | **sûr** : un chemin d'URL client atteint bien une lecture, mais `_STATIC_DIR` vaut `_MODULE_DIR / "static"` (`src/tgi/tgi.py:52`), résolu par `Path(__file__)`, et `StaticFiles` impose son propre confinement. **Aucune des six recherches ne l'atteint** : il est listé parce qu'un balayage qui ne trouve que ce qu'il cherche n'en est pas un | aucune |
| `src/tgi/tgi.py:182` — `Jinja2Templates(directory=str(_TEMPLATES_DIR))` | **sûr** : même résolution par `Path(__file__)`, et les 9 noms de gabarits passés à `TemplateResponse` sont des littéraux (`src/tgi/tgi.py:258`, `:317`, `:522`, `:554`, `:580`, `:606`, `:647`, `:674`, `:684`) | aucune |
| `src/tgi/tgi.py:167` — `log_dir.mkdir()` | **sûr** : vient de `Settings.log_dir` (`src/tgi/config.py:174-181`), configuration serveur | aucune |
| `src/tgi/tgi.py:180` — `Path(app_settings.projects_dir).mkdir()` | **sûr** : racine de configuration, sans segment client | aucune |
| `src/tgi/config.py:41` — `env_file.read_text()` | **sûr** : `env_file` vaut `Path(".env")`, passé depuis `src/tgi/config.py:156` et `:171`, nom littéral résolu par rapport au répertoire courant ; dérogation assumée à la convention `Path(__file__)` du dépôt | aucune |
| `src/tgi/config.py:91` — `Path(local_app_data) / app_name / "logs"` | **sûr** : `local_app_data` vient de l'environnement du processus, `app_name` est une constante (`src/tgi/config.py:110`) | aucune |
| `src/tgi/config.py:139` — `projects_dir` par défaut `"./projects"` | **sûr** : valeur de configuration serveur | aucune |
| `src/tgi/logging_config.py:49-50`, `src/tgi/tracing.py:58`, `:62-63`, `:72`, `:124-125` | **sûr** : tous dérivés de `Settings.log_dir` ; les noms de rotation sont calculés par `range()` et `with_name()`, jamais reçus | aucune |
| `src/tgi/stats.py:75`, `:152-154`, `:296`, `:346` | **sûr** : motifs littéraux sur le répertoire de traces ou de projets ; commande `tgi-stats`, hors surface HTTP | aucune |
| `src/tgi/validate.py:38`, `:188`, `:382`, `:390`, `:392`, `:424` | **sûr** : `SAMPLE_PATH` est résolu par `Path(__file__)`, `workdir` vient de `tempfile.mkdtemp()` (`src/tgi/validate.py:392`), commande `tgi-validate`, hors surface HTTP | aucune |
| `src/tgi/services/git_service.py:25` — `shutil.which("git")` | **sûr** : argument littéral | aucune |
| `src/tgi/agents/{distiller,scenario_generator,coverage}.py` et `orchestrator.py:308` — `_PROMPT_PATH.read_text()` | **sûr** : constantes résolues par `Path(__file__)` (`distiller.py:29`, `scenario_generator.py:27`, `coverage.py:28`) | aucune |
| `src/tgi/build.py:19` — `Path(__file__).resolve().parents[2]` | **sûr** : constante de module | aucune |

Aucune occurrence n'est reportée au backlog. L'occurrence d'origine, `src/tgi/tgi.py:278`, est
fermée dans ce lot, et toutes celles de la même classe avec elle.

## 3. Scope

### 3.1 In Scope

La fermeture de la classe CWE-22 sur tout le code existant, la primitive de confinement
réutilisable, et les tests qui prouvent l'attaque.

### 3.2 Out of Scope (Non-Goals)

- Toute la refonte d'interface, les versions, la table de modèles et l'export QC : SPEC-0001b.
- L'application de la primitive aux routes que SPEC-0001b crée. Ce document la livre ;
  SPEC-0001b l'emploie et porte ses propres tests d'attaque sur ses propres routes.
- L'ajout d'une authentification. Hors périmètre, et sans rapport avec cette classe : une route
  authentifiée reste traversable.

## 4. User Personas & Actors

| Acteur | Description | Ce qu'il fait ici |
|---|---|---|
| Testeuse recette (Véronique Bertail, équipe TRA) | Utilisatrice légitime | Rien ne change pour elle, hormis le nom de fichier retenu quand elle dépose un document dont le nom porte des caractères interdits |
| Attaquant sur le réseau interne | Non authentifié, atteint le service | Ne peut plus écrire ni lire hors du répertoire des projets |

## 4.5 Bounded Contexts

| Context | Scope | Key entities |
|---|---|---|
| Confinement | La frontière entre une donnée reçue et un chemin disque | `safe_basename`, `validated_project_id`, `validated_version`, `validated_test_id` |
| Persistance | Les dossiers de projets, tels qu'ils existent aujourd'hui | `StateManager`, `GitService` |

## 5. Usage Scenarios

### SC-001: Déposer un document dont le nom est hostile

**Actor:** Attaquant, ou utilisatrice dont le système a produit un nom inhabituel
**Preconditions:** Le service répond.
**Flow:**
1. Un document est déposé sous un nom contenant des séparateurs de chemin.
2. Le système n'en retient que le nom de base, l'assainit et l'écrit dans le projet.
**Postconditions:** Aucun fichier n'existe hors du répertoire des projets.
**Exceptions:**
- [EXC-001a]: nom réduit à `.` ou `..` → remplacé par `document`.
- [EXC-001b]: nom vide après assainissement → remplacé par `document`.
- [EXC-001c]: séparateur Windows `\` → traité comme `/`.

### SC-002: Atteindre un projet par un identifiant mal formé

**Actor:** Attaquant
**Preconditions:** Un projet légitime existe.
**Flow:** Une requête porte un identifiant de projet ou de test qui n'est pas de la forme
attendue ; le système refuse avant toute opération disque.
**Postconditions:** Rien n'est lu, écrit ni supprimé hors du projet désigné.
**Exceptions:**
- [EXC-002a]: identifiant décodant en `..` → 404, aucun accès disque.
- [EXC-002b]: identifiant contenant un séparateur encodé → 404 du routeur ou du gestionnaire.
- [EXC-002c]: identifiant bien formé mais inexistant → 404, corps identique au précédent, pour
  qu'une sonde ne distingue pas les deux cas.

### SC-003: Un identifiant produit par le modèle atteint le disque

**Actor:** Le pipeline lui-même
**Preconditions:** Une génération tourne.
**Flow:** Le modèle rend un test dont l'identifiant contient des séparateurs ; aucun fichier
n'est écrit à partir de cet identifiant.
**Postconditions:** Rien n'est écrit hors du projet.
**Exceptions:**
- [EXC-003a]: le puits est supprimé plutôt qu'assaini, c'est la seule fermeture qui ne puisse
  pas être contournée par une régression.

## 6. Functional Requirements

#### FR-NEW-001 [EARS-E]: Le nom de fichier déposé est confiné
> WHEN un nom de fichier est reçu THE système SHALL n'en retenir que le nom de base, puis
> remplacer par `_` tout octet nul, tout caractère de contrôle et tout caractère de
> `< > : " | ? *`, et SHALL NOT écrire hors du répertoire du projet.

- **Exact names:** fonction `safe_basename(raw: str) -> str` dans `src/tgi/services/paths.py`.
- **Portee:** le fichier déposé est écrit sous `projects/_uploads/`
  (`src/tgi/tgi.py:276`), et non dans un dossier de projet : la mise du document à l'intérieur
  du projet appartient à SPEC-0001b FR-MOD-003. Ce document garantit seulement qu'il ne sort pas
  du répertoire des projets.
- **Business Rules:** l'ordre est normatif, **nom de base d'abord, assainissement ensuite**.
  `../../../etc/passwd.md` donne `passwd.md`, jamais `etc_passwd.md` : ce qui précède le dernier
  séparateur est jeté, pas aplati. L'ordre inverse laisserait passer `.._.._.._etc_passwd.md`.
  Les séparateurs `/` et `\` comptent tous deux.
  La liste de substitution est une **liste noire** et non une liste blanche : une liste blanche
  du type `[A-Za-z0-9._-]` plus lettres Unicode rejetterait l'emoji de
  `spécification_été_📄.docx`, qui est de catégorie Unicode `So`, alors que ce nom est légitime.
  Le confinement vient de la prise du nom de base, pas de la classe de caractères.
  **Les espaces et les points en fin de nom sont retirés avant tout le reste**, parce que NTFS
  les ignore : `".. "` y désigne `..`, et un nom se terminant par un point y désigne le même
  fichier sans le point. L'oublier rouvrirait la classe sur la cible Windows, que `WINDOWS.md`
  documente.
  **Les noms de périphériques réservés de Windows sont préfixés par `_`** : `CON`, `PRN`, `AUX`,
  `NUL`, `COM1` à `COM9`, `LPT1` à `LPT9`, les formes à exposant `COM¹`, `COM²`, `COM³`, `LPT¹`,
  `LPT²`, `LPT³` que Windows reconnaît également, ainsi que `CONIN$` et `CONOUT$`, avec ou sans
  extension, insensible à la casse.
  `CON.md` devient `_CON.md`. Sans cela, `src/tgi/services/doc_parser.py:120` ouvrirait un
  périphérique en lecture synchrone depuis un gestionnaire asynchrone, ce qui bloquerait la
  boucle d'événements du serveur entier : un déni de service à une requête.
  **Tout nom de base qui, après assainissement, ne contient plus que des `.` ou que des `_`
  devient `document`**, comme un nom vide. Cela couvre `.`, `..`, `...`, et un nom composé
  uniquement de caractères de la liste noire comme `<>:"|?*`, qui donnerait sinon `_______`.
  La règle est énoncée ainsi, et non par énumération de `.` et `..`, parce que l'énumération
  laissait passer `...`, lequel ne désigne rien d'utile et varie selon le système de fichiers.
  Le nom retenu est normalisé en NFC.
- **Priority:** Must-have

#### FR-NEW-002 [EARS-UB]: Un identifiant reçu ne compose pas un chemin sans validation
> THE système SHALL NOT employer un `project_id`, un `version` ou un `test_id` reçu dans un
> chemin d'URL, dans un paramètre de requête ou dans un corps de requête pour composer un chemin
> disque sans avoir d'abord vérifié qu'il correspond respectivement à `^[0-9a-f-]{12,36}$`,
> `^v[1-9][0-9]*$` et `^(?!\.+$)[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$`.

- **Exact names:** fonctions `validated_project_id(raw: str) -> str`,
  `validated_version(raw: str) -> str`, `validated_test_id(raw: str) -> str` dans
  `src/tgi/services/paths.py`. Chacune lève `InvalidIdentifier`, que la couche HTTP traduit en
  404. **`InvalidIdentifier` hérite de `ValueError`**, et de rien d'autre : si elle héritait de
  `FileNotFoundError`, les appelants qui attrapent déjà cette dernière, comme
  `src/tgi/tgi.py:243-246`, avaleraient silencieusement un refus de validation et le compte des
  tests existants à corriger passerait de 9 à 8 pour une mauvaise raison.
- **Note sur l'expression du `test_id`:** elle est `^(?!\.+$)[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$`
  et non `^[A-Za-z0-9._-]{1,64}$`. La seconde accepte `..`, qui est un nom de base dégénéré, et
  accepte un nom commençant par un point, donc un fichier caché. Le point reste autorisé à
  l'intérieur par prudence, bien que le schéma n'en produise pas : `test_schema.json:20-22`
  impose `^TEST-[0-9]+$`. L'expression est donc plus large que le schéma, volontairement, pour
  ne pas rejeter un identifiant rédigé à la main dans un état existant.
  La comparaison se fait par **`fullmatch` et non `match`**. La raison n'est pas qu'un `match`
  accepterait un suffixe arbitraire, les motifs étant ancrés par `$` : c'est que `$` appareille
  aussi **avant un saut de ligne final**, donc `match` accepterait `0123456789ab\n`, qu'une URL
  transporte en `%0A`. Les tests unitaires de `paths.py` portent ce cas.
- **Business Rules:** un identifiant non conforme donne 404, jamais 500, et n'atteint aucune
  opération de système de fichiers. Le corps est `{"detail": "projet inconnu: <project_id>"}`,
  `{"detail": "version inconnue: <version>"}` ou `{"detail": "test inconnu: <test_id>"}`, et il
  est **identique** que l'identifiant soit mal formé ou bien formé mais absent, de sorte qu'une
  sonde ne puisse pas distinguer les deux.
  L'expression du projet accepte 12 à 36 caractères hexadécimaux et tirets, parce que les
  projets existants portent des `uuid4` (`src/tgi/services/state_manager.py:107`) de 36
  caractères : une expression plus étroite rendrait tout projet existant inatteignable, ce qui
  serait un changement observable et non du durcissement.
  La charge qui atteint réellement le puits est `%2E%2E`, qui se décode en `..`. Un `%2F` est
  décodé par Starlette **avant** le routage et un segment contenant `/` ne peut appareiller un
  `{param}` : une charge en `%2F` reçoit le 404 du routeur sans qu'aucun gestionnaire ne
  s'exécute, et ne prouve donc rien.
- **Priority:** Must-have

#### FR-NEW-003 [EARS-UB]: Aucun chemin n'est construit à partir d'une sortie de modèle
> THE système SHALL NOT composer de chemin disque à partir d'un identifiant produit par un
> modèle de langage.

- **Business Rules:** ferme `src/tgi/services/state_manager.py:188`, qui construit
  `tests_dir / f"{test.get('id')}.json"` à partir de la sortie du modèle, hors de portée de
  FR-NEW-002 qui ne régit que les entrées client. La fermeture se fait **par suppression** du
  puits, c'est-à-dire de la fonction `add_or_update_tests`, et non par assainissement : la
  fonction n'a aujourd'hui aucun appelant dans `src/tgi`, et un assainissement laisserait un
  puits dormant que rien n'empêche de rebrancher.
- **Priority:** Must-have

#### FR-NEW-004 [EARS-E]: La primitive est appliquée à toutes les routes existantes
> WHEN une route reçoit un `project_id` ou un `test_id` THE système SHALL le faire passer par la
> fonction de validation correspondante avant tout appel à `StateManager` ou `GitService`.

- **Business Rules:** les 22 gestionnaires concernés sont ceux de `src/tgi/tgi.py` qui prennent
  `project_id` en paramètre de chemin, plus `PUT /projects/{project_id}/tests/{test_id}`
  (`src/tgi/tgi.py:396`) pour `test_id`. Appliquer la validation dans `StateManager` plutôt
  qu'à la frontière HTTP serait acceptable et n'est pas ce qui est demandé : la frontière est
  l'endroit où l'on sait que la donnée vient d'un client.
- **Priority:** Must-have

#### FR-NEW-005 [EARS-U]: La validation est portée par les aides de chemin elles-mêmes
> THE système SHALL appeler `validated_project_id` à l'intérieur de
> `StateManager.project_dir()` et de `GitService.repo_dir()` avant toute composition, en plus de
> la validation à la frontière HTTP de FR-NEW-004, et `src/tgi/tgi.py` SHALL NOT composer de
> chemin disque.

- **Business Rules:** la double validation n'est pas une redondance, c'est ce qui rend la
  fermeture **non contournable par ajout**. La validation à la frontière seule laisse une route
  future, ajoutée sans elle, rouvrir la classe en silence ; une assertion structurelle sur
  `src/tgi/tgi.py` ne l'attraperait pas davantage, puisque `tgi.py` ne compose aucun chemin
  lui-même et délègue tout à `StateManager`. Mettre le contrôle dans l'aide de chemin met la
  garde là où passe le trafic.
  La frontière reste néanmoins validée, parce que c'est là que l'on sait quel corps d'erreur
  rendre et que l'on évite de créer un dossier avant de refuser.
- **Priority:** Must-have

#### FR-NEW-006 [EARS-O]: Taille et forme du fichier déposé
> IF le fichier déposé fait zéro octet THEN THE système SHALL répondre 400 avec
> `{"detail": "document vide"}` ; IF il dépasse 52 428 800 octets THEN THE système SHALL
> répondre 413 avec `{"detail": "document trop volumineux (max 50 Mo)"}` et SHALL NOT écrire sur
> disque.

- **Business Rules:** présent ici et non dans SPEC-0001b parce qu'une écriture non bornée sur un
  service non authentifié est une saturation de disque, c'est-à-dire la partie `A:H` du vecteur
  CVSS de cet incrément. La SFD de référence pèse 7 527 741 octets, soit une marge de 6,96 fois.
- **Priority:** Must-have

#### FR-NEW-007 [EARS-U]: Le vecteur de sévérité est consigné
> THE système SHALL porter dans le bloc de tête de ce document le vecteur CVSS de la faille
> fermée, et SHALL NOT le laisser à `not scored`.

- **Business Rules:** trois vecteurs, parce que la sévérité dépend du déploiement et non du code,
  le vecteur applicable au déploiement **par défaut** étant le premier, 8.8, et non le plus
  élevé des trois, qui vaut pour le conteneur exposé :
  `AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H`, score **8.8**, sur le bind par défaut
  `host = "127.0.0.1"` (`src/tgi/config.py:137`), parce que `POST /upload`
  (`src/tgi/tgi.py:267`) est un multipart non authentifié qu'une page tierce visitée par
  l'utilisatrice peut envoyer à `127.0.0.1` sans prévol CORS ; `UI:R` parce qu'il faut qu'elle
  visite cette page. La protection Private Network Access de Chrome bloque partiellement ce cas,
  Firefox et Safari non.
  `AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`, score **8.4**, pour un attaquant déjà local.
  `AV:N` sans `UI:R`, score **9.8**, pour un déploiement conteneur lié à `0.0.0.0`, ce que le
  `Dockerfile` du dépôt rend possible.
- **Rationale:** DRIFT-008 du parapluie, qui relevait que `CVSS: not scored` sous-évaluait une
  écriture de fichier arbitraire non authentifiée.
  `C:H` et non `C:N` : l'écriture arbitraire atteint le répertoire de travail du serveur, qui
  sous `make run` est la copie du code, donc elle permet de remplacer un `.py` exécuté ensuite ;
  et `GET /projects/%2E%2E/history` divulgue le journal git de ce répertoire.
  La première rédaction de ce document portait `AV:A ... C:N`, score 8.1 et non 8.2 comme
  écrit : l'erreur d'arithmétique et la sous-évaluation sont consignées ici plutôt que
  silencieusement corrigées.
- **Priority:** Should-have

#### FR-NEW-009 [EARS-U]: Seul un identifiant bien formé désigne un projet
> THE système SHALL ne retenir dans `StateManager.list_projects()` que les noms de dossier
> acceptés par `validated_project_id`, et SHALL NOT renvoyer 500 sur `GET /` quel que soit le
> contenu du répertoire des projets.

- **Business Rules:** cette exigence existe parce qu'un correctif conforme à FR-NEW-005 **crée
  une régression sans elle**, et c'est le seul endroit du document où une exigence répare le
  correctif plutôt que le code d'origine. Le mécanisme, mesuré : `list_projects`
  (`src/tgi/services/state_manager.py:248`) retient tout dossier portant un `state.json`, et
  `projects/_uploads/` en est un dès qu'un client dépose un fichier nommé `state.json`
  (`src/tgi/tgi.py:276`). Aujourd'hui, cela fait apparaître `_uploads` dans la liste comme un
  projet dont le client écrit l'état. Une fois `project_dir()` validant, le même dossier fait
  lever `InvalidIdentifier` à chaque `GET /`, que `index()` n'attrape pas
  (`src/tgi/tgi.py:243-246`) : déni de service permanent, non authentifié, jusqu'à suppression
  manuelle du fichier.
  Le filtrage se fait **par exclusion silencieuse** et non par exception : un dossier dont le
  nom n'est pas un identifiant valide n'est pas un projet, ce n'est pas une erreur.
- **Priority:** Must-have

#### FR-NEW-008 [EARS-E]: L'édition d'un test n'écrit que dans l'état
> WHEN un test est édité THE système SHALL ne l'écrire que dans le `state.json` du projet, et
> SHALL NOT créer de fichier par test.

- **Business Rules:** ferme le puits `src/tgi/services/state_manager.py:207`, qui est le seul
  des deux puits à avoir un appelant réel, `PUT /projects/{project_id}/tests/{test_id}`
  (`src/tgi/tgi.py:396`). FR-NEW-003 ferme l'autre, celui alimenté par le modèle. Les deux
  disparaissent avec `tests_dir`.
  Conséquence sur les tests existants : `tests/test_state_manager.py:56-66`, qui vérifie la
  création de `tests/TEST-001.json`, est supprimé. C'est le seul test existant que ce document
  retire, et il est retiré parce qu'il verrouille le comportement que l'on ferme.
- **Priority:** Must-have

## 7. Non-Functional Requirements

### 7.1 Performance
Trois expressions régulières compilées par requête. Sans effet mesurable.

### 7.2 Security
C'est l'objet du document. Aucune authentification n'est ajoutée : elle ne fermerait pas cette
classe, une route authentifiée restant traversable.

**Risque résiduel assumé, sur la part `A:H` du vecteur.** FR-NEW-006 borne la taille d'un dépôt
unique à 50 Mio, ce qui ferme l'écriture démesurée en un appel. Cela ne ferme pas la saturation
du disque : rien ne limite le **nombre** de dépôts, et Starlette déverse le corps de la requête
sur disque avant que le gestionnaire ne s'exécute, donc la borne agit après une écriture
temporaire. Un attaquant non authentifié peut donc encore remplir le disque en répétant des
dépôts de 50 Mio. La limitation de débit qui fermerait ce reste n'est pas dans ce lot ; elle est
portée par DRIFT-001 et doit être inscrite au backlog avant la fusion.

### 7.4 Reliability
Un identifiant mal formé donne 404 et non 500, ce qui est aujourd'hui le comportement sur
certains chemins seulement.

### 7.5 Observability
Un identifiant rejeté est journalisé au niveau `WARNING` avec la route et la **forme** de
l'identifiant rejeté, jamais sa valeur brute, pour ne pas recopier une charge dans les traces.

## 8. Data Model

Aucun changement. Ce document ne touche ni `state.json`, ni la disposition des dossiers.

## 9. Impact Analysis

### 9.1 Affected Components

| File/Module | Impact | Description |
|---|---|---|
| `src/tgi/services/paths.py` | Création | les quatre fonctions et `InvalidIdentifier` |
| `src/tgi/tgi.py` | Modification | validation à la frontière sur 22 gestionnaires, assainissement du nom déposé en `:278`, bornes de taille |
| `src/tgi/services/state_manager.py` | Modification | suppression de `add_or_update_tests` et de `tests_dir` |
| `src/tgi/services/git_service.py` | **Modification** | `repo_dir()` valide son `project_id`, FR-NEW-005 ; le puits de sous-processus `rollback()` en dépend. Supprimé plus tard par SPEC-0001b |

### 9.3 Affected Tests

| Test File | Tests | Action | Description |
|---|---|---|---|
| `tests/test_state_manager.py` | 16 | À adapter | un test appelle `add_or_update_tests` (`tests/test_state_manager.py:59`), qui disparaît ; `:56-66`, qui vérifie la création de `tests/TEST-001.json`, est supprimé par FR-NEW-008 |
| `tests/test_git_service.py` | 7 | À adapter | `repo_dir()` valide désormais son argument, FR-NEW-005. **6 des 7 échouent** sur un correctif conforme, leurs identifiants de projet étant des libellés du type `proj-init` |
| `tests/functional/test_api.py` | 36 | Inchangés | **vérifié par exécution** : les 36 passent sur un correctif conforme |
| les 245 autres | 245 | Inchangés | 304 moins 16, 7 et 36 |
| `tests/` | +13 | Création | la suite `E2E-` de la section 12 |

**Mesuré, et non estimé.** Un correctif minimal conforme à FR-NEW-001 à FR-NEW-009, appliqué
dans un arbre de travail jetable, donne **9 échecs et 295 réussites** sur les 304 tests
existants. Les 9 sont : 6 des 7 de `tests/test_git_service.py`, et 3 de
`tests/test_state_manager.py`, aux lignes `:39` (`does-not-exist`), `:56` et `:164` (`p1`). Tous
emploient des identifiants de projet qui ne sont pas des hexadécimaux. Ce sont donc des
fixtures à corriger, pas des régressions : aucun ne décrit un comportement que l'on veut garder.
Le chiffre « un test à adapter » de la première rédaction était faux d'un facteur neuf.

### 9.5 Dependencies & Risks

Aucune dépendance ajoutée. Le seul risque de rupture est l'expression du `project_id` : les
projets existants portent des `uuid4` de 36 caractères, ce que FR-NEW-002 accepte explicitement.
Une expression plus étroite les rendrait inatteignables.

## 10. Documentation Requirements

`AGENTS.md` : une ligne dans les conventions, disant que tout identifiant reçu passe par
`src/tgi/services/paths.py`. `.agent_docs/` : une note sur la classe et sur la raison pour
laquelle les charges en `%2F` ne prouvent rien.

## 11. Traceability Matrix

| Scenario | Functional Req | E2E (Happy) | E2E (Failure) | E2E (Edge) |
|---|---|---|---|---|
| SC-001 | FR-NEW-001, FR-NEW-006, FR-NEW-009 | E2E-001 | E2E-002, E2E-003, E2E-012 | E2E-004, E2E-005 |
| SC-002 | FR-NEW-002, FR-NEW-004, FR-NEW-005 | E2E-006 | E2E-007, E2E-008, E2E-009, E2E-011 | E2E-002, E2E-010 |
| SC-003 | FR-NEW-003, FR-NEW-008 | E2E-013 | E2E-005, E2E-008 | E2E-010 |
| Non-régression | FR-NEW-004, FR-NEW-005 | E2E-006 | E2E-010, E2E-011 | E2E-001, E2E-004 |
| Sévérité et puits de sous-processus | FR-NEW-007, FR-NEW-005 | E2E-010 | E2E-009, E2E-011 | E2E-008 |

## 12. End-to-End Test Suite

> **Ceci est le contrat.** Chaque test de sécurité porte une charge littérale, vérifie le refus
> **et** l'absence d'effet relue par un canal différent de celui de l'envoi, et son champ
> « rouge avant le correctif » est vérifiable.

### 12.1 Test Summary

| Test ID | Action | Category | Scenario | FR refs | Priority |
|---|---|---|---|---|---|
| E2E-001 | New | happy | SC-001 | FR-NEW-001 | Critical |
| E2E-002 | New | security | SC-001 | FR-NEW-001, FR-NEW-002 | Critical |
| E2E-003 | New | failure | SC-001 | FR-NEW-006, FR-NEW-001 | Critical |
| E2E-004 | New | edge | SC-001 | FR-NEW-001, FR-NEW-005 | High |
| E2E-005 | New | security | SC-003 | FR-NEW-003, FR-NEW-001 | Critical |
| E2E-006 | New | happy | SC-002 | FR-NEW-002, FR-NEW-004 | Critical |
| E2E-007 | New | security | SC-002 | FR-NEW-002, FR-NEW-004 | Critical |
| E2E-008 | New | security | SC-002 | FR-NEW-002, FR-NEW-004, FR-NEW-007 | Critical |
| E2E-009 | New | failure | SC-002 | FR-NEW-002, FR-NEW-006, FR-NEW-007 | High |
| E2E-010 | New | security | SC-002 | FR-NEW-005, FR-NEW-002, FR-NEW-003, FR-NEW-007 | Critical |
| E2E-011 | New | security | SC-002 | FR-NEW-005, FR-NEW-002, FR-NEW-004 | Critical |
| E2E-012 | New | security | SC-001 | FR-NEW-009, FR-NEW-001, FR-NEW-005 | Critical |
| E2E-013 | New | security | SC-003 | FR-NEW-008, FR-NEW-002 | High |

**Coverage statistics:** happy 2, failure 2, security 8, edge 1, soit **13 tests**.
**Happy:failure ratio 2:10** en comptant les huit tests de sécurité comme des tests d'échec, ce
qu'ils sont : chacun vérifie un refus. Le ratio dépasse 1:1.

**Couverture par exigence, recomptée sur ce que chaque test vérifie réellement et non sur ses
étiquettes.** La distinction est celle que le round 3 a imposée : une exigence citée dans la
colonne `FR refs` d'un test qui n'vérifie rien à son sujet n'est pas couverte, elle est
étiquetée.

| Exigence | Tests qui l'vérifient **réellement** | Compte |
|---|---|---|
| FR-NEW-001 | E2E-001, 002, 004 | 3 |
| FR-NEW-002 | E2E-007, 008, 009, 010, 011, 013 | 6 |
| FR-NEW-003 | E2E-005 | 1 |
| FR-NEW-004 | E2E-006, 007, 008, 010, 011 | 5 |
| FR-NEW-005 | E2E-010 | 1 |
| FR-NEW-006 | E2E-003, qui en porte les trois cas limites | 1 test, 3 cas |
| FR-NEW-007 | E2E-010 | 1 |
| FR-NEW-008 | E2E-013 | 1 |
| FR-NEW-009 | E2E-012 | 1 |

**Six exigences restent sous le seuil de trois tests distincts** : FR-NEW-003, 005, 006, 007,
008 et 009. Le chiffre est donné tel qu'il est plutôt que relevé en étiquetant des tests qui
n'vérifient rien, ce que les rédactions précédentes de ce tableau faisaient : E2E-003 et E2E-012
y étaient comptés pour FR-NEW-001 alors qu'aucun des deux n'vérifie quoi que ce soit sur
l'assainissement du nom, et E2E-005 comme E2E-010 y étaient comptés pour FR-NEW-008 alors que
ni l'un ni l'autre n'atteint `update_test`.

Pourquoi ces six restent ainsi, et pourquoi c'est acceptable : FR-NEW-003 et FR-NEW-008 ferment
le même puits par deux chemins et leurs tests se recouvrent par construction ; FR-NEW-006 est
une borne à trois cas limites qu'un seul test couvre intégralement et que découper
n'améliorerait pas ; FR-NEW-005, FR-NEW-007 et FR-NEW-009 sont respectivement une descente de
validation, une mention documentaire et un filtre de liste, chacune assertée exactement une
fois, une seconde assertion n'étant qu'une copie. Le seuil de trois est une heuristique, pas
une loi ; la contourner par des étiquettes serait pire que de l'annoncer. L'écart est enregistré
en DRIFT-005.

### 12.2 New Test Specifications

**Montage commun, et il est normatif.** `src/tgi/services/state_manager.py:66` et
`src/tgi/services/git_service.py:36` lisent le **singleton de module** `settings`. Poser la
variable d'environnement `TGI_PROJECTS_DIR` après l'import ne le change donc pas : le singleton
continue de lire `./projects` pendant qu'un `Settings()` neuf lit la valeur attendue, et les
leurres de E2E-007 et E2E-011, posés relativement à `tmp_path`, ne sont jamais atteints.

Chaque test monkeypatche donc `tgi.config.settings.projects_dir` vers `tmp_path/projects` et
construit l'application par
`create_app(Settings(projects_dir=..., logs=tmp_path/"logs"))`, exactement comme la fixture
`client` de `tests/functional/test_api.py:42-72`. Le LLM est toujours simulé. Pilote HTTP :
`AsyncClient(ASGITransport(app))`.

**Toute requête est enveloppée dans `asyncio.wait_for(..., timeout=5)`**, et un dépassement
compte comme un échec du test, nommé d'après la route. Sans cela, une route à flux continu ne
fait pas échouer le test, elle le suspend : `GET /projects/{project_id}/stream`
(`src/tgi/tgi.py:321-351`) rend un flux SSE sans fin et sans contrôle de projet, et le dépôt ne
porte pas `pytest-timeout`.

#### E2E-001: un nom hostile est réduit à son nom de base
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-001
- **Driver:** HTTP client + file system
- **Preconditions:** aucune.
- **Steps:**
  - When `POST /upload` avec `file=("../../../etc/passwd.md", b"# spec\n" * 100, "text/markdown")`
  - Then 200 ou 303, et le nom retenu est `passwd.md`
  - And le fichier existe sous le répertoire des projets et nulle part ailleurs
  - And le même appel avec le séparateur Windows `..\\..\\..\\etc\\passwd.md` donne également
    `passwd.md`
  - And un dépôt nommé `spécification_été_📄.docx` conserve son nom tel quel, comparaison faite
    après `unicodedata.normalize("NFC", nom)` : l'emoji est de catégorie `So` et la liste noire
    ne le touche pas
- **Priority:** Critical

#### E2E-002: le fichier déposé n'atterrit jamais hors du répertoire des projets
- **Category:** Security
- **Scenario:** SC-001
- **Requirements:** FR-NEW-001, FR-NEW-002
- **Driver:** HTTP client + file system
- **Preconditions:** un fichier témoin `tmp_path/temoin.md` contenant `b"TEMOIN"`, et un relevé
  `avant = {p: sha256(p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file() and "logs" not in p.parts}`.
  **L'exclusion de `logs` est nécessaire** : `TGI_LOGS` pointe sous `tmp_path` et le serveur y
  écrit pendant le test, de sorte qu'une égalité portant sur tout `tmp_path` serait rouge même
  après le correctif.
- **Steps:**
  - When `POST /upload` avec, successivement, les noms littéraux `../../escaped.md`,
    `../../temoin.md`, `../../../etc/passwd.md` et `/absolu/evil.md`
  - Then aucun appel ne lève ni ne renvoie 500
  - And, **relu par le système de fichiers et non par l'API**, `tmp_path/escaped.md` n'existe pas
  - And `tmp_path/temoin.md` contient toujours `b"TEMOIN"`
  - And tout fichier apparu hors de `logs` est sous `tmp_path/projects/`
- **Red before the fix because:** mesuré sur le code actuel, et non déduit. Le dépôt est écrit
  sous `projects/_uploads/` (`src/tgi/tgi.py:276`), donc `../../` depuis là atteint exactement
  `tmp_path` : `escaped.md` y est créé, et `../../temoin.md` écrase le témoin. Les charges plus
  profondes comme `../../../etc/passwd.md` lèvent `FileNotFoundError` et n'écrivent rien, ce qui
  est précisément pourquoi elles ne peuvent pas servir de preuve et pourquoi `../../` est la
  bonne profondeur : une charge qui échoue à écrire ne démontre pas le confinement.
- **Priority:** Critical

#### E2E-003: un document vide ou démesuré est refusé avant toute écriture
- **Category:** Error
- **Scenario:** SC-001
- **Requirements:** FR-NEW-006, FR-NEW-001
- **Driver:** HTTP client + file system
- **Steps:**
  - When `POST /upload` avec `file=("vide.md", b"", "text/markdown")`
  - Then 400, `{"detail": "document vide"}`
  - When `POST /upload` avec un `.md` de 62 914 560 octets, soit 60 Mio
  - Then 413, `{"detail": "document trop volumineux (max 50 Mo)"}`
  - And, relu par le système de fichiers, aucun des deux n'a laissé de fichier ni de dossier
  - When `POST /upload` avec un `.md` de **exactement** 52 428 800 octets
  - Then l'appel est accepté : la borne est inclusive, et ce cas limite est ce qui distingue
    une borne correcte d'un `>=` posé à l'envers
- **Priority:** Critical

#### E2E-004: les noms de base dégénérés deviennent `document`
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-001, FR-NEW-005
- **Driver:** HTTP client + file system
- **Steps:**
  - When `POST /upload` avec les noms littéraux `.`, `..`, `...`, `/`, `\\`, `".. "` avec son
    espace final, `"evil.md."` avec son point final, et un nom composé uniquement de caractères
    de la liste noire, `<>:"|?*`
  - Then chaque dépôt accepté porte le nom `document`, sauf `"evil.md."` qui donne `evil.md`,
    et aucun ne désigne un dossier
  - When `POST /upload` avec les noms `CON`, `NUL`, `COM1.md` et `con.MD`
  - Then chacun est écrit sous un nom préfixé `_`, et l'appel rend sa réponse en moins de 5
    secondes : ouvrir un périphérique bloquerait la boucle d'événements
  - **Ces deux derniers groupes ne sont significatifs que sous Windows** et sont marqués
    `skipif` ailleurs ; ils sont spécifiés parce que `WINDOWS.md` documente `tgi.bat` comme
    cible de déploiement, et qu'une classe fermée sur un seul système n'est pas fermée
  - And aucun appel ne renvoie 500, et en particulier aucun ne lève `IsADirectoryError`
  - And, relu par le système de fichiers, aucun dossier du répertoire des projets n'a été
    remplacé par un fichier
- **Priority:** High

#### E2E-005: un identifiant de test venu du modèle n'écrit nulle part
- **Category:** Security
- **Scenario:** SC-003
- **Requirements:** FR-NEW-003, FR-NEW-001
- **Driver:** HTTP client + file system + direct call
- **Preconditions:** le double de LLM rend un test dont le champ `id` vaut littéralement
  `"../../evil"`, **à son premier appel de `scenario_generator` seulement, puis `{"tests": []}`**.
  Sans cette borne, le nombre de tests produits dépend du nombre de cas d'utilisation que la
  distillation trouve dans le document d'essai, et l'assertion « exactement un test » devient
  fonction de la fixture plutôt que du comportement.
- **Steps:**
  - When une génération complète
  - Then, **assertion structurelle, rouge aujourd'hui** :
    `rg -n 'add_or_update_tests|def tests_dir' src/tgi` ne rend rien, et `StateManager` ne porte
    ni l'attribut `add_or_update_tests` ni `tests_dir`
  - And, relu par le système de fichiers, `list(tmp_path.rglob("evil*")) == []`
  - And `list(projects.rglob("tests")) == []`
  - And l'état du projet porte exactement un test, qui conserve le `name` rendu par le modèle et
    dont l'`id` appareille `^TEST-[0-9]+$`. **L'identifiant du modèle n'est pas conservé**, et ce
    n'est pas cette exigence qui le jette : `src/tgi/agents/scenario_generator.py:142` le
    remplace déjà par `f"TEST-{start_index + offset + 1:04d}"`. Asserter « l'identifiant tel
    quel » rendrait ce test inpassable avant comme après le correctif. Conséquence utile :
    aucun identifiant venu du modèle n'atteint l'état non plus
- **Red before the fix because:** `src/tgi/services/state_manager.py:170` définit
  `add_or_update_tests` et `:73` définit `tests_dir` : l'assertion structurelle est rouge sur le
  code actuel. Les assertions de système de fichiers sont, elles, un **garde contre la
  régression** et non une attaque, le puits n'ayant aujourd'hui aucun appelant ; c'est dit
  plutôt que masqué, un « rouge avant le correctif » faux valant moins que pas de test.
- **Priority:** Critical

#### E2E-006: un identifiant bien formé continue de fonctionner
- **Category:** Core Journey
- **Scenario:** SC-002
- **Requirements:** FR-NEW-002, FR-NEW-004
- **Driver:** HTTP client
- **Preconditions:** un projet existant créé par l'application, donc portant un `uuid4` de 36
  caractères (`src/tgi/services/state_manager.py:107`). **Et un second dossier
  `projects/0123456789ab/` portant un `state.json` complet**, copie de celui du premier : sans
  ce projet réel, un identifiant de 12 hexadécimaux rendrait 404 pour cause d'absence, 404 que
  E2E-009 rend délibérément indistinguable d'un refus de validation, donc l'acceptation de la
  forme courte ne serait pas observable.
- **Steps:**
  - When chacune des **21** routes non diffusantes est appelée, via `AsyncClient`, avec
    l'identifiant réel du projet
  - Then aucune ne répond 404 **avec le corps `{"detail": "projet inconnu: <pid>"}`**.
    L'assertion porte sur ce corps et non sur le statut : mesuré sur un correctif conforme,
    trois routes rendent légitimement 404 parce que l'objet second manque, `tests/TEST-0001`
    avec `test inconnu`, `requirements/RM01` avec `Requirement RM01 not found` et `discards/0`
    avec `Discard not found`. Un test qui affirmerait `status != 404` ne pourrait jamais passer
  - And chaque POST et chaque PUT porte un corps, faute de quoi `request.json()` lève :
    `{"hash": "HEAD", "message": "q", "decision": "accepted", "name": "x"}` convient aux cinq
    routes concernées
  - When `GET /projects/{pid}/stream` est pilotée **en ASGI brut** et non par `AsyncClient` :
    construire le `scope` à la main, fournir un `receive` qui ne rend jamais, et résoudre une
    promesse dès le premier `http.response.start` ; envelopper cette promesse dans
    `wait_for(5)` puis annuler la tâche
  - Then le statut lu sur `http.response.start` vaut 200
  - And `GET /projects/0123456789ab` répond 200 : la forme à 12 hexadécimaux que SPEC-0001b
    produira est acceptée
- **Pourquoi ce pilote particulier pour `/stream`:** `src/tgi/tgi.py:321-351` rend un flux SSE
  sans fin, et `ASGITransport` de httpx met tout le corps en tampon avant de rendre la réponse.
  Appelée par `AsyncClient`, même avec un identifiant **valide** et même sur une implémentation
  correcte, cette route dépasse donc le `wait_for` du montage commun : le test échouerait
  toujours, correctif ou non. Mesuré. C'est la sixième façon, sur ce lot et son parapluie, dont
  un test peut ne pas fonctionner, et la première où le défaut est qu'il ne peut jamais passer
  plutôt qu'il ne peut jamais échouer.
- **Priority:** Critical
- **Rationale:** c'est le test qui empêche le durcissement de casser les projets existants,
  risque nommé en 9.5.

#### E2E-007: un identifiant de projet décodant en `..` n'atteint pas le disque
- **Category:** Security
- **Scenario:** SC-002
- **Requirements:** FR-NEW-002, FR-NEW-004
- **Driver:** HTTP client + file system
- **Preconditions:** un projet légitime `{pid}`. Et un **leurre complet** hors du répertoire des
  projets, de sorte que `projects/..` soit un projet valide à tous égards sauf son identifiant :
  `tmp_path/state.json` portant toutes les clés que `StateManager.create` écrit
  (`src/tgi/services/state_manager.py:102-121`), dont `doc_text` valant `"ROOT-LEAK"`.
  **Cette complétude est la condition pour que le test attaque** : un leurre partiel ferait
  échouer la lecture et le 404 tomberait tout seul, donc le test serait vert sans validation.
- **Steps:**
  - When `GET /projects/%2E%2E`, charge littérale qui se décode en `..` et atteint bien le
    gestionnaire, contrairement à `..%2F..%2F` que Starlette décode avant le routage
  - Then 404, corps `{"detail": "projet inconnu: .."}`
  - And aucun corps de réponse ne contient `ROOT-LEAK`
  - And, relu par le système de fichiers, l'empreinte sha256 de `tmp_path/state.json` est
    inchangée
- **Red before the fix because:** sans FR-NEW-002, `..` se concatène en `projects/..`,
  `state.json` s'y lit, et la page rend 200 en affichant `ROOT-LEAK`.
- **Priority:** Critical

#### E2E-008: un identifiant de test décodant en `..` n'écrit pas hors du projet
- **Category:** Security
- **Scenario:** SC-002
- **Requirements:** FR-NEW-002, FR-NEW-004, FR-NEW-007
- **Driver:** HTTP client + file system
- **Preconditions:** un projet légitime `{pid}` dont l'état contient un test dont l'`id` vaut
  **littéralement** `..\..\evil`. Ce leurre est indispensable : `update_test` n'écrit que si
  l'identifiant existe déjà dans l'état (`src/tgi/services/state_manager.py:198`), donc sans lui
  le code actuel répond 404 tout seul et le test serait vert sans validation. Relevé
  `{p: sha256(p.read_bytes()) for p in projects.rglob("*") if p.is_file()}` pris avant.
- **Steps:**
  - When `PUT /projects/{pid}/tests/%2E%2E%5C%2E%2E%5Cevil` avec un corps d'édition valide.
    `%5C` est employé et non `%2F` parce qu'il traverse le routeur **en un seul segment**, là où
    un `%2F` décodé avant le routage empêcherait l'appariement et rendrait le 404 du routeur
  - Then 404, corps `{"detail": "test inconnu: ..\\..\\evil"}`
  - And, relu par le système de fichiers, aucun fichier dont le nom contient `evil` n'existe
    sous `tmp_path`
  - And le relevé pris ensuite égale celui pris avant, `state.json` compris
- **Red before the fix because:** mesuré. Le code actuel trouve le test dans l'état, répond 200,
  réécrit `state.json` et crée `tests/..\..\evil.json`
  (`src/tgi/services/state_manager.py:207`). Sous POSIX ce nom est un fichier unique au
  caractère `\` près ; sous Windows, cible de déploiement documentée par `WINDOWS.md`, c'est une
  traversée réelle de deux niveaux. Les trois assertions tombent dans les deux cas.
- **Priority:** Critical

#### E2E-009: un identifiant mal formé et un identifiant absent sont indistinguables
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-002, FR-NEW-006, FR-NEW-007
- **Driver:** HTTP client
- **Steps:**
  - When `GET /projects/%2E%2E` puis `GET /projects/ffffffffffff`, le second étant bien formé
    mais inexistant
  - Then les deux répondent 404 avec un corps de la même forme,
    `{"detail": "projet inconnu: <valeur>"}`, et aucun en-tête ne les distingue
  - And aucun des deux ne renvoie 500
  - And l'écart de temps de réponse entre les deux reste sous 50 ms, de sorte qu'une sonde ne
    puisse pas les séparer par chronométrage
  - And, relu par le système de fichiers, **le dossier `projects/ffffffffffff/` n'existe pas** :
    une sonde ne doit rien laisser derrière elle. `StateManager.project_dir()` crée aujourd'hui
    le dossier qu'il résout (`src/tgi/services/state_manager.py:67`), y compris sur une lecture,
    donc cette assertion est rouge sur le code actuel et impose de refuser avant de résoudre
- **Priority:** High

#### E2E-010: aucune composition de chemin n'échappe à la primitive
- **Category:** Security
- **Scenario:** SC-002
- **Requirements:** FR-NEW-005, FR-NEW-002, FR-NEW-003, FR-NEW-007
- **Driver:** direct call
- **Steps:**
  - When, pour **chaque** route de `app.routes` dont le chemin contient `{project_id}`, la route
    est appelée avec sa propre méthode, `%2E%2E` substitué à `{project_id}` et une valeur bien
    formée substituée aux autres paramètres
  - Then chacune répond 404 avec `{"detail": "projet inconnu: .."}`, et aucune ne répond 200 ni
    500
  - And `StateManager().project_dir("..")` et `GitService().repo_dir("..")` lèvent
    `InvalidIdentifier`
  - And `src/tgi/services/paths.py` expose `safe_basename`, `validated_project_id`,
    `validated_version`, `validated_test_id` et `InvalidIdentifier`
  - And le bloc de tête de ce document porte un vecteur CVSS et non `not scored`
- **Red before the fix because:** mesuré sur les 22 routes. `GET /projects/%2E%2E/stream` rend
  aujourd'hui un flux 200 sans fin, donc **sans l'enveloppe `wait_for` ce test se suspend au
  lieu d'échouer**, ce qui est pire qu'un échec. Les 21 autres rendent bien 404 mais avec le
  corps `Project .. not found` (`src/tgi/tgi.py:225`) et non `{"detail": "projet inconnu: .."}`
  : elles sont donc rouges par le corps, pas par le statut, et ce test ne pose délibérement
  aucun leurre, celui de E2E-007 étant propre à `GET /projects/{project_id}`.
  Enfin `project_dir("..")` rend `projects/..` au lieu de lever.
- **Priority:** Critical
- **Rationale:** c'est le test qui rougit quand une **nouvelle** route est ajoutée sans
  validation, donc celui qui protège SPEC-0001b et la suite. Il énumère les routes depuis
  `app.routes` au lieu de les lister en dur, pour cette raison exacte. Et il vérifie le
  comportement des aides de chemin, et non une propriété syntaxique de `src/tgi/tgi.py`, lequel
  ne compose aucun chemin lui-même : une assertion syntaxique y serait verte sans rien prouver.

#### E2E-013: l'édition légitime d'un test n'écrit aucun fichier par test
- **Category:** Security
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008, FR-NEW-002
- **Driver:** HTTP client + file system
- **Preconditions:** un projet `{pid}` dont l'état porte un test d'identifiant `TEST-0001`.
- **Steps:**
  - When `PUT /projects/{pid}/tests/TEST-0001` avec `{"name": "edited"}`
  - Then 200 : l'édition légitime continue de fonctionner, ce n'est pas elle que l'on ferme
  - And, relu dans `state.json` sur le système de fichiers, le test porte `name` valant `edited`
  - And `list(projects.rglob("tests")) == []` : aucun dossier `tests/`
  - And, assertion plus forte que la précédente et qui est celle qui compte, l'ensemble des
    fichiers sous `projects/` avant et après le `PUT` ne diffère que par `state.json` et par le
    contenu de `.git/`. Une écriture à plat en `<pid>/TEST-0001.json`, sans dossier `tests/`,
    passerait la seule assertion `rglob("tests")`
- **Red before the fix because:** mesuré, le code actuel répond 200 **et** crée
  `<pid>/tests/TEST-0001.json` (`src/tgi/services/state_manager.py:207`), donc la dernière
  assertion tombe.
- **Priority:** High
- **Rationale:** c'est le seul test qui emprunte le **chemin légitime** jusqu'à `update_test`.
  E2E-008 est refusé à la validation et n'atteint jamais la fonction, et E2E-005 fait une
  génération et non une édition : sans E2E-013, une implémentation qui conserve l'écriture par
  fichier en ligne passerait les douze autres tests.

#### E2E-012: un fichier déposé nommé `state.json` ne crée pas de projet
- **Category:** Security
- **Scenario:** SC-001
- **Requirements:** FR-NEW-009, FR-NEW-001, FR-NEW-005
- **Driver:** HTTP client + file system
- **Preconditions:** aucune ; le répertoire des projets peut être vide.
- **Steps:**
  - When `POST /upload` avec
    `file=("state.json", <JSON d'un état complet dont `doc_text` vaut "UPLOAD-LEAK">, "application/json")`
  - Then `GET /` répond **200**, et non 500
  - And son corps ne contient ni `_uploads` ni `UPLOAD-LEAK`
  - And `GET /projects/_uploads` répond 404 `{"detail": "projet inconnu: _uploads"}`
- **Red before the fix because:** mesuré des deux côtés, et c'est le seul test du document dont
  les deux moitiés rougissent pour des raisons opposées. **Sur le code actuel**, `GET /` répond
  200 mais liste `_uploads` comme un projet dont le client contrôle l'état, parce que
  `list_projects` retient tout dossier portant un `state.json`
  (`src/tgi/services/state_manager.py:248`) et que le dépôt écrit dans `projects/_uploads/`
  (`src/tgi/tgi.py:276`) : l'assertion sur le corps tombe. **Sur un correctif conforme à
  FR-NEW-005 mais sans FR-NEW-009**, `GET /` lève `InvalidIdentifier` et rend 500 de façon
  permanente, `index()` n'attrapant que `FileNotFoundError` et `JSONDecodeError`
  (`src/tgi/tgi.py:243-246`) : l'assertion de statut tombe. Ce test est donc le garde-fou du
  correctif autant que du code d'origine.
- **Priority:** Critical

#### E2E-011: un identifiant de projet `..` ne fait pas tourner git hors du répertoire
- **Category:** Security
- **Scenario:** SC-002
- **Requirements:** FR-NEW-005, FR-NEW-002, FR-NEW-004
- **Driver:** HTTP client + file system + sous-processus git
- **Preconditions:** le leurre complet `tmp_path/state.json` de E2E-007, et `tmp_path`
  initialisé en dépôt git portant deux commits. Empreinte sha256 du leurre et valeur de
  `git -C tmp_path rev-parse HEAD` relevées avant.
- **Steps:** les deux appels sont **mesurés séparément, et jamais enchaînés avant lecture de
  l'effet**. C'est la condition de validité de ce test, et elle est contre-intuitive : sur du
  code vulnérable, `validate-map` crée un commit et `rollback` le défait, donc les deux appels
  **s'annulent** et les deux assertions d'effet passent au vert alors que les deux attaques ont
  réussi. Mesuré : `HEAD` vaut `f31c5d04`, puis `94cbf4f6` après `validate-map`, puis `f31c5d04`
  de nouveau après le `reset`.
  - Given `h0 = git -C tmp_path rev-parse HEAD` et l'empreinte sha256 du leurre relevées
  - When `POST /projects/%2E%2E/validate-map`
  - Then 404 `{"detail": "projet inconnu: .."}`
  - And **immédiatement, avant tout autre appel**, l'empreinte du leurre et
    `git -C tmp_path rev-parse HEAD` valent encore leurs valeurs relevées
  - When, dans un second temps, `POST /projects/%2E%2E/rollback` avec `{"hash": "HEAD~1"}`
  - Then 404 `{"detail": "projet inconnu: .."}`
  - And, relu par **un canal entièrement différent** de celui de l'envoi,
    `git -C tmp_path rev-parse HEAD` vaut `h0` et `git -C tmp_path rev-list --count HEAD` vaut 2
- **Red before the fix because:** mesuré, et pris séparément. `validate-map` seul répond 200 et
  porte `HEAD` à un troisième commit dans `tmp_path`, par
  `src/tgi/agents/orchestrator.py:155-158`. `rollback` seul exécute `git reset --hard HEAD~1`
  avec `cwd` valant `projects/..` (`src/tgi/services/git_service.py:136` et `:41-44`), donc
  `HEAD` recule dans le dépôt du serveur lui-même et le compte de commits tombe à 1.
- **Priority:** Critical
- **Rationale:** c'est le seul test qui atteint un puits de **sous-processus** plutôt que
  d'écriture de fichier, et c'est lui qui justifie le `C:H` du vecteur CVSS de FR-NEW-007.

## 13. Consistency Notes

Ce document est extrait de `SPEC-0001` après trois rounds d'audit d'implémentabilité qui ont
tous rendu `NOT-IMPLEMENTABLE`, et dont les constats bloquants se concentraient tous ici. La
section 18 du parapluie porte le détail. Le motif, qui justifie l'extraction plutôt qu'un
quatrième round : chaque round a fermé une condition de l'attaque et découvert la suivante,
d'abord la charge absorbée par le routeur, puis le leurre absent, puis le leurre incomplet au
regard du modèle de données. Trois corrections justes et insuffisantes de suite disent que la
fermeture d'une classe CWE-22 est un lot à part, pas une section d'un lot de refonte.

Aucune spécification existante n'est modifiée.

## 14. Migration & Implementation Notes

Ordre imposé, chaque étape laissant la suite verte :

1. `src/tgi/services/paths.py` et ses tests unitaires. Rien n'en dépend encore.
2. FR-NEW-003, la suppression de `add_or_update_tests` et de `tests_dir`, et l'adaptation de
   `tests/test_state_manager.py:59`. À faire avant l'étape 3, parce que l'étape 3 touche les
   mêmes fichiers.
3. FR-NEW-004, l'application à la frontière HTTP, puis FR-NEW-001 et FR-NEW-006 sur le dépôt.
4. FR-NEW-005, la descente de la validation dans `StateManager.project_dir()` et
   `GitService.repo_dir()`, **et FR-NEW-009 dans le même commit**. L'ordre est contraint :
   FR-NEW-005 sans FR-NEW-009 fait rendre 500 à `GET /` dès qu'un `state.json` traîne dans
   `projects/_uploads/`, donc les livrer séparément laisse la suite rouge et l'application
   inutilisable entre les deux.
5. Les fixtures des 9 tests existants que le durcissement casse, listées en 9.3.

Pas de bascule par drapeau. Retour arrière par retour au commit précédent.

## 15. Open Questions & TBDs

Aucune. Les deux choix qui auraient pu en être, la liste noire plutôt que la liste blanche et la
suppression plutôt que l'assainissement du puits modèle, sont tranchés en DEC-013 et DEC-014.

## 16. Glossary

| Term | Definition | Context (if multiple) |
|---|---|---|
| CWE-22 | Traversée de chemin : une donnée reçue compose un chemin et sort du répertoire prévu | |
| Classe | Un couple source et puits, énoncé sans nommer de module ni de fonction | |
| Puits | L'opération de système de fichiers qui reçoit le chemin composé | |
| Source | La donnée non fiable qui entre dans la composition | |
| Leurre | Un fichier ou un projet valide posé à l'emplacement que l'attaque vise, sans lequel un test de traversée est vert avant le correctif | |
| Nom de base | Le dernier segment d'un chemin, ce qui suit le dernier séparateur | |
| Confinement | La garantie qu'un chemin composé reste sous un répertoire donné | |

## 17. Decisions Log

- **DEC-013:** L'assainissement du nom de fichier emploie une **liste noire** de caractères
  dangereux, et non une liste blanche. **Rationale:** une liste blanche du type `[A-Za-z0-9._-]`
  plus lettres Unicode rejetterait l'emoji de `spécification_été_📄.docx`, de catégorie Unicode
  `So`, alors que ce nom est légitime et doit survivre. Le confinement vient de la prise du nom
  de base, pas de la classe de caractères, donc restreindre celle-ci coûte des faux positifs
  sans rien gagner. **Alternatives considérées:** liste blanche stricte, écartée.
  **Implemented by:** FR-NEW-001. **Round:** 1.
- **DEC-014:** Le puits alimenté par la sortie du modèle est **supprimé** et non assaini.
  **Rationale:** `add_or_update_tests` n'a aujourd'hui aucun appelant dans `src/tgi` ; un
  assainissement laisserait un puits dormant que rien n'empêche de rebrancher, alors que la
  suppression est vérifiable par une assertion structurelle. **Alternatives considérées:**
  assainir l'identifiant comme un nom de fichier, écartée. **Implemented by:** FR-NEW-003.
  **Round:** 1. **Code evidence:** `src/tgi/services/state_manager.py:170` et `:188`.
- **DEC-015:** L'expression du `project_id` accepte 12 à 36 caractères hexadécimaux et tirets.
  **Rationale:** les projets existants portent des `uuid4` de 36 caractères
  (`src/tgi/services/state_manager.py:107`) et SPEC-0001b produira des identifiants de 12
  hexadécimaux ; une expression calée sur l'un rendrait l'autre inatteignable, ce qui serait un
  changement observable et non du durcissement. **Alternatives considérées:** `^[0-9a-f]{12}$`
  seul, écartée parce qu'elle casse le parc existant. **Implemented by:** FR-NEW-002.
  **Round:** 1.
- **DEC-016:** Les charges de test emploient `%2E%2E` et jamais `%2F`. **Rationale:** Starlette
  décode `%2F` avant le routage et un segment contenant `/` ne peut appareiller un `{param}` :
  une charge en `%2F` reçoit le 404 du routeur sans atteindre aucun gestionnaire, donc le test
  est vert même sans validation et ne prouve rien. **Alternatives considérées:** garder les
  charges en `%2F`, écartée après vérification empirique par deux auditeurs indépendants.
  **Implemented by:** FR-NEW-002, et la forme de E2E-007 et E2E-008. **Round:** 2.
- **DEC-020:** FR-NEW-005 et FR-NEW-009 sont livrées dans le même commit. **Rationale:** la
  première sans la seconde rend `GET /` définitivement 500 dès qu'un `state.json` se trouve dans
  `projects/_uploads/`, c'est-à-dire qu'elle transforme une divulgation en déni de service.
  **Alternatives considérées:** livrer FR-NEW-005 seule et traiter la régression ensuite,
  écartée : elle laisse l'application inutilisable entre les deux commits.
  **Implemented by:** FR-NEW-009, et l'ordre de la section 14. **Round:** 2 de ce document.
- **DEC-018:** Un test de traversée n'est réputé valide qu'une fois **exécuté contre le code
  non corrigé et contre un correctif conforme**, observé rouge dans le premier cas et vert dans
  le second. **Rationale:** quatre fois de suite, sur ce lot et son
  parapluie, un test écrit de bonne foi s'est révélé vert avant le correctif, pour quatre
  raisons différentes : le routeur absorbait la charge, la cible n'existait pas, la cible était
  incomplète, puis le puits refusait d'écrire faute de leurre dans l'état. Aucune de ces quatre
  n'était déductible par lecture. **Alternatives considérées:** s'en remettre à la relecture,
  écartée par quatre contre-exemples. **Implemented by:** le champ
  « Red before the fix because » de chaque test de sécurité, qui cite désormais une mesure et
  non un raisonnement. **Round:** 1 de ce document.
- **DEC-019:** La validation est portée à la fois par la frontière HTTP et par les aides de
  chemin. **Rationale:** la frontière seule laisse une route future rouvrir la classe en
  silence, et une assertion syntaxique sur `src/tgi/tgi.py` ne l'attraperait pas, ce fichier ne
  composant aucun chemin. Mettre la garde dans `project_dir()` et `repo_dir()` la place là où
  passe le trafic. **Alternatives considérées:** frontière seule, et assertion syntaxique,
  toutes deux écartées. **Implemented by:** FR-NEW-005. **Round:** 1 de ce document.
- **DEC-017:** Chaque test de traversée pose un **leurre complet** à l'emplacement visé.
  **Rationale:** un leurre partiel fait échouer la lecture et le gestionnaire rend 404 de
  lui-même, donc le test est vert avant le correctif. C'est ce défaut, découvert deux rounds de
  suite sous deux formes différentes, qui a motivé l'extraction de ce document.
  **Alternatives considérées:** se contenter d'asserter le 404, écartée : c'est exactement
  l'assertion qu'un code vulnérable satisfait. **Implemented by:** E2E-007. **Round:** 3.

## 18. Implementability Gate

| Round | F (functional, blocking) | A (drift, traced) | Verdict |
|---|---|---|---|
| 1 | 9 (5 BLOCKING, 4 MINOR) | 8 | NOT-IMPLEMENTABLE |
| 2 | 7 (4 BLOCKING, 3 MINOR) | 6 | NOT-IMPLEMENTABLE |
| 3 | 2 (1 MAJOR, 1 MINOR) | 5 | NOT-IMPLEMENTABLE, plafond de trois rounds atteint |
| 4 | **0** | 7 | **IMPLEMENTABLE-WITH-DRIFT** |

**Round 4, de confirmation, signé par l'utilisateur.** Un quatrième auditeur, à contexte neuf, a
construit à son tour une implémentation conforme dans deux arbres jetables, l'un resté à `HEAD`
et l'autre corrigé, et a mesuré les treize tests des deux côtés. **Aucun constat F.** Les huit
tests de sécurité attaquent, et chacun peut devenir vert. Le pilote ASGI brut de `/stream`,
imposé au round 3, fonctionne et rend 200 sur les deux arbres sans suspendre. E2E-013 est rouge
sur `HEAD` et vert sur le correctif. La suite existante donne de nouveau **9 échecs et 295
réussites**, aux mêmes identifiants de test qu'au round 3.

Il cherchait une septième façon, pour un test de sécurité, de ne pas attaquer, les six
précédentes ayant chacune été trouvée par un round distinct. **Il n'en a pas trouvé.** Il a
aussi dérivé quatre recherches de son cru, cherchant une quatrième catégorie de puits après le
sous-processus, la liste de dossiers alimentée par les dépôts et l'aliasing Windows : arguments
de sous-processus construits depuis le corps, champs d'état relus comme chemins, aliasing de
casse, en-tête construit depuis une valeur client. **Aucune quatrième catégorie.** L'injection
d'option sur `git reset --hard` a été testée et échoue côté git.

Les sept constats A du round 4 sont traités comme le gate l'impose : ceux dont la correction est
évidente, c'est-à-dire les coquilles sur la réalité, sont corrigés en place, et l'écart de
couverture qui subsiste est enregistré en DRIFT-005. Corrections appliquées : l'énoncé EARS de
FR-NEW-002 porte désormais la bonne expression de `test_id` ; la justification de `fullmatch`
dit la vraie raison, le `$` appareillant avant un saut de ligne final ; le tableau de couverture
est recompté sur les assertions ; E2E-005 borne sa fixture ; E2E-006 vérifie un corps et non un
statut, et envoie un corps sur ses POST et PUT ; E2E-013 gagne l'assertion d'ensemble de
fichiers, plus forte que `rglob("tests")` ; FR-NEW-001 étend la liste réservée Windows aux
formes à exposant, à `CONIN$` et à `CONOUT$`.

**Hors périmètre, relevé au passage et à porter au backlog :** `infer_grammar` lève
`ValueError: max() iterable argument is empty` (`src/tgi/grammar.py:184`) sur un document à un
seul cas d'utilisation, et la tâche de fond non rattrapée laisse le projet bloqué. Sans rapport
avec cette classe.

**Amendments applied, round 3 :** E2E-006 pilote désormais `/stream` en ASGI brut, le seul
moyen pour qu'il puisse passer ; E2E-013 est ajouté pour couvrir FR-NEW-008 par le chemin
légitime ; FR-NEW-001 traite les noms de périphériques Windows et les espaces et points finaux ;
`InvalidIdentifier` hérite explicitement de `ValueError` ; le décompte des gestionnaires passe
partout à 22 ; la couverture par exigence est recomptée sur ce que chaque test asserte
réellement, et les quatre exigences sous le seuil de trois sont annoncées plutôt que maquillées.

**Trajectoire des trois rounds : 9, puis 7, puis 2 constats bloquants.** Chaque round a fermé
les précédents sans en rouvrir, et les deux derniers sont des défauts de **tests**, non
d'exigences : un test qui ne pouvait pas passer, et une exigence sans test sur son chemin
légitime. C'est l'inverse du motif qui avait fait échouer le parapluie, où chaque round
découvrait une catégorie de faille nouvelle. La scission a donc produit ce qu'elle visait.

**Ce que le round 3 a trouvé en construisant le correctif.** L'auditeur a écrit une
implémentation minimale conforme aux neuf exigences dans un arbre de travail jetable, a rejoué
les treize tests des deux côtés, puis la suite existante. Résultat : **9 échecs et 295
réussites**, identiques à ce que la section 9.3 annonçait, avec les mêmes identifiants de test.
Et un défaut que deux rounds de mesure n'avaient pas révélé : **E2E-006 ne pouvait pas passer**,
pas même sur un correctif correct, parce que `ASGITransport` met en tampon le corps entier et
que `/stream` n'en a pas. Sixième façon, sur ce lot et son parapluie, dont un test de sécurité
peut ne pas fonctionner, et la première où le défaut est qu'il ne peut jamais devenir vert.

À l'issue du round 3, le document était escaladé : plafond de trois rounds atteint, et les deux
constats corrigés mais non vérifiés. L'utilisateur a signé un round 4 de confirmation, dont le
résultat est ci-dessous. Cette escalade est donc close.

**Drift registered :** DRIFT-001 à DRIFT-003 au round 1, DRIFT-004 et DRIFT-005 au round 3.

**Amendments applied, round 2 :** FR-NEW-009 est ajoutée et E2E-012 avec elle ; la ligne
`state_manager.py:248` du balayage passe de « sûr » à « vulnérable » ; E2E-005, E2E-010 et
E2E-011 sont corrigés sur les trois points mesurés ci-dessous ; le montage commun devient
normatif et impose le monkeypatch du singleton plutôt qu'une variable d'environnement, ainsi
qu'une enveloppe `wait_for` ; E2E-003 gagne le cas limite de la borne haute ; le vecteur CVSS
passe à 8.8 en tenant compte de la requête inter-site ; la section 9.3 porte le résultat mesuré
de 9 échecs sur 304 ; la section 14 impose de livrer FR-NEW-005 et FR-NEW-009 ensemble.

**Ce que l'audit a trouvé en construisant le correctif.** L'auditeur n'a pas seulement sondé le
code existant : il a écrit un correctif minimal conforme aux exigences, l'a appliqué dans un
arbre de travail jetable, et a rejoué les tests des deux côtés. Quatre résultats qu'aucune
relecture n'aurait donnés :

1. **Le correctif créait lui-même une faille.** Une fois `project_dir()` validant, `GET /`
   lève `InvalidIdentifier` sur `projects/_uploads/` et rend 500 **à chaque requête**, de façon
   permanente et non authentifiée. C'est FR-NEW-009, et c'est la seule exigence de ce document
   qui répare le correctif plutôt que le code d'origine.
2. **E2E-011 était vert sur du code vulnérable**, alors que ses deux attaques réussissaient :
   `validate-map` crée un commit, `rollback` le défait, les deux appels s'annulent et les
   empreintes relues à la fin sont identiques. Il fallait mesurer l'effet **entre** les deux.
3. **E2E-005 ne pouvait jamais passer** : il assertait la conservation de l'identifiant rendu
   par le modèle, que `src/tgi/agents/scenario_generator.py:142` remplace systématiquement.
4. **E2E-010 se suspendait au lieu d'échouer** : `GET /projects/%2E%2E/stream` rend un flux SSE
   sans fin, et le dépôt n'a pas de `pytest-timeout`.

Cinq fois de suite, sur ce lot et son parapluie, un test de sécurité écrit de bonne foi s'est
révélé ne pas attaquer, et pour cinq raisons distinctes. DEC-018 est renforcée en conséquence :
la mesure doit porter sur le code corrigé **autant** que sur le code vulnérable, un test qui ne
peut pas devenir vert étant aussi inutile qu'un test qui ne peut pas être rouge.

**Amendments applied, round 1 :** FR-NEW-005 est réécrite, la validation descendant dans
`StateManager.project_dir()` et `GitService.repo_dir()` au lieu d'être une assertion syntaxique
sur `src/tgi/tgi.py`, lequel ne compose aucun chemin ; FR-NEW-008 est ajoutée ; l'expression du
`test_id` devient `^(?!\.+$)[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$` ; E2E-002, E2E-008 et E2E-010
sont réécrits ; E2E-011 est ajouté ; E2E-006 et E2E-009 reçoivent les préconditions et
l'assertion qui leur manquaient ; le vecteur CVSS passe de `AV:A ... C:N` 8.2, arithmétiquement
faux et sous-évalué, à `AV:L ... C:H` 8.4 ; le décompte des gestionnaires passe de 19 à 22 ;
les sections 1, 2.1 et 9.3 sont corrigées.

**Ce que l'audit a trouvé et que personne n'avait vu.** L'auditeur a écrit une sonde et l'a
exécutée contre l'application réelle plutôt que de raisonner sur le code. Trois résultats :

1. **Un puits de sous-processus**, absent du balayage. `GitService.rollback()` exécute
   `git reset --hard <hash>` avec `cwd=repo_dir(project_id)`
   (`src/tgi/services/git_service.py:136` et `:41-44`). Un `project_id` valant `..` fait reculer
   le `HEAD` du dépôt du serveur lui-même. C'est ce puits qui fait passer la confidentialité de
   `C:N` à `C:H`, et il est désormais couvert par E2E-011.
2. **E2E-002 ne pouvait pas passer, même après correction.** Son égalité portait sur tout
   `tmp_path`, où le serveur écrit ses journaux pendant le test. Et ses charges étaient trop
   profondes : `../../../etc/passwd.md` lève `FileNotFoundError` et n'écrit rien, donc ne
   démontre aucun confinement. La bonne profondeur, mesurée, est `../../`.
3. **E2E-008 était vert sur l'effet.** `update_test` n'écrit que si l'identifiant existe déjà
   dans l'état (`src/tgi/services/state_manager.py:198`), et le test ne semait aucun leurre.

C'est la quatrième fois, sur ce lot et son parapluie, qu'un test de sécurité écrit de bonne foi
se révèle vert avant le correctif, et la première où la cause est que le puits refuse d'écrire
plutôt que la charge d'arriver. La leçon consignée en DEC-018 : un test de traversée n'est
valide que **mesuré contre le code non corrigé**, jamais raisonné.

**Drift registered :** DRIFT-001 à DRIFT-003.

## 19. Implementation Drift Register

#### DRIFT-004: les noms de périphériques Windows ne sont pas mesurés
- **Spec says:** FR-NEW-001 traite désormais `CON`, `NUL`, `COM1` et les espaces et points
  finaux, et E2E-004 en porte les cas.
- **Code does:** ces cas ne sont **pas mesurés**. Les trois audits ont tourné sous macOS, où ces
  noms n'ont aucune signification particulière et où le test est `skipif`. Le raisonnement
  s'appuie sur `src/tgi/services/doc_parser.py:120`, une lecture synchrone dans un gestionnaire
  asynchrone, et sur `WINDOWS.md:91` qui documente `tgi.bat`.
- **Nature:** missing capability, non vérifiée
- **Resolution during implementation:** exécuter E2E-004 au moins une fois sur un poste Windows
  avant de clore, ou déclarer la cible Windows hors périmètre de ce lot et l'inscrire au
  backlog.
- **Detected by:** E2E-004, mais **seulement sous Windows** ; ailleurs il est ignoré. C'est la
  raison pour laquelle cette entrée existe plutôt qu'une confiance dans le test.
- **Blocks which requirement:** FR-NEW-001 sur la cible Windows uniquement
- **Status:** open

#### DRIFT-005: six exigences restent sous trois tests distincts
- **Spec says:** la règle de suffisance demande au moins trois tests par exigence.
- **Code does:** recompté au round 4 sur ce que les tests vérifient réellement et non sur leurs
  étiquettes, **six** exigences sont sous le seuil : FR-NEW-003 en a 1, FR-NEW-005 en a 1,
  FR-NEW-006 un seul test à trois cas, FR-NEW-007 en a 1, FR-NEW-008 en a 1, FR-NEW-009 en a 1.
  Les rédactions précédentes annonçaient quatre, en comptant des références portées par des
  tests qui n'vérifient rien à leur sujet.
- **Nature:** false statement, corrigé en énoncé mais pas en couverture
- **Resolution during implementation:** ne pas étiqueter des tests qui n'vérifient rien pour
  atteindre le seuil, ce que les rounds précédents avaient commencé à faire. Si la couverture
  doit monter, ce sont de vrais tests qu'il faut écrire, et la section 12.1 dit lesquels
  manquent.
- **Detected by:** le recomptage de la section 12.1, refait à chaque round du gate.
- **Blocks which requirement:** aucune
- **Status:** open

#### DRIFT-001: la saturation disque n'est pas fermée par la seule borne de taille
- **Spec says:** FR-NEW-006 ferme la part `A:H` du vecteur.
- **Code does:** la borne empêche un dépôt unique démesuré, mais rien ne limite le **nombre** de
  dépôts de 50 Mio. Il n'existe aucun compteur ni aucune limitation de débit dans le dépôt :
  `rg -n 'rate.?limit|slowapi|throttl' src/tgi/` ne rend rien, et la route de dépôt
  (`src/tgi/tgi.py:267-282`) n'en porte pas. De plus Starlette déverse le corps sur disque avant
  que le gestionnaire ne s'exécute, donc la borne de FR-NEW-006 agit **après** une écriture
  temporaire de la taille reçue.
- **Nature:** missing capability
- **Resolution during implementation:** le risque résiduel est désormais écrit en section 7.2.
  Ouvrir une entrée de backlog pour une limitation de débit, et ne pas prétendre que `A:H` est
  fermé.
- **Detected by:** aucun test automatique ne mesure une saturation, et c'est dit plutôt que
  masqué. Le contrôle est documentaire : la section 7.2 porte un paragraphe
  « Risque résiduel assumé », dont la présence se vérifie à la relecture du gate. Cette entrée
  reste de nature A, et non promue en F, parce qu'aucun utilisateur ni consommateur de contrat
  n'observe de différence entre deux implémentations : seul le document change.
- **Blocks which requirement:** aucune, informationnel sur la portée de FR-NEW-006
- **Status:** open

#### DRIFT-002: `project_dir()` crée le dossier qu'il résout
- **Spec says:** un identifiant bien formé mais absent rend un 404 sans effet.
- **Code does:** `src/tgi/services/state_manager.py:67` fait `d.mkdir(parents=True, exist_ok=True)`
  dans `project_dir()`, donc une lecture crée le dossier. Mesuré : sonder
  `GET /projects/ffffffffffff` crée `projects/ffffffffffff/`.
- **Nature:** bypassed abstraction
- **Resolution during implementation:** sortir le `mkdir` de `project_dir()` et le porter dans
  `create()` seul, qui est le seul appelant qui doive créer.
- **Detected by:** E2E-009, dont la dernière assertion est `projects/ffffffffffff` n'existe pas.
- **Blocks which requirement:** FR-NEW-002
- **Status:** open

#### DRIFT-003: `git_service.py` n'est pas inchangé
- **Spec says:** la première rédaction de la section 9.1 classait `git_service.py` « Inchangé »,
  confiné par la seule validation à la frontière HTTP.
- **Code does:** `GitService.repo_dir()` (`src/tgi/services/git_service.py:36`) compose
  `Path(settings.projects_dir) / project_id` de son côté, et `rollback()` l'emploie comme `cwd`
  d'un sous-processus (`:136`). La validation à la frontière ne couvre pas un appelant interne.
- **Nature:** false statement
- **Resolution during implementation:** 9.1 porte désormais « Modification », et FR-NEW-005
  descend la validation dans `repo_dir()`.
- **Detected by:** E2E-010, qui vérifie que `GitService().repo_dir("..")` lève
  `InvalidIdentifier`.
- **Blocks which requirement:** FR-NEW-005
- **Status:** open
