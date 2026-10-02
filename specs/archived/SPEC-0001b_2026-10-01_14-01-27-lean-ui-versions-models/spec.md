# Test Interface — interface lean, versions et table de modèles

> Generated on: 2026-10-01
> Id: SPEC-0001b
> Nature: FEAT
> Depth: L
> Depth evidence: 3 modules touchés (`src/tgi/tgi.py` 24 routes, `src/tgi/templates/` 9 gabarits, `src/tgi/services/`), un nouveau modèle de persistance versionnée, 70 exigences (62 FR-NEW, 3 FR-MOD, 5 FR-DEL). Escaladé depuis M après l'ajout des versions et de la table de modèles ; l'escalade est à sens unique.
> Status: Draft
> Type: Evolution Specification
> From backlog: n/a
> Split: not split
> Parent: SPEC-0001
> Depends on: SPEC-0001a
> Security: internal finding
> CVSS: 8.2 — AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H, coté et fermé par SPEC-0001a
> Affected: tous les builds déployés à ce jour
> Fixed in: unreleased

## 1. Executive Summary

L'outil lit une spécification fonctionnelle détaillée (SFD) et produit un cahier de tests
au format Excel. Son utilisatrice, Véronique Bertail (équipe TRA / recette, Euro-Information),
s'en sert en production depuis juin 2026 sur trois qualifications successives, et la dernière
a produit environ 700 lignes de cas de tests.

L'interface actuelle lui impose un parcours de 24 routes, 9 gabarits et 7 onglets pour
obtenir un fichier. Cet incrément la remplace par un parcours en deux gestes, déposer puis
lancer, et ajoute les trois capacités qu'elle a demandées et qui n'existent pas : des
**versions numérotées** de la génération, l'**édition des prompts** avant exécution, et une
**table de modèles** éditable depuis l'interface.

Il rend aussi un projet réellement autoportant : aujourd'hui le document déposé est écrit
dans un dossier partagé hors du projet, donc zipper un projet en perd la source.

Source du besoin : la note de réunion du 18 septembre 2026, 1:1 Véronique Bertail / Sébastien
Morand, et la planche « Propositions d'améliorations IA (V8) » transmise ensuite.

## 2. Current State (MANDATORY, every depth)

### 2.1 How it works today

**Parcours.** L'utilisatrice dépose un fichier depuis `base.html` vers `POST /upload`
(`src/tgi/tgi.py:267`), est redirigée vers `/projects/{id}` (`src/tgi/tgi.py:310`) qui rend
`project.html`. La lecture du document tourne en tâche de fond (`src/tgi/tgi.py:306-308`). Quand
l'événement `distil_done` arrive, elle doit ouvrir l'onglet CARTE puis cliquer « Je valide la
carte » (`POST /projects/{id}/validate-map`, `src/tgi/tgi.py:353`), ce qui débloque le bouton
« Lancer la génération » (`POST /projects/{id}/run`, `src/tgi/tgi.py:368`). Ce dernier renvoie
409 si la carte n'est pas validée (`src/tgi/tgi.py:375`). Le résultat se récupère en zip de
7 fichiers (`src/tgi/tgi.py:467-509`) ; aucune route ne sert le xlsx seul.

**Décompte.** 24 routes dans `src/tgi/tgi.py`, 9 gabarits dans `src/tgi/templates/`,
**7 onglets** déclarés dans `src/tgi/templates/project.html:356-364` : `doc` « 📄 DOC »,
`map` « 🧭 CARTE », `requirements` « 📋 EXIGENCES », `scenarios` « 🎬 SCÉNARIOS & TESTS »,
`tests` « 🔍 RECHERCHE », `chat` « 💬 CHAT », `history` « 🕑 HISTORIQUE ».

**Document source.** Les octets déposés sont écrits dans
`projects/_uploads/<filename>` (`src/tgi/tgi.py:276-282`), un dossier **partagé par tous les
projets**. `state.json` ne garde qu'un chemin vers ce fichier (`src/tgi/services/state_manager.py:110`).
Deux conséquences mesurées : un dossier de projet zippé perd sa source, et deux projets
alimentés par un fichier de même nom s'écrasent mutuellement, le chemin étant indexé par nom
de fichier.

**Persistance.** `projects/<project_id>/` avec `project_id` un `uuid4`
(`src/tgi/services/state_manager.py:107`), le dossier étant résolu par `project_dir()`
(`src/tgi/services/state_manager.py:65-68`), contenant `state.json`
(`src/tgi/services/state_manager.py:87-98`), `.gitignore` (`src/tgi/services/git_service.py:64-66`),
`.git/` (`src/tgi/services/git_service.py:68-70`) et `tests/<test_id>.json`
(`src/tgi/services/state_manager.py:207`). `list_projects()` **balaye le répertoire** et
retient les dossiers portant un `state.json` (`src/tgi/services/state_manager.py:244-248`) :
aucun index, aucun registre.

**Versions.** ABSENT. Relancer une génération fusionne les résultats en place par identifiant
(`src/tgi/services/state_manager.py:170-182`), donc écrase. Ce qui existe à la place est un
**dépôt git par projet** (`src/tgi/services/git_service.py:36`, `init()` à `:55-80`), commité
à la création (`src/tgi/tgi.py:302`) et à chaque édition humaine (`src/tgi/tgi.py:403`,
`:414`, `:430`), avec un `rollback()` qui est un `git reset --hard`
(`src/tgi/services/git_service.py:131-141`) exposé en `src/tgi/tgi.py:459`. Les versions y sont
des empreintes de commit, jamais des numéros.

**Modèles.** Configuration par variables d'environnement uniquement : `TGI_LLM_BASE_URL`
(`src/tgi/config.py:112`), `TGI_LLM_API_KEY` (`:113`), `TGI_MODEL_GENERATOR` (`:119`), via
`Settings`. `LLMClient` est un singleton de module (`src/tgi/services/llm.py:475`) dont
`base_url` et `api_key` sont figés à la construction (`src/tgi/services/llm.py:243`). Le nom de
modèle, lui, est déjà passé par appel. `LLMClient.list_models()` existe
(`src/tgi/services/llm.py:432`) mais **aucune route ne l'expose**.

**Détection d'absence de modèle.** Partiellement présente, et c'est une nuance qui change la
portée de NFR4. `Settings.configuration_problems()` (`src/tgi/config.py:158-172`) compare déjà
`llm_api_key` au littéral `"changeme"` (`src/tgi/config.py:15` et `:113`) et **signale** le
problème. Mais c'est un avertissement consultatif : rien ne le consulte avant de lancer une
génération, et aucune route ne refuse pour ce motif. Le mécanisme existe, le refus n'existe pas.

**Prompts.** Aucune interface de consultation ni d'édition. ABSENT dans
`src/tgi/templates/` comme dans `src/tgi/tgi.py`.

### 2.2 Existing specifications governing this area

Aucune. Le répertoire `specs/` n'existait pas avant ce document ; `SPEC-0001` est le premier.
Les règles de conception en vigueur sont dans `AGENTS.md` et `.agent_docs/pipeline.md`, et une
seule entre en conflit avec cet incrément, traitée en section 13.

### 2.3 Existing test coverage

Commande de test exacte : `uv run pytest -v` (`Makefile:91-99`). Couverture plancher 80,
`fail_under = 80` (`pyproject.toml:159`). `make check` enchaîne lint, format-check, typecheck,
security, test-cov (`Makefile:147`).

La suite compte **304 tests**, chiffre pris sur `uv run pytest --collect-only -q` et non sur un
comptage par expression régulière : `rg -c '^(async )?def test_' tests/` en annonce 305, parce
qu'il compte en trop la fixture `test_settings` (`tests/conftest.py:45-46`), dont le nom commence
par `test_` sans en être un. Le détail qui compte pour cet incrément :

| Fichier | Fonctions | Sort dans cet incrément |
|---|---|---|
| `tests/functional/test_api.py` | 36 | **À réécrire** : exerce le parcours et les routes supprimés |
| `tests/test_state_manager.py` | 16 | **À réécrire** : l'axe version change la forme de l'état |
| `tests/test_state_races.py` | 3 | **À réécrire** : mêmes raisons |
| `tests/test_git_service.py` | 7 | **À supprimer** avec `git_service.py` |
| `tests/test_llm.py` | 42 | À étendre : construction par exécution, FR-MOD-002 |
| `tests/test_config.py` | 17 | À étendre : `config_dir`, refus sans modèle |
| `tests/test_progress.py` | 10 | À adapter : progression portée par version |
| `tests/test_workbook.py` | 6 | Inchangé |
| `tests/test_coverage_report.py` | 9 | Inchangé |
| `tests/test_grammar.py` | 23 | Inchangé |

`src/tgi/deliverable.py` n'est importé par aucun fichier de test : **0 test direct**, alors que
FR-NEW-035 en dépend pour le titre du cas d'utilisation. C'est le seul trou de couverture
réellement gêlant de cet incrément.

Dit platement : contrairement à ce qu'on pourrait croire d'une refonte d'interface, le parcours
remplacé **est** couvert, par les 36 tests de `tests/functional/test_api.py`. Ces tests tombent
avec le parcours, et c'est volontaire : ils décrivent le comportement que DEC-002, DEC-003 et
DEC-004 suppriment. La non-régression ne peut donc pas servir de garde-fou, non par absence de
tests mais parce que le contrat observable change. C'est la suite `E2E-` de la section 12 qui
tient lieu de contrat.

### 2.4 Class Sweep

> **Ce balayage appartient à SPEC-0001a et n'est pas redéroulé ici.** La classe,
> « une donnée fournie par le client atteint une opération de système de fichiers qui construit
> un chemin par concaténation (CWE-22) », ses six recherches et la disposition de ses 40
> occurrences sur le code existant sont dans la section 2.4 de
> `specs/SPEC-0001a_2026-10-01_14-01-27-cwe22-path-containment/spec.md`. SPEC-0001a livre les
> primitives `safe_basename`, `validated_project_id`, `validated_version` et
> `validated_test_id` dans `src/tgi/services/paths.py`, et c'est la raison du
> `Depends on: SPEC-0001a` du bloc de tête.
>
> Ce qui reste à la charge du présent document est **la même classe sur les sources que lui
> seul introduit** : les 9 nouvelles routes, les deux paramètres de requête de `GET /` et la
> clé de prompt du corps de `POST .../runs`. Elles sont énumérées ci-dessous et disposées par
> FR-NEW-040, qui n'invente plus de contrôle mais applique celui de SPEC-0001a.

### Sources que cet incrément ajoute

| Nouvelle source | Puits atteint | Verdict | Disposition |
|---|---|---|---|
| `{project_id}` de `POST /api/v1/projects/{project_id}/runs` | crée `v<n>/`, `prompts/`, `state.json` | **vulnérable** : écriture hors du répertoire | FR-NEW-040, test E2E-101 |
| `{project_id}` de `GET .../source`, `POST .../source`, `GET .../prompts` | lecture et écriture sous le projet | **vulnérable** | FR-NEW-040, tests E2E-094, E2E-101 |
| `{version}` de `GET .../versions/{version}` et de ses quatre routes filles `/events`, `/xlsx`, `/qc`, `/qc.xlsx` | lecture sous la version | **vulnérable** | FR-NEW-040, test E2E-101 |
| `{version}` de `DELETE .../versions/{version}` | **`rmtree`**, le puits le plus destructeur du lot | **vulnérable** | FR-NEW-040, test E2E-095 |
| `project` et `version`, paramètres de requête de `GET /` | résolution de projet et de version | **vulnérable** : source que le balayage du code existant ne pouvait pas voir | FR-NEW-040, test E2E-096 |
| clé de `prompts` dans le corps de `POST .../runs` | `v<n>/prompts/<clé>.md` | **vulnérable** : segment venu du corps | FR-NEW-019, par liste blanche des trois clés, test E2E-007 |
| `{name}` de `DELETE /api/v1/models/{name}` | aucun : sert de clé dans une liste JSON, le seul chemin écrit étant `models.json`, nom littéral de FR-NEW-026 | **sûr** | aucune |

Aucune occurrence n'est reportée au backlog.

### Rappel de l'état existant, pour mémoire

**Class:** un nom de fichier ou un identifiant fourni par le client atteint une opération de
système de fichiers qui construit un chemin par concaténation (CWE-22, path traversal).

**Searches run:**
1. `rg -n 'Path\(.*\)\s*/\s*[a-z_"]' src/tgi/` — couvre l'idiome de concaténation par
   l'opérateur `/` de `pathlib`, qui est la forme employée partout dans ce dépôt. **4 occurrences.**
2. `rg -n 'filename|file\.filename|project_id|test_id|scenario_id' src/tgi/tgi.py src/tgi/services/` —
   couvre les sources non fiables elles-mêmes, pour attraper un puits que la première recherche
   manquerait (`open()` direct, `os.path.join`, f-string). 189 lignes sur 3 fichiers ; toutes
   remontent aux deux sources déjà listées, `file.filename` et les identifiants d'URL, et
   aucune n'atteint un puits absent de la recherche 3.
3. `rg -n 'os\.path\.join|open\(|shutil\.|rmtree|unlink|mkdir\(' src/tgi/` — couvre les puits
   restants, y compris la suppression, qui est le puits que la fonctionnalité « supprimer une
   version » introduit. **21 occurrences**, toutes disposées ci-dessous.
4. `rg -n '/\s*f"' src/tgi/` — couvre le chemin construit par f-string, idiome que la classe de
   caractères de la recherche 1 ne peut pas atteindre. **5 occurrences.** C'est cette recherche
   qui a révélé `state_manager.py:188`, où un segment de chemin vient de la sortie du modèle.
5. `rg -n 'project_dir\(|tests_dir\(|state_path\(|repo_dir\(' src/tgi/` — part de la **source**,
   l'identifiant de projet, et suit ses points d'appel plutôt que ses puits. **12 occurrences**,
   qui sont des appels aux aides de chemin déjà disposées, plus les trois sites de
   `git_service.py` listés ci-dessous.
6. `rg -n 'read_text|write_text|read_bytes|write_bytes|\.glob\(|rglob|iterdir\(|\.rename\(|os\.remove' src/tgi/ -g '*.py'` —
   part du **puits** plutôt que de la source, pour attraper les lectures et énumérations que les
   cinq précédentes ne couvrent pas. **11 occurrences**, disposées ci-dessous.

Idiome non recherché et pourquoi : les gabarits Jinja ne construisent aucun chemin disque, ils
ne produisent que des URL ; `src/tgi/templates/` est hors périmètre de cette classe.

| Occurrence | Verdict | Disposition |
|---|---|---|
| `src/tgi/tgi.py:276-282` — `projects/_uploads/<file.filename>` | **vulnérable** : `file.filename` vient du client, aucune normalisation avant concaténation | FR-NEW-003 |
| `src/tgi/services/state_manager.py:66` — `Path(settings.projects_dir) / project_id` | **vulnérable** : `project_id` vient du chemin d'URL sur toutes les routes projet, aucune validation de forme | FR-NEW-040 |
| `src/tgi/services/state_manager.py:188` — `tests_dir / f"{test.get('id')}.json"` | **vulnérable** : le segment vient de la sortie du modèle, non validée | FR-NEW-040 |
| `src/tgi/services/state_manager.py:207` — `tests_dir / f"{test_id}.json"` | **vulnérable** : `test_id` vient du chemin d'URL (`src/tgi/tgi.py:396`) | FR-NEW-040 |
| `src/tgi/services/git_service.py:36` — `Path(settings.projects_dir) / project_id` | **vulnérable**, même source | supprimé par FR-DEL-002 |
| `src/tgi/services/state_manager.py:67` et `:75` — `mkdir(parents=True)` | **vulnérable par héritage** : crée le dossier dérivé de `project_id`, donc un identifiant traversé créerait un dossier hors périmètre | FR-NEW-040 |
| `src/tgi/services/state_manager.py:82`, `:96`, `:186`, `:189`, `:208` — `open()` et `mkdir()` sous `tests/` | **vulnérable par héritage** : mêmes deux sources | FR-NEW-040 |
| `src/tgi/services/state_manager.py:94` — `path.with_name(f"{path.name}.{uuid4().hex}.tmp")` | **vulnérable par héritage** : le fichier temporaire de l'écriture atomique dérive de `state_path(project_id)`, donc de la même source | FR-NEW-040 |
| `src/tgi/services/state_manager.py:70-71` et `:73-74` — `state_path()` et `tests_dir()` | **vulnérable par héritage** : les deux autres aides de chemin construites sur `project_id`, listées pour la même raison que `git_service.py:35` | FR-NEW-040 |
| `src/tgi/services/state_manager.py:41` — `source.replace(target)` | **sûr** : les deux chemins sont dérivés en interne de `state_path()`, aucune entrée client ne s'y insère ; contrôlé en amont par FR-NEW-040 qui valide `project_id` | FR-NEW-040 |
| `src/tgi/tgi.py:277` et `:280` — `mkdir()` puis `open()` du fichier déposé | **vulnérable** : même occurrence que la première ligne, vue du côté du puits | FR-NEW-003 |
| `src/tgi/tgi.py:167` — `log_dir.mkdir()` | **sûr** : `log_dir` vient de `Settings.log_dir` (`src/tgi/config.py:174-181`), configuration serveur, jamais du client | aucune |
| `src/tgi/tgi.py:180` — `Path(app_settings.projects_dir).mkdir()` | **sûr** : racine de configuration, sans segment client | aucune |
| `src/tgi/config.py:91` — `Path(local_app_data) / app_name / "logs"` | **sûr** : `local_app_data` vient de l'environnement du processus et `app_name` est une constante de configuration ; aucune des deux n'est atteignable par une requête HTTP | aucune |
| `src/tgi/config.py:139` — `projects_dir` par défaut `"./projects"` | **sûr** : valeur de configuration serveur, lue par `Settings` depuis l'environnement | aucune |
| `src/tgi/logging_config.py:49` — `directory.mkdir()` | **sûr** : reçoit `Settings.log_dir`, pas d'entrée client | aucune |
| `src/tgi/tracing.py:58` — `oldest.unlink()` | **sûr** : `oldest` vaut `self._path.with_name(...)`, dérivé du chemin de traces fixé à l'initialisation ; rotation interne, aucun segment client | aucune |
| `src/tgi/tracing.py:124` — `directory.mkdir()` | **sûr** : même répertoire de traces | aucune |
| `src/tgi/validate.py:382` — `log_dir.mkdir()` | **sûr** : outil en ligne de commande `tgi-validate`, hors surface HTTP | aucune |
| `src/tgi/validate.py:424` — `shutil.rmtree(workdir)` | **sûr** : `workdir` est un répertoire temporaire créé par l'outil lui-même, hors surface HTTP | aucune |
| `src/tgi/services/git_service.py:40` et `:60` — `repo = self.repo_dir(project_id)` | **vulnérable par héritage** : les deux sites où un `project_id` client devient un chemin | supprimé par FR-DEL-002 |
| `src/tgi/services/git_service.py:61` — `repo.mkdir(parents=True)` | **vulnérable par héritage** : crée le dossier dérivé de `project_id` | supprimé par FR-DEL-002 |
| `src/tgi/services/git_service.py:25` — `shutil.which("git")` | **sûr** : argument littéral, ne construit aucun chemin à partir d'une entrée | aucune |
| `src/tgi/stats.py:75` — `otel_path.open()` | **sûr** : `otel_path` vient de `Settings.log_dir` (`src/tgi/config.py:174-181`), configuration serveur ; outil en ligne de commande `tgi-stats`, hors surface HTTP | aucune |
| `src/tgi/tracing.py:72` — `self._path.open("a")` | **sûr** : `self._path` est le fichier de traces résolu à l'initialisation depuis `Settings.log_dir`, aucun segment client | aucune |
| `src/tgi/tracing.py:62-63` — `replace()` de rotation | **sûr** : renomme des fichiers énumérés par `range(self._backup_count - 1, 0, -1)` et `with_name()`, donc des noms entièrement calculés, jamais reçus | aucune |
| `src/tgi/tracing.py:125` et `src/tgi/logging_config.py:50` et `src/tgi/validate.py:390` — chemins construits par f-string | **sûr** : les trois dérivent de `Settings.log_dir` (`src/tgi/config.py:174-181`), configuration serveur, et aucune n'est atteignable par une requête | aucune |
| `src/tgi/services/git_service.py:35` — `def repo_dir` | **vulnérable par héritage** : la définition de l'aide de chemin elle-même | supprimé par FR-DEL-002 |
| `src/tgi/services/git_service.py:65` — `aiofiles.open(gitignore, "w")` | **vulnérable par héritage** : écrit sous le dossier dérivé de `project_id` | supprimé par FR-DEL-002 |
| `src/tgi/services/state_manager.py:248` — `base.iterdir()` puis `(d / "state.json").exists()` | **sûr aujourd'hui, à durcir** : énumère le répertoire sans y insérer d'entrée client, mais ne filtre ni les liens symboliques ni les intrus, ce qui est la faille que FR-NEW-032 ferme | FR-NEW-032 |
| `src/tgi/services/doc_parser.py:120` — `path.read_text()` | **vulnérable par héritage** : la lecture réelle du chemin construit à `src/tgi/tgi.py:276-282` | FR-NEW-003 |
| `src/tgi/stats.py:152-154` — `projects_dir.glob("*/state.json")` puis `read_text` | **sûr** : motif littéral, aucun segment reçu ; outil en ligne de commande `tgi-stats`, hors surface HTTP | aucune |
| `src/tgi/config.py:41` — `env_file.read_text()` | **sûr** : `env_file` vaut `Path(".env")`, passé depuis `src/tgi/config.py:156` et `:171`, donc un nom littéral résolu **relativement au répertoire courant**, sans aucun segment reçu d'une requête. À noter, puisque la convention du dépôt est de résoudre les ressources par `Path(__file__)` : celle-ci y échappe délibérément, un `.env` étant censé suivre le répertoire de lancement | aucune |
| `src/tgi/validate.py:188` — `SAMPLE_PATH.read_text()` | **sûr** : `SAMPLE_PATH` vaut `Path(__file__).parent / "samples" / "sample_spec.md"` (`src/tgi/validate.py:38`), constante résolue par rapport au module ; outil en ligne de commande, hors surface HTTP | aucune |
| `src/tgi/stats.py:296` — `log_dir.glob("*-otel.log")` | **sûr** : motif littéral sur le répertoire de traces issu de `Settings.log_dir` ; outil en ligne de commande, hors surface HTTP | aucune |
| `src/tgi/agents/{distiller,scenario_generator,coverage}.py` et `src/tgi/agents/orchestrator.py:308` — `_PROMPT_PATH.read_text()` | **sûr aujourd'hui** : constante résolue par `Path(__file__)`. FR-NEW-016 et FR-NEW-017 y ajoutent une lecture par version, dont le segment `v<n>` est contraint par FR-NEW-040 | FR-NEW-040 |
| `src/tgi/services/doc_parser.py:62-70` — reçoit un chemin déjà construit | **sûr** : ne concatène rien, l'appelant seul construit le chemin, contrôlé en `src/tgi/tgi.py:276-282` | couvert par FR-NEW-003 |
| `src/tgi/tgi.py:182` — `Jinja2Templates(directory=str(_TEMPLATES_DIR))` | **sûr** : `_TEMPLATES_DIR` est résolu par `Path(__file__)` et tous les noms de gabarits passés à `TemplateResponse` sont des littéraux, aucun ne vient d'une requête | aucune |
| `src/tgi/stats.py:346` — `default=Path(settings.projects_dir)` | **sûr** : valeur par défaut d'un argument de la commande `tgi-stats`, hors surface HTTP et hors de la classe, qui ne vise que l'entrée client | aucune |
| `src/tgi/tgi.py:218` — `application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)))` | **sûr** : un chemin d'URL client atteint bien une lecture disque, mais `_STATIC_DIR` vaut `_MODULE_DIR / "static"` (`src/tgi/tgi.py:52`), résolu par `Path(__file__)`, et `StaticFiles` de Starlette impose lui-même le confinement sous ce répertoire. Aucune des six recherches ne l'atteint, ce qui est précisément pourquoi il est listé ici : un balayage qui ne trouve que ce qu'il cherche n'est pas un balayage | aucune |

**Sources que cet incrément ajoute, et qui appartiennent à la même classe.** Un balayage qui ne
regarde que le code existant manque les puits que la spécification elle-même crée.

| Nouvelle occurrence | Verdict | Disposition |
|---|---|---|
| La **clé de `prompts`** du corps de `POST .../runs` atteint `v<n>/prompts/<clé>.md` | **vulnérable** : segment de chemin venu du corps de la requête | FR-NEW-019, par liste blanche des trois clés, test E2E-007 |
| Les paramètres `project` et `version` de `GET /` atteignent le dossier de projet et de version | **vulnérable** : segments venus de la chaîne de requête | FR-NEW-040 étendu, test E2E-096 |
| Le `version` de `DELETE .../versions/{version}` atteint un `rmtree` | **vulnérable** : le puits le plus destructeur du lot | FR-NEW-040, test E2E-095 |
| Le `name` de `DELETE /api/v1/models/{name}` | **sûr** : sert de clé dans une liste JSON, n'atteint aucun chemin ; le seul chemin écrit est `models.json` lui-même, nom littéral de FR-NEW-026 | aucune |
| L'identifiant de test venu de la **sortie du modèle** | **vulnérable** : hors de portée de FR-NEW-040, qui ne régit que les identifiants reçus du client | FR-NEW-056, qui supprime le puits, test E2E-097 |

Aucune occurrence n'est reportée au backlog : l'occurrence d'origine et toutes celles de la même
classe, existantes comme ajoutées, sont traitées dans ce lot.

## 3. Scope

### 3.1 In Scope

Le parcours complet déposer / éditer les prompts / lancer / suivre / télécharger, les versions
numérotées et leur suppression, la liste des projets, la table de modèles, l'export QC comme
seconde action, et la mise en conformité du stockage avec NFR2.

### 3.2 Out of Scope (Non-Goals)

- L'explicabilité, c'est-à-dire la justification par le modèle de chaque cas de test produit
  (demande n°1 de la note du 18/09). Entrée de backlog séparée.
- La classification MOA / MOE / COMM à l'intérieur de l'agent (demande n°6). Entrée séparée.
- La restructuration du classeur de recette : onglet Scénarii consolidé, renommage des onglets
  par sujet d'exigence (demandes n°3 et n°4). Entrée séparée.
- La phase interactive de clarification avant génération. Backlog.
- L'intégration API directe avec QC, sans Excel intermédiaire. Backlog.
- Les défauts de génération : cas de tests sans lien avec l'exigence référencée, statut
  `Untestable` erroné sur RM04 et RM08, mauvaise lecture de la section 2.2.3. Relèvent de
  `/analysis`, pas d'une spécification de fonctionnalité.
- Toute authentification utilisateur. L'outil reste sans compte ni session.

## 4. User Personas & Actors

| Acteur | Description | Ce qu'il fait ici |
|---|---|---|
| Testeuse recette (Véronique Bertail, équipe TRA) | Prépare les cahiers de recette à partir d'une SFD. Non développeuse. | Tout le parcours décrit en section 5. |
| Binôme recette | Deuxième membre de l'équipe de 2. | Mêmes gestes, éventuellement en parallèle sur un autre projet. |
| Exploitant | Installe l'outil sur un poste Windows ou un serveur. | Fournit `TGI_CONFIG_DIR` et `TGI_PROJECTS_DIR`, rien d'autre : les modèles se saisissent dans l'interface. |

## 4.5 Bounded Contexts

| Context | Scope | Key entities |
|---|---|---|
| Projet | Le document déposé et son identité. Un projet, un fichier source. | `Project`, `SourceDocument` |
| Version | Une exécution du pipeline et ce qu'elle a produit. | `Version`, `PromptSet`, `RunStatus` |
| Configuration modèles | Les points d'accès LLM utilisables. | `ModelEntry`, `ModelStore` |
| Livrable | Les classeurs produits à partir d'une version. | `Workbook`, `QcExport` |

Le mot « version » appartient au contexte Version et désigne une exécution numérotée `v1`,
`v2`. Il ne désigne jamais une version du logiciel, qui se dit « build »
(`src/tgi/build.py`).

## 5. Usage Scenarios

### SC-001: Éditer les prompts avant de générer

**Actor:** Testeuse recette
**Preconditions:** Un projet existe et porte sa source. Au moins un modèle est configuré.
**Flow:**
1. Elle ouvre le projet ; le système affiche les trois prompts **par défaut**, jamais ceux
   d'une version précédente.
2. Elle modifie le prompt `scenario_generator` pour la recette transverse.
3. Elle presse Lancer ; le système crée la version suivante et y écrit les prompts employés.
**Postconditions:** La version porte sur disque les prompts exacts qui l'ont produite. Les
prompts par défaut livrés avec l'outil sont inchangés.
**Exceptions:**
- [EXC-001a]: clé de prompt inconnue → 422, aucune version créée.
- [EXC-001b]: prompt vide ou blanc → 422, le défaut n'est pas écrasé par du vide.
- [EXC-001c]: une génération tourne déjà → 409, l'édition n'est pas appliquée.
**Cross-scenario notes:** l'édition est portée par SC-005 : v2 repart du défaut.

### SC-002: Déposer une SFD, ce qui crée un projet

**Actor:** Testeuse recette
**Preconditions:** Aucune. Un modèle n'est pas nécessaire pour déposer.
**Flow:**
1. Elle dépose `specification_habilitations.md`.
2. Le système crée le dossier du projet, y écrit `project.json` et `source/<nom d'origine>`.
3. Il affiche le projet, sans rien générer.
**Postconditions:** Le dossier est autoportant. Aucun appel modèle n'a eu lieu.
**Exceptions:**
- [EXC-002a]: fichier vide → 400, aucun dossier créé.
- [EXC-002b]: extension non supportée → 415.
- [EXC-002c]: au-delà de 50 Mo → 413, refusé avant toute écriture.
- [EXC-002d]: document illisible → 400, aucun dossier créé.
- [EXC-002e]: disque plein → 507, aucun demi-projet laissé.
- [EXC-002f]: nom de fichier en traversée de chemin → assaini, écrit dans le projet.

### SC-003: Retélécharger le fichier déposé

**Actor:** Testeuse recette
**Preconditions:** Le projet porte sa source.
**Flow:** Elle demande la source ; le système renvoie les octets d'origine.
**Postconditions:** Octets identiques, rien de modifié dans le dossier.
**Exceptions:**
- [EXC-003a]: projet inconnu → 404.
- [EXC-003b]: source effacée à la main → 404 et non 500, le projet reste listé.
- [EXC-003c]: second dépôt sur un projet qui a déjà sa source → 409.

### SC-004: Lancer, suivre, télécharger

**Actor:** Testeuse recette
**Preconditions:** Un projet avec sa source, au moins un modèle configuré.
**Flow:**
1. Elle choisit un modèle et presse Lancer.
2. Le système répond immédiatement avec le numéro de version et exécute en tâche de fond.
3. Une barre de progression avance ; elle voit l'avancement et une estimation.
4. À la fin elle télécharge le xlsx.
**Postconditions:** Le classeur existe dans le dossier de la version. La source n'a pas bougé ;
`project.json` n'a changé que par son compteur `next_version`.
**Exceptions:**
- [EXC-004a]: aucun modèle configuré → 409, aucune version créée.
- [EXC-004b]: point d'accès injoignable → version en échec, message lisible.
- [EXC-004c]: 401 en milieu d'exécution → version en échec, le travail déjà écrit est **conservé**.
- [EXC-004d]: deux onglets lancent le même projet → une seule version, l'autre reçoit 409.
- [EXC-004e]: réponse du modèle illisible trois fois → version en échec, pas de boucle.
- [EXC-004f]: disque plein à l'écriture du classeur → échec, aucun fichier tronqué.

### SC-005: Rejouer l'extraction, versions successives

**Actor:** Testeuse recette
**Preconditions:** Le projet a au moins une version.
**Flow:** Elle relance ; le système crée la version suivante sans toucher aux précédentes.
**Postconditions:** Chaque version garde ses propres résultats, son modèle et ses prompts.
**Exceptions:**
- [EXC-005a]: dossier de version supprimé à la main → disparaît de la liste, les autres vivent.
- [EXC-005b]: `state.json` de version corrompu → listée `corrompue`, n'empêche pas une nouvelle.
- [EXC-005c]: relance après échec → crée bien la suivante.

### SC-006: Supprimer une version

**Actor:** Testeuse recette
**Flow:** Elle supprime une version ; le dossier disparaît.
**Postconditions:** Les autres versions sont intactes, la numérotation n'est jamais réécrite.
**Exceptions:**
- [EXC-006a]: version en cours → 409.
- [EXC-006b]: version inconnue → 404.
- [EXC-006c]: supprimer la seule version → le projet survit avec zéro version et sa source.
- [EXC-006d]: deux suppressions concurrentes → un 204 et un 404.

### SC-007: Rafraîchir la liste des projets

**Actor:** Testeuse recette
**Flow:** Elle rafraîchit ; le système relit le disque.
**Postconditions:** Un dossier copié à chaud apparaît sans redémarrage.
**Exceptions:**
- [EXC-007a]: dossier sans `project.json` → ignoré.
- [EXC-007b]: `project.json` corrompu → listé `corrompu`, pas de 500.
- [EXC-007c]: lien symbolique sortant du répertoire → non listé.

### SC-008: Gérer la table de modèles

**Actor:** Testeuse recette, ou exploitant au premier démarrage
**Flow:** Elle liste, ajoute, retire des entrées `base_url` + clé + nom de modèle.
**Postconditions:** Le fichier de modèles est écrit sur disque par l'outil.
**Exceptions:**
- [EXC-008a]: nom déjà défini → 409.
- [EXC-008b]: `base_url` absente ou de schéma non http(s) → 422.
- [EXC-008c]: fichier de modèles illisible → interface démarre, génération refusée.
- [EXC-008d]: retrait du dernier modèle → la génération repasse en 409.
- [EXC-008e]: deux ajouts concurrents → les deux présents, rien de perdu.

### SC-009: Convertir le résultat au format QC

**Actor:** Testeuse recette
**Preconditions:** Une version terminée avec au moins un test.
**Flow:** Elle demande l'export QC ; le système produit un second classeur.
**Postconditions:** Le classeur de recette est inchangé ; l'export QC est un artefact de plus.
**Exceptions:**
- [EXC-009a]: version en cours → 409.
- [EXC-009b]: aucun test → 409.
- [EXC-009c]: préfixe d'exigence inconnu → `TYPE = INCONNU`, export produit, avertissement rendu.

## 6. Functional Requirements

Casse employée : `snake_case` pour les champs JSON et les clés de configuration, `kebab-case`
pour les segments d'URL, conformément à l'existant (`src/tgi/services/state_manager.py:102-121`).

Les exigences supprimées, `FR-DEL-XXX`, ne portent délibérément ni étiquette EARS ni énoncé
normatif : elles retirent un comportement au lieu d'en prescrire un, et se décrivent par
Description, Reason et Cleanup. Les 65 exigences qui prescrivent un comportement sont toutes en
EARS.

### New Requirements

#### FR-NEW-001 [EARS-E]: Le dépôt crée un projet autoportant
> WHEN un document est reçu sur `POST /api/v1/projects` THE système SHALL créer
> `projects/<project_id>/` contenant `project.json` et `source/<nom assaini>`, et répondre 201.

- **Inputs:** multipart, partie `file`.
- **Outputs:** 201, corps `{"id": str, "name": str, "source_filename": str, "created_at": str}`.
- **Business Rules:** `project_id` est un identifiant hexadécimal de 12 caractères issu de
  `secrets.token_hex(6)`. `name` vaut par défaut le radical du nom de fichier.
  `created_at` est une date ISO 8601 UTC avec suffixe `Z`.
  Si la partie `file` est absente de la requête, c'est la validation de schéma du cadriciel qui
  répond, donc 422 avec le corps que FastAPI produit, `detail` étant une **liste** dont la
  première entrée porte `loc == ["body", "file"]`. Même distinction que pour `base_url` en
  FR-NEW-027 : un champ absent n'est pas un champ invalide, et les deux ne rendent pas le même
  corps.
- **Exact names:** route `POST /api/v1/projects` ; fichier `project.json` ; champs `id`,
  `name`, `source_filename`, `created_at`, `next_version` ; dossier `source/`.
- **Priority:** Must-have

#### FR-NEW-002 [EARS-U]: Le dossier de projet ne référence rien à l'extérieur
> THE système SHALL écrire toute donnée d'un projet sous `projects/<project_id>/` et SHALL NOT
> y stocker de chemin absolu ni de chemin sortant de ce dossier.

- **Business Rules:** aucun index ni registre global. La liste des projets est le balayage du
  répertoire, comportement déjà en place (`src/tgi/services/state_manager.py:244-248`).
- **Priority:** Must-have
- **Rationale:** c'est la condition pour que zipper et dézipper un projet le conserve utilisable.

#### FR-NEW-003 [EARS-E]: Le nom de fichier déposé est assaini par la primitive de SPEC-0001a
> WHEN un nom de fichier est reçu THE système SHALL le faire passer par
> `safe_basename()` de `src/tgi/services/paths.py`, livré par SPEC-0001a, et SHALL NOT écrire
> hors de `projects/<project_id>/source/`.

- **Business Rules:** l'ordre des deux opérations est normatif et dans ce sens : **nom de base
  d'abord, assainissement ensuite**. `../../../etc/passwd.md` donne donc `passwd.md`, et non
  `etc_passwd.md` : tout ce qui précède le dernier séparateur est jeté, jamais aplati. L'ordre
  inverse laisserait passer `.._.._.._etc_passwd.md`, les points étant inoffensifs une fois le
  nom de base pris. Les séparateurs `/` et `\` comptent tous deux, un client Windows pouvant
  envoyer l'un ou l'autre.
  **La liste de substitution est une liste noire, et c'est délibéré.** Une liste blanche du type
  `[A-Za-z0-9._-]` plus lettres Unicode rejetterait l'emoji de
  `spécification_été_📄.docx`, qui est de catégorie Unicode `So` et non une lettre, alors que ce
  nom est légitime et doit survivre tel quel, comme l'exige E2E-016. Seul ce qui est dangereux
  pour un système de fichiers est substitué ; le confinement, lui, est assuré par la prise du
  nom de base, pas par la classe de caractères.
  Un nom réduit à vide après assainissement devient `document`, et il en va de même des deux
  noms de base dégénérés `.` et `..`, qui survivent à la liste noire sans être vides et
  désigneraient sinon le dossier lui-même. Le nom retenu est normalisé en
  NFC. Pour l'en-tête `content-disposition` de FR-NEW-008, le repli ASCII se calcule par
  normalisation NFKD puis retrait de tout caractère non ASCII, ce qui donne
  `specification_ete_.docx` pour l'exemple ci-dessus : l'emoji disparaît sans laisser de `_`,
  celui qui subsiste étant celui qui le précédait dans le nom d'origine.
- **Priority:** Must-have

#### FR-NEW-004 [EARS-O]: Document vide refusé
> IF le fichier déposé fait zéro octet THEN THE système SHALL répondre 400 avec le corps
> `{"detail": "document vide"}` et SHALL NOT créer de dossier.

- **Priority:** Must-have

#### FR-NEW-005 [EARS-O]: Extension non supportée refusée
> IF l'extension du fichier déposé n'est pas dans `.md`, `.txt`, `.docx`, `.pdf` THEN THE
> système SHALL répondre 415 avec `{"detail": "format non supporté: <extension>"}`.

- **Business Rules:** l'extension est reconnue mais le contenu ne s'analyse pas, par exemple un
  `.docx` tronqué : 400 `{"detail": "document illisible"}`, et aucun dossier n'est créé, la
  lecture ayant lieu avant l'écriture.
- **Priority:** Must-have

#### FR-NEW-006 [EARS-O]: Taille maximale
> IF le fichier déposé dépasse 52 428 800 octets THEN THE système SHALL répondre 413 avec
> `{"detail": "document trop volumineux (max 50 Mo)"}` et SHALL NOT écrire sur disque.

- **Business Rules:** la SFD de référence pèse 7 527 741 octets, soit une marge de 6,96 fois.
  Ce document est le `0302 - SFD - Portefeuille et Intervenants _ v5.docx` fourni par
  Euro-Information ; il vit sous `examples/`, qui est dans `.gitignore`, donc la mesure n'est
  pas rejouable depuis le dépôt seul.
- **Priority:** Should-have

#### FR-NEW-007 [EARS-UB]: Le dépôt ne génère rien
> THE système SHALL NOT appeler de modèle ni créer de version lors d'un dépôt.

- **Priority:** Must-have
- **Rationale:** c'est ce qui laisse la place à l'édition des prompts avant la v1.

#### FR-NEW-008 [EARS-E]: Retéléchargement de la source
> WHEN `GET /api/v1/projects/{project_id}/source` est appelé THE système SHALL renvoyer les
> octets d'origine avec l'en-tête `content-disposition` portant le nom du fichier.

- **Business Rules:** nom non ASCII encodé en RFC 5987 (`filename*=UTF-8''...`) avec un repli
  ASCII dans `filename=`, calculé selon la règle NFKD de FR-NEW-003. Type MIME déduit de
  l'extension, exhaustivement : `text/markdown; charset=utf-8`, `text/plain; charset=utf-8`,
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/pdf`.
  Si le fichier source a disparu du disque, 404 `{"detail": "source absente"}`, jamais 500, et
  le projet reste listé par FR-NEW-031 avec le statut `source_manquante`.
- **Priority:** Must-have

#### FR-NEW-009 [EARS-O]: Une seule source par projet
> IF un projet porte déjà une source THEN THE système SHALL répondre 409 avec
> `{"detail": "le projet a déjà une source"}` à toute tentative de dépôt supplémentaire sur
> `POST /api/v1/projects/{project_id}/source`.

- **Business Rules:** cette exigence est ce qui déclare la route
  `POST /api/v1/projects/{project_id}/source`. Elle n'existe que pour être refusée lorsqu'une
  source est déjà présente ; sur un projet sans source, cas que l'interface ne produit pas
  puisque FR-NEW-001 dépose les deux ensemble, elle se comporte comme FR-NEW-001 à partir de
  l'étape d'écriture et répond 201.
- **Priority:** Must-have

#### FR-NEW-010 [EARS-U]: Disposition d'une version sur disque
> THE système SHALL stocker chaque version dans `projects/<project_id>/v<n>/` contenant
> `state.json`, `prompts/` et, une fois produits, `testplan.xlsx` puis `qc.xlsx`.

- **Exact names:** `prompts/distiller.md`, `prompts/scenario_generator.md`,
  `prompts/coverage.md`, `testplan.xlsx`, `qc.xlsx`.
- **Priority:** Must-have

#### FR-NEW-011 [EARS-E]: Numérotation monotone
> WHEN une version est créée THE système SHALL lui donner le numéro `next_version` lu dans
> `project.json`, puis incrémenter ce compteur.

- **Business Rules:** un numéro n'est **jamais** réutilisé, même après suppression. Si
  `next_version` manque ou est illisible, le système retombe sur `max(versions existantes) + 1`.
  La dixième version s'appelle `v10` et se classe après `v9`, donc le tri est numérique et non
  lexicographique.
- **Priority:** Must-have
- **Rationale:** deux artefacts différents sous un même nom rendraient un audit de recette faux.

#### FR-NEW-012 [EARS-E]: Liste des versions
> WHEN `GET /api/v1/projects/{project_id}/versions` est appelé THE système SHALL renvoyer les
> versions de la plus récente à la plus ancienne, chacune avec son identifiant, son statut, son
> modèle et sa date.

- **Outputs:** `{"versions": [{"id": "v3", "status": "done", "model": str, "created_at": str}, ...]}`
- **Business Rules:** statuts possibles, exhaustivement : `running`, `done`, `failed`,
  `corrompue`.
- **Priority:** Must-have

#### FR-NEW-047 [EARS-E]: Détail d'une version
> WHEN `GET /api/v1/projects/{project_id}/versions/{version}` est appelé THE système SHALL
> renvoyer l'état de cette version avec, sous la clé `prompts`, le **contenu** des prompts lu
> depuis `v<n>/prompts/`, et non les chemins qui y mènent.

- **Outputs:** `{"id": str, "status": str, "model": str, "created_at": str, "error": str|null, "prompts": {"distiller": str, "scenario_generator": str, "coverage": str}}`
- **Business Rules:** c'est la seule différence entre ce que FR-NEW-017 **persiste** et ce que
  cette route **rend**. Sur disque, `state.json` ne porte que les chemins relatifs, pour ne pas
  garder le même texte à deux endroits ; la route les déréférence à la lecture. Un implementeur
  qui renvoie `state.json` tel quel renvoie `"prompts/distiller.md"` et casse E2E-008. 404
  `{"detail": "version inconnue: <version>"}` si elle n'existe pas, 409
  `{"detail": "version corrompue: <version>"}` si son état est illisible.
- **Priority:** Must-have

#### FR-NEW-013 [EARS-E]: Suppression d'une version
> WHEN `DELETE /api/v1/projects/{project_id}/versions/{version}` est appelé sur une version
> terminée THE système SHALL supprimer son dossier et répondre 204 sans corps.

- **Business Rules:** la suppression ne renumérote rien. Elle ne touche ni `source/` ni
  `project.json` autrement que par le compteur, qui n'est pas décrémenté.
- **Priority:** Must-have

#### FR-NEW-014 [EARS-O]: Suppression refusée pendant une exécution
> IF la version visée est en statut `running` THEN THE système SHALL répondre 409 avec
> `{"detail": "version en cours d'exécution"}` et SHALL NOT supprimer quoi que ce soit.

- **Priority:** Must-have

#### FR-NEW-015 [EARS-O]: Version corrompue
> IF le `state.json` d'une version est illisible THEN THE système SHALL la lister avec le statut
> `corrompue`, SHALL répondre 409 `{"detail": "version corrompue: <version>"}` à toute demande
> de classeur, et SHALL NOT empêcher la création d'une nouvelle version.

- **Priority:** Must-have

#### FR-NEW-016 [EARS-E]: Lecture des prompts par défaut
> WHEN `GET /api/v1/projects/{project_id}/prompts` est appelé THE système SHALL renvoyer le
> contenu des prompts livrés avec l'outil, et SHALL NOT renvoyer ceux d'une version antérieure.

- **Outputs:** `{"distiller": str, "scenario_generator": str, "coverage": str}`
- **Business Rules:** lus depuis `src/tgi/prompts/`, résolus par `Path(__file__)` conformément
  à la convention du dépôt.
- **Priority:** Must-have

#### FR-NEW-017 [EARS-E]: Les prompts employés sont écrits dans la version
> WHEN une version est créée THE système SHALL écrire dans `v<n>/prompts/` le contenu exact des
> trois prompts employés, édités ou non.

- **Business Rules:** `state.json` de la version référence les chemins relatifs
  `prompts/<clé>.md`, jamais le contenu en double.
- **Priority:** Must-have

#### FR-NEW-018 [EARS-UB]: Une édition de prompt ne déborde pas de sa version
> THE système SHALL NOT propager une édition de prompt à la version suivante ni aux prompts
> livrés avec l'outil.

- **Priority:** Must-have

#### FR-NEW-019 [EARS-O]: Prompt invalide
> IF une clé de prompt reçue n'est pas l'une de `distiller`, `scenario_generator`, `coverage`,
> ou si sa valeur est vide une fois les blancs retirés, THEN THE système SHALL répondre 422 avec
> respectivement `{"detail": "prompt inconnu: <clé>"}` ou `{"detail": "prompt vide: <clé>"}` et
> SHALL NOT créer de version.

- **Priority:** Must-have

#### FR-NEW-020 [EARS-E]: Lancement d'une génération
> WHEN `POST /api/v1/projects/{project_id}/runs` est appelé THE système SHALL créer la version
> suivante, lancer le pipeline en tâche de fond et répondre 202 avec `{"version": "v<n>"}`.

- **Inputs:** `{"model": str, "prompts": {clé: str}}`, `prompts` facultatif.
- **Priority:** Must-have

#### FR-NEW-021 [EARS-O]: Une seule génération par projet
> IF une version du projet est déjà en statut `running` THEN THE système SHALL répondre 409 avec
> `{"detail": "génération déjà en cours"}` et SHALL NOT créer de seconde version.

- **Business Rules:** le verrou est porté par projet, via `locks.lock_for(f"run:{project_id}")`,
  de sorte que deux projets distincts tournent en parallèle.
- **Priority:** Must-have

#### FR-NEW-022 [EARS-S]: Progression
> WHILE une version est en statut `running` THE système SHALL émettre sur
> `GET /api/v1/projects/{project_id}/versions/{version}/events` un événement `progress` à chaque
> changement d'état d'un scénario et au moins toutes les 2 secondes, puis un événement terminal
> `done` ou `error`.

- **Outputs:** `event: progress`, `data` JSON `{"version": str, "percent": int, "done": int, "total": int, "elapsed_s": int, "remaining_s": int|null}`.
- **Business Rules:** `percent` est monotone croissant, borné à `[0, 100]`, et vaut 100 au
  terme d'une exécution réussie. **Les deux cadences sont cumulatives et non alternatives** :
  une exécution de 60 scénarios émet au moins 60 événements `progress` même si elle dure 3
  secondes, ce que la seule règle des 2 secondes ne garantirait pas, et une exécution lente sur
  un seul scénario en émet quand même un toutes les 2 secondes.
- **Priority:** Must-have

#### FR-NEW-023 [EARS-E]: Téléchargement du classeur
> WHEN `GET /api/v1/projects/{project_id}/versions/{version}/xlsx` est appelé sur une version
> `done` THE système SHALL renvoyer le classeur avec le type
> `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

- **Business Rules:** 409 `{"detail": "génération en cours"}` si `running`, 409
  `{"detail": "version en échec"}` si `failed`.
- **Priority:** Must-have

#### FR-NEW-024 [EARS-O]: Échecs d'exécution nommés
> IF le pipeline échoue THEN THE système SHALL passer la version en `failed` et écrire dans son
> `state.json` un champ `error` valant exactement l'un de : `"endpoint injoignable: <base_url>"`,
> `"authentification refusée (401)"`, `"réponse du modèle illisible"`,
> `"disque plein, classeur non écrit"`.

- **Business Rules:** une réponse illisible donne lieu à **3 tentatives au total** pour un
  scénario donné, première tentative comprise, donc 2 reprises et jamais davantage. Le compte se
  lit sur le nombre d'appels au modèle, qui est exactement 3.
- **Priority:** Must-have

#### FR-NEW-025 [EARS-UB]: Le travail déjà écrit n'est pas défait
> THE système SHALL NOT effacer les scénarios déjà terminés d'une version lorsque celle-ci
> passe en `failed`.

- **Priority:** Must-have
- **Rationale:** une coupure d'authentification au bout de 40 minutes ne doit pas rendre
  l'exécution entière inutile.

#### FR-NEW-026 [EARS-U]: Fichier de configuration des modèles
> THE système SHALL lire et écrire la liste des modèles dans `<config_dir>/models.json`, où
> `config_dir` vaut `TGI_CONFIG_DIR` ou, à défaut, `$HOME/.config/tgi`.

- **Exact names:** fichier `models.json` ; forme
  `{"models": [{"name": str, "base_url": str, "api_key": str, "model": str}]}` ; clé de
  configuration `TGI_CONFIG_DIR`.
- **Business Rules:** créé par l'outil s'il est absent, dossiers parents compris, avec le mode
  `0o600`.
- **Priority:** Must-have

#### FR-NEW-027 [EARS-E]: Gestion de la table de modèles
> WHEN les routes `GET /api/v1/models`, `POST /api/v1/models`,
> `DELETE /api/v1/models/{name}` sont appelées THE système SHALL respectivement lister, ajouter
> et retirer une entrée, et persister immédiatement le fichier.

- **Outputs:** 200 pour la liste, 201 pour l'ajout, 204 pour le retrait.
- **Business Rules:** 409 `{"detail": "modèle déjà défini: <name>"}` sur doublon de `name` ;
  404 `{"detail": "modèle inconnu: <name>"}` au retrait d'une entrée absente ; `name` limité à
  120 caractères, au-delà 422 `{"detail": "nom de modèle trop long (max 120)"}`.
  **Les deux cas fautifs de `base_url` sont distincts et ne rendent pas le même corps.**
  Champ **absent** : c'est la validation de schéma du cadriciel qui répond, donc 422 avec le
  corps `{"detail": [{"loc": ["body", "base_url"], ...}]}` que FastAPI produit, `detail` étant
  une liste. Champ **présent mais de schéma autre que `http` ou `https`** : c'est notre
  validation, donc 422 avec `{"detail": "base_url invalide: <valeur>"}`, `detail` étant une
  chaîne. Un implementeur qui unifie les deux casse E2E-067 ou E2E-068.
  L'ajout préserve l'ordre et ajoute en queue.
  Les écritures sont sérialisées par `locks.lock_for("models")` pour qu'aucun ajout concurrent
  ne soit perdu.
- **Priority:** Must-have

#### FR-NEW-028 [EARS-UB]: La clé d'API ne sort jamais en clair
> THE système SHALL NOT inclure la valeur d'une `api_key` dans une réponse HTTP, dans une page
> rendue, dans un flux SSE ni dans une trace OpenTelemetry.

- **Business Rules:** toute restitution est masquée sous la forme `sk-***<4 derniers caractères>`.
- **Priority:** Must-have

#### FR-NEW-029 [EARS-O]: Refus de générer sans modèle
> IF aucun modèle n'est configuré THEN THE système SHALL répondre 409 avec
> `{"detail": "aucun modèle configuré"}` à toute demande de génération, et SHALL servir
> néanmoins l'interface et les routes de gestion des modèles.

- **Business Rules:** « aucun modèle configuré » signifie fichier absent, illisible, ou liste
  vide. Un fichier illisible fait en plus répondre `GET /api/v1/models` avec
  `{"models": [], "warning": "fichier de modèles illisible"}`. Le mécanisme de détection
  existant, `Settings.configuration_problems()` (`src/tgi/config.py:158-172`), est consultatif
  et n'empêche rien ; cette exigence le remplace par un refus effectif et déplace le critère de
  la variable d'environnement vers `models.json`.
- **Priority:** Must-have

#### FR-NEW-030 [EARS-E]: Client LLM construit par exécution
> WHEN une génération démarre THE système SHALL construire un client LLM à partir de la
> `base_url` et de l'`api_key` de l'entrée de modèle choisie.

- **Exact names:** fonction `build_llm_client(entry: ModelEntry) -> LLMClient` dans
  `src/tgi/services/llm.py`.
- **Priority:** Must-have

#### FR-NEW-031 [EARS-E]: Liste des projets
> WHEN `GET /api/v1/projects` est appelé THE système SHALL balayer le répertoire des projets et
> renvoyer les projets de la création la plus récente à la plus ancienne.

- **Outputs:** `{"projects": [{"id": str, "name": str, "source_filename": str, "version_count": int, "status": str}]}`
- **Business Rules:** un dossier n'est un projet que s'il porte un `project.json`. Un dossier
  copié pendant que l'application tourne apparaît au rafraîchissement suivant, sans redémarrage.
  Statuts de projet possibles, exhaustivement : `ok`, `corrompu` quand `project.json` est
  illisible (FR-NEW-033), `source_manquante` quand le fichier source a disparu (FR-NEW-008).
- **Priority:** Must-have

#### FR-NEW-032 [EARS-UB]: Ni intrus ni lien sortant dans la liste
> THE système SHALL NOT lister une entrée du répertoire des projets qui est un lien symbolique,
> ni un dossier dépourvu de `project.json`.

- **Priority:** Must-have

#### FR-NEW-033 [EARS-O]: Projet corrompu
> IF le `project.json` d'un dossier est illisible THEN THE système SHALL lister ce projet avec
> exactement les trois clés `id`, `name` et `status`, `status` valant `corrompu` et `id` comme
> `name` valant le nom du dossier, et SHALL NOT échouer la requête.

- **Business Rules:** c'est la seule entrée de la liste qui déroge à la forme à cinq clés de
  FR-NEW-031, et la dérogation est normative plutôt que tolérée : `source_filename` et
  `version_count` se lisent dans `project.json`, qui est précisément ce qui est illisible. Les
  émettre à `null` serait un troisième contrat à définir pour rien ; l'entrée dégradée porte
  trois clés, ni plus ni moins, ce qu'E2E-060 vérifie par égalité et non par inclusion.
- **Priority:** Must-have

#### FR-NEW-034 [EARS-E]: Production de l'export QC
> WHEN `POST /api/v1/projects/{project_id}/versions/{version}/qc` est appelé sur une version
> `done` portant au moins un test THE système SHALL écrire `v<n>/qc.xlsx` et répondre 201.

- **Outputs:** `{"path": "v<n>/qc.xlsx", "warnings": [str]}`
- **Business Rules:** une seule feuille, nommée `QC`, dont la ligne 1 est exactement
  `["Subject", "Test Name", "Description", "Step Name", "Step Description", "Expected Results"]`.
  Téléchargement par `GET /api/v1/projects/{project_id}/versions/{version}/qc.xlsx`.
- **Priority:** Must-have

#### FR-NEW-035 [EARS-U]: Composition des colonnes QC
> THE système SHALL composer chaque ligne de la feuille `QC` ainsi : `Subject` vaut
> `<conteneur>-<TYPE>_<titre du cas d'utilisation>_<identifiant du scénario>` ; `Test Name` vaut
> `TRA_<identifiant du test>_<nom du test>__<références jointes par une virgule>` ;
> `Description` vaut la description du test, un saut de ligne, puis
> `Exigences validées : <références jointes par virgule et espace>` ; `Step Name` vaut
> `Étape <rang>` ; `Step Description` et `Expected Results` valent les champs de l'étape.

- **Business Rules:** une ligne par étape, `Subject` et `Test Name` répétés sur chaque ligne du
  même test, ce qui est la règle de rattachement de l'import ALM. Le titre du cas d'utilisation
  vient de `Group.title` (`src/tgi/deliverable.py:194`).
  **Les champs sources sont nommés exactement**, d'après `src/tgi/schemas/test_schema.json` :
  `<identifiant du test>` = `test["id"]`, `<nom du test>` = `test["name"]`, la description =
  `test["description"]`, les références = `test["requirement_refs"]`, `<rang>` =
  `step["order"]`, `Step Description` = `step["description"]`, `Expected Results` =
  `step["expected_result"]`, `<conteneur>` = `scenario["container"]`,
  `<identifiant du scénario>` = `scenario["id"]`.
- **Priority:** Must-have

#### FR-NEW-036 [EARS-U]: Type d'exigence
> THE système SHALL déduire `TYPE` du préfixe du dernier segment de la **première** référence du
> test, selon la table : `RM` donne `RM`, `EM` donne `EMOE`, `M`, `N` et `T` donnent `IHM`.

- **Business Rules:** les trois valeurs recouvrent les deux **axes** que la SFD de référence se
  donne : l'axe `F`, dont les feuilles sont `RM` et `EM`, et l'axe `E`, dont les feuilles sont
  `M`, `N` et `T` et qui décrit les écrans. C'est l'axe qui porte le sens métier, et le préfixe
  de feuille suffit à le retrouver, ce qui évite d'avoir à lire `Requirement.axis`.
  Le préfixe est déjà calculé par `Grammar.kind_of`
  (`src/tgi/grammar.py:136`), la comparaison est insensible à la casse. Table vérifiée sur la
  SFD de référence : 272 occurrences `RM`, 273 `EM`, 159 `M`, 88 `N`, 10 `T`. Ce comptage porte
  sur le document d'Euro-Information placé sous `examples/`, qui est dans `.gitignore` : il
  n'est pas rejouable depuis le dépôt seul, et le seul échantillon versionné,
  `src/tgi/samples/sample_spec.md`, ne porte pas ces préfixes.
- **Priority:** Must-have

#### FR-NEW-037 [EARS-O]: Préfixe inconnu
> IF le préfixe d'une référence n'est pas dans la table THEN THE système SHALL employer
> `TYPE = INCONNU`, SHALL produire quand même l'export, et SHALL inclure dans `warnings` la
> chaîne `"préfixe d'exigence inconnu: <préfixe> (<référence>)"`.

- **Priority:** Must-have
- **Rationale:** échouer l'export entier sur un préfixe inattendu bloquerait une qualification
  en cours ; l'avertissement rend le cas visible sans retirer le livrable.

#### FR-NEW-038 [EARS-O]: Limite de cellule Excel
> IF une valeur de cellule dépasse 32 767 caractères THEN THE système SHALL la tronquer à
> 32 767 caractères, dernier caractère compris valant `…`.

- **Business Rules:** une cellule plus longue rend le fichier inouvrable par Excel.
- **Priority:** Should-have

#### FR-NEW-039 [EARS-O]: Export QC impossible
> IF la version visée est `running` THEN THE système SHALL répondre 409
> `{"detail": "génération en cours"}` ; IF elle ne porte aucun test THEN THE système SHALL
> répondre 409 `{"detail": "aucun test à exporter"}`.

- **Priority:** Must-have

#### FR-NEW-040 [EARS-UB]: Les identifiants d'URL ne construisent pas de chemin libre
> THE système SHALL NOT employer un `project_id` ou un `version` reçu dans un chemin d'URL ou
> dans un paramètre de requête pour composer un chemin disque sans l'avoir fait passer par
> `validated_project_id()` ou `validated_version()` de `src/tgi/services/paths.py`, livrées par
> SPEC-0001a.

- **Business Rules:** cette exigence n'invente aucun contrôle : elle **applique** celui de
  SPEC-0001a FR-NEW-002 aux 9 routes et aux 2 paramètres de requête que le présent document
  crée, énumérés dans la table des sources ajoutées en 2.4. La validation a lieu à la frontière
  HTTP, avant tout appel au gestionnaire d'état.
  La route la plus dangereuse est `DELETE .../versions/{version}`, dont le puits est un
  `rmtree` : un `version` valant `..` y désigne le répertoire des projets entier.
  Les corps restent ceux de SPEC-0001a, `{"detail": "projet inconnu: <project_id>"}` et
  `{"detail": "version inconnue: <version>"}`, identiques que l'identifiant soit mal formé ou
  bien formé mais absent.

#### FR-NEW-040-bis [EARS-UB]: Énoncé d'origine, conservé pour mémoire
> THE système SHALL NOT employer un `project_id`, un `version` ou un `test_id` reçu dans un
> chemin d'URL **ou dans un paramètre de requête** pour composer un chemin disque sans avoir
> d'abord vérifié qu'il correspond respectivement à `^[0-9a-f]{12}$`, `^v[1-9][0-9]*$` et
> `^[A-Za-z0-9._-]{1,64}$`.

- **Business Rules:** un identifiant non conforme donne 404, jamais 500, et n'atteint aucune
  opération de système de fichiers. Les corps sont nommés :
  `{"detail": "projet inconnu: <project_id>"}` pour un projet, et
  `{"detail": "version inconnue: <version>"}` pour une version, aussi bien quand l'identifiant
  est mal formé que quand il est bien formé mais absent, de sorte qu'une sonde ne puisse pas
  distinguer les deux.
  **Le paramètre de requête compte comme source au même titre que le chemin**, puisque
  FR-NEW-042 en introduit deux qui atteignent le disque. Et la charge qui atteint réellement le
  puits est `%2E%2E`, qui se décode en `..` : `%2F` est décodé par Starlette **avant** le
  routage, donc un `..%2F..%2Fetc` n'atteint aucun gestionnaire et reçoit le 404 du routeur,
  même sans aucune validation. C'est pourquoi E2E-094 à E2E-096 emploient `%2E%2E`.
  Couvre les occurrences relevées en 2.4 à
  `src/tgi/services/state_manager.py:66`, `:94`, `:186`, `:188` et `:207`.
- **Priority:** Must-have

#### FR-NEW-041 [EARS-O]: Disque plein
> IF une écriture échoue avec `ENOSPC` THEN THE système SHALL répondre 507 au dépôt avec
> `{"detail": "disque plein, projet non créé"}`, SHALL passer la version en `failed` lors d'une
> génération, et SHALL NOT laisser de dossier partiel ni de fichier `.tmp`.

- **Priority:** Should-have

#### FR-NEW-042 [EARS-E]: Interface en deux gestes
> WHEN l'utilisatrice ouvre `GET /` THE système SHALL présenter la liste des projets, une zone
> de dépôt, et pour un projet ouvert : les trois prompts éditables, le choix du modèle, un
> bouton Lancer, la barre de progression, la liste des versions et leurs téléchargements.

- **Inputs:** deux paramètres de requête facultatifs, `project` et `version`, qui ouvrent
  directement un projet et une version. Ils existent pour que l'onglet du navigateur soit
  partageable et re-chargeable, ce qui est le seul état de navigation que l'interface conserve.
- **Business Rules:** aucun écran intermédiaire entre le dépôt et le lancement. Aucun onglet.
  Appelée sans paramètre, la page ouvre la liste. Avec `project` seul, elle ouvre ce projet ;
  avec `project` et `version`, cette version. Un `project` ou un `version` inconnu donne 404,
  traité par FR-NEW-044. Un `version` fourni **sans** `project` donne 404 avec le corps HTML
  `projet inconnu: `, la chaîne vide étant le nom de projet manquant. Les deux paramètres sont
  des identifiants au sens de FR-NEW-040 et sont validés par ses trois expressions.
  **Trois libellés sont normatifs**, parce que des tests les vérifient : la liste vide affiche
  `Aucun projet` ; l'absence de modèle configuré affiche `aucun modèle configuré` dans le corps
  de la page ; un lien profond vers une version absente affiche `version inconnue: <version>`
  dans le corps HTML, et non dans un `detail` JSON, `GET /` rendant du HTML.
- **Priority:** Must-have

#### FR-NEW-043 [EARS-E]: Page de paramètres
> WHEN l'utilisatrice ouvre `GET /parametres` THE système SHALL présenter la table des modèles
> avec l'ajout et le retrait.

- **Priority:** Must-have

#### FR-NEW-044 [EARS-O]: Lien profond périmé
> IF `GET /` est appelée avec un paramètre `project` ou `version` qui ne désigne rien THEN THE
> système SHALL répondre 404 avec un corps HTML portant `projet inconnu: <project>` ou
> `version inconnue: <version>`, et SHALL laisser `GET /` sans paramètre répondre 200.

- **Business Rules:** c'est la contrepartie HTML de FR-NEW-040, qui ne régit que les corps JSON
  des routes `/api/v1/`. Les deux chaînes sont les mêmes, le conteneur diffère. Un marque-page
  sur une version supprimée ne doit pas rendre l'application inatteignable, seulement cette URL.
- **Priority:** Should-have

#### FR-NEW-045 [EARS-U]: Rien d'autre que du JSON, du Markdown et du XLSX
> THE système SHALL n'écrire sous le répertoire des projets que des fichiers d'extension
> `.json`, `.md`, `.xlsx`, plus le document source dans `source/`, et SHALL NOT y créer de base
> de données ni de dépôt git.

- **Priority:** Must-have

#### FR-NEW-046 [EARS-UB]: Les projets au format antérieur sont ignorés
> THE système SHALL NOT lister, ouvrir ni convertir un dossier portant un `state.json` à sa
> racine et aucun `project.json`.

- **Business Rules:** c'est le comportement que FR-NEW-031 produit déjà, un dossier n'étant un
  projet que s'il porte un `project.json` ; cette exigence le rend explicite pour le cas
  particulier des projets créés par le build antérieur, plutôt que d'introduire un statut
  `ancien_format` qui la contredirait. Le parc concerné est de 1 projet sur le poste de
  développement ; aucune donnée de production n'est en jeu, et la conversion ne vaut pas son
  risque. L'utilisatrice redépose la SFD, ce qui coûte un geste.
- **Priority:** Must-have

#### FR-NEW-048 [EARS-E]: Les prompts de la version pilotent réellement le pipeline
> WHEN une version s'exécute THE système SHALL employer comme message système de chaque appel
> `distiller`, `scenario_generator` et `coverage` le contenu de `v<n>/prompts/<clé>.md`, et
> SHALL NOT lire `src/tgi/prompts/` pendant l'exécution.

- **Exact names:** `DistillerAgent(llm, system_prompt: str)`,
  `ScenarioGeneratorAgent(llm, system_prompt: str)`, `CoverageAgent(llm, system_prompt: str)`.
- **Business Rules:** aujourd'hui chaque agent lit sa constante de module une fois, à la
  construction (`src/tgi/agents/distiller.py:134`, `scenario_generator.py:87`,
  `coverage.py:64`). Sans cette exigence, une implémentation qui écrit bien les fichiers de
  prompts mais continue d'exécuter les prompts livrés **passe les 91 tests** tout en rendant
  SC-001 inopérant. C'est la raison d'être de E2E-092, qui lit le message système réellement
  envoyé et non le fichier sur disque.
- **Priority:** Must-have

#### FR-NEW-049 [EARS-E]: Une exécution enchaîne lecture, génération et couverture
> WHEN `POST /api/v1/projects/{project_id}/runs` est accepté THE système SHALL, en tâche de
> fond et dans cet ordre, analyser `source/<source_filename>`, exécuter la distillation, puis la
> génération par scénario, puis la couverture, puis écrire `testplan.xlsx` et passer `status` à
> `done`.

- **Business Rules:** c'est le déplacement que FR-NEW-007 rend nécessaire : la lecture du
  document est aujourd'hui déclenchée par le dépôt (`src/tgi/tgi.py:306-308`), et FR-NEW-007
  l'interdit. Sans cette exigence le pipeline ne s'exécute jamais.
  Pendant la distillation, les événements `progress` portent `total = 0`, `done = 0`,
  `percent = 0` et `remaining_s = null`. Ensuite `total` vaut le nombre de scénarios distillés,
  `done` le nombre de scénarios dans un état final (`done`, `needs_human`, `error`), et
  `percent = floor(100 * done / total)`, porté à 100 à l'écriture du classeur.
- **Priority:** Must-have

#### FR-NEW-050 [EARS-O]: Ce qui fait échouer une version, et ce qui ne la fait pas échouer
> IF la distillation lève une erreur, OR un appel modèle quelconque lève une erreur de connexion
> ou un statut 401, THEN THE système SHALL annuler les scénarios non commencés et passer la
> version en `failed` avec le message de FR-NEW-024.

- **Business Rules:** un scénario isolé qui épuise ses 3 tentatives sur une réponse illisible
  est marqué `needs_human` et **l'exécution continue**. La version ne passe `failed` avec
  `"réponse du modèle illisible"` que si la distillation elle-même est illisible, ou si tous les
  scénarios finissent `needs_human` ou `error`.
- **Priority:** Must-have
- **Rationale:** DEC-012. Perdre 40 minutes de travail et 83 appels pour une réponse mal formée
  est exactement ce que FR-NEW-025 existe pour empêcher ; une coupure réseau ou
  d'authentification, elle, ne se répare pas en continuant.

#### FR-NEW-051 [EARS-O]: Classification des erreurs modèle
> IF un appel lève `openai.APIConnectionError` ou `httpx.ConnectError` THEN THE système SHALL
> cesser de réessayer et écrire `error` égal à `"endpoint injoignable: <base_url>"` ; IF il lève
> `openai.AuthenticationError` ou une `httpx.HTTPStatusError` de statut 401 THEN THE système
> SHALL écrire `error` égal à `"authentification refusée (401)"`, sans nouvelle tentative.

- **Business Rules:** aujourd'hui `chat_json` attrape **toute** exception et réessaie, puis lève
  `LLMJSONError` (`src/tgi/services/llm.py:416-430`) : une coupure réseau, un 401 et un JSON
  invalide arrivent indistinctement à l'orchestrateur. Les trois doivent être séparés à la
  source. Les appels passent par `AsyncOpenAI` (`src/tgi/services/llm.py:243`), qui lève les
  exceptions `openai.*` ; les formes `httpx.*` sont listées parce qu'un transport simulé les
  produit. Seules les réponses illisibles sont réessayées, avec `max_attempts = 3` : la valeur
  par défaut de `TGI_LLM_JSON_RETRIES` passe de 5 (`src/tgi/config.py:133`) à 3, et le client
  est construit avec `AsyncOpenAI(max_retries=0)` pour que le compte d'appels soit lisible.
- **Priority:** Must-have

#### FR-NEW-052 [EARS-E]: Format et rejeu du flux d'événements
> WHEN un client s'abonne à `GET /api/v1/projects/{project_id}/versions/{version}/events` THE
> système SHALL émettre d'abord un événement `progress` reflétant l'état persisté, puis, si la
> version est déjà `done`, `failed` ou `corrompue`, l'événement terminal correspondant, et
> fermer le flux.

- **Exact names:** trame `event: progress|done|error\ndata: <json>\n\n` ; entretien de connexion
  `: ping\n\n`. Charge `done` : `{"version": str, "tests": int}`. Charge `error` :
  `{"version": str, "error": str}`, `error` étant la chaîne exacte de FR-NEW-024.
- **Business Rules:** le flux actuel n'émet qu'une ligne `data:` sans ligne `event:`
  (`src/tgi/tgi.py:333-338`). Le rejeu de l'état persisté à l'abonnement est ce qui empêche un
  client, ou un test, de rester suspendu lorsqu'il s'abonne après la fin de l'exécution.
- **Priority:** Must-have

#### FR-NEW-053 [EARS-E]: Exécution orpheline après redémarrage
> WHEN l'application démarre THE système SHALL passer en `failed`, avec `error` égal à
> `"exécution interrompue par un redémarrage"`, toute version dont `state.json` porte
> `status` égal à `running`.

- **Business Rules:** les tâches ne vivent qu'en mémoire (`src/tgi/tgi.py:377-379`). Sans cette
  exigence, un arrêt brutal laisse une version `running` que FR-NEW-014 empêche de supprimer et
  FR-NEW-021 empêche de relancer : le projet est bloqué définitivement, sans aucun moyen de le
  débloquer depuis l'interface.
- **Priority:** Must-have

#### FR-NEW-054 [EARS-E]: Schéma de la table de modèles
> WHEN `POST /api/v1/models` reçoit un corps THE système SHALL exiger les quatre champs `name`,
> `base_url`, `api_key` et `model`, tous de type `str`.

- **Business Rules:** un champ absent donne la 422 du cadriciel, `detail` étant une liste.
  `name` ou `model` vide après `strip()` donne 422 `{"detail": "champ vide: <champ>"}`.
  Le corps de la 201 et chaque entrée de `GET /api/v1/models` valent
  `{"name": str, "base_url": str, "api_key": str, "model": str}`. Le masque de FR-NEW-028 se
  calcule `"sk-***" + key[-4:]` si `len(key) >= 8`, et vaut `"sk-***"` sinon, **quel que soit le
  préfixe réel de la clé** : le littéral `sk-` du masque ne décrit pas la clé, il marque qu'elle
  est masquée.
- **Priority:** Must-have

#### FR-NEW-055 [EARS-O]: Demande d'exécution invalide
> IF `model` est absent du corps de `POST .../runs` THEN THE système SHALL répondre 422 du
> cadriciel ; IF `model` ne désigne aucune entrée de `models.json` alors que la table n'est pas
> vide THEN THE système SHALL répondre 422 `{"detail": "modèle inconnu: <model>"}` et SHALL NOT
> créer de version.

- **Business Rules:** l'ordre des contrôles est normatif, parce que deux ordres donnent deux
  codes observables sur la même requête : projet inconnu (404), table vide (409), modèle inconnu
  (422), prompts invalides (422), exécution déjà en cours (409). Une valeur de `prompts` qui
  n'est pas une chaîne donne la 422 du cadriciel.
- **Priority:** Must-have

#### FR-NEW-056 [EARS-UB]: Aucun fichier par test
> THE système SHALL NOT écrire de fichier `tests/<id>.json` ; les tests ne vivent que dans
> `v<n>/state.json`.

- **Note de scission:** la suppression du puits lui-même, `add_or_update_tests` et `tests_dir`,
  appartient à SPEC-0001a FR-NEW-003, qui la ferme sur le code existant. Ce qui reste ici est
  la conséquence sur la disposition disque : la nouvelle persistance par version n'en recrée
  aucun.

- **Business Rules:** supprime le puits `src/tgi/services/state_manager.py:188`, qui construit
  un chemin à partir d'un identifiant **venu du modèle** et que FR-NEW-040 ne couvre pas,
  celui-ci ne régissant que les identifiants d'URL. La fonction `add_or_update_tests` disparaît
  avec lui.
- **Priority:** Must-have

#### FR-NEW-057 [EARS-E]: Les statistiques lisent le nouveau format
> WHEN `tgi-stats` lit le répertoire des projets THE système SHALL énumérer `*/v*/state.json` et
> rattacher chaque version à son projet par le nom du dossier parent.

- **Business Rules:** `src/tgi/stats.py:152` balaye aujourd'hui `*/state.json`, qui n'existe
  plus à la racine d'un projet. Les 26 tests de `tests/test_stats.py` construisent leurs propres
  fixtures à l'ancien format et resteraient verts : **rien ne détecterait la panne**, ce qui est
  la raison pour laquelle cette exigence existe plutôt qu'une entrée de dérive.
- **Priority:** Must-have

#### FR-NEW-058 [EARS-E]: Spans des opérations
> WHEN un projet est créé, une version lancée ou supprimée, un export QC produit, ou
> `models.json` écrit THE système SHALL ouvrir respectivement
> `trace_span("project.create")`, `trace_span("version.run")`, `trace_span("version.delete")`,
> `trace_span("qc.export")` et `trace_span("models.write")`.

- **Business Rules:** attributs `project_id` et `version` quand ils s'appliquent. Jamais
  d'`api_key`, jamais de contenu de prompt ni de réponse. Ces noms n'apparaissaient qu'en 7.5,
  sans exigence ni test, alors que `tgi-stats` les consomme.
- **Priority:** Should-have

#### FR-NEW-059 [EARS-O]: Ordre des refus au dépôt
> IF plusieurs motifs de refus s'appliquent à un dépôt THEN THE système SHALL appliquer cet
> ordre : partie `file` absente (422), extension non supportée (415), taille (413), zéro octet
> (400 `document vide`), analyse impossible (400 `document illisible`), écriture (507).

- **Business Rules:** sans cet ordre, un `.png` vide rend 400 pour un implementeur et 415 pour
  un autre.
- **Priority:** Must-have

#### FR-NEW-060 [EARS-O]: Statuts supprimables et exportables
> IF une version est en statut `done`, `failed` ou `corrompue` THEN THE système SHALL en
> autoriser la suppression ; IF un export QC vise une version `failed` THEN THE système SHALL
> répondre 409 `{"detail": "version en échec"}` ; IF il vise une version `corrompue` THEN THE
> système SHALL répondre 409 `{"detail": "version corrompue: <version>"}`.

- **Business Rules:** seul `running` empêche la suppression, par FR-NEW-014. « Version terminée »
  en FR-NEW-013 se lit donc « toute version qui n'est pas `running` ».
- **Priority:** Must-have

#### FR-NEW-061 [EARS-O]: Forme dégradée et tri des entrées sans métadonnées
> IF une version est `corrompue` THEN son entrée de liste SHALL valoir exactement
> `{"id": "v<n>", "status": "corrompue"}` ; IF un projet est `corrompu` THEN THE système SHALL
> le classer après tous les autres, par nom de dossier croissant.

- **Business Rules:** une version corrompue n'a ni `model` ni `created_at` lisibles, un projet
  corrompu n'a pas de `created_at` sur lequel trier. À `created_at` égal, les projets se
  départagent par `id` croissant, pour que l'ordre soit total et donc testable.
- **Priority:** Must-have

#### FR-NEW-062 [EARS-E]: Volume de tests par scénario
> WHEN une exécution démarre THE système SHALL employer `settings.tests_per_scenario` comme
> cible de volume, et `POST .../runs` SHALL NOT accepter de champ `tests_per_scenario`.

- **Business Rules:** c'est aujourd'hui un champ du formulaire de dépôt (`src/tgi/tgi.py:271`),
  conservé dans l'état (`src/tgi/services/state_manager.py:113`) et consommé par la génération
  (`src/tgi/agents/orchestrator.py:223`). Le nouveau contrat le retire de la surface HTTP sans
  le supprimer du produit : la cible reste réglable par configuration, pas par requête.
- **Priority:** Must-have

### Modified Requirements

#### FR-MOD-001 [EARS-UB]: Les résultats ne sont plus fusionnés en place
> THE système SHALL NOT fusionner les résultats d'une exécution avec ceux d'une exécution
> antérieure.

- **Original behavior:** `add_or_update_tests()` écrase par identifiant,
  `src/tgi/services/state_manager.py:170-182`, et `update_scenario()` fusionne,
  `src/tgi/services/state_manager.py:134-139`.
- **New behavior:** chaque exécution écrit dans son propre dossier de version, donc aucune
  collision d'identifiant entre versions.
- **Reason for change:** sans cela SC-005 est impossible, la v2 détruisant la v1.

#### FR-MOD-002 [EARS-U]: Le client LLM cesse d'être un singleton figé
> THE système SHALL exposer `build_llm_client(entry)` et SHALL NOT dépendre d'un client de
> module dont `base_url` et `api_key` sont figés à l'import.

- **Original behavior:** `llm_client = LLMClient()` au niveau module,
  `src/tgi/services/llm.py:475`, construit avec `settings.llm_api_key` et
  `settings.llm_base_url`, `src/tgi/services/llm.py:243`.
- **New behavior:** construction par exécution à partir de l'entrée choisie.
- **Reason for change:** la table de modèles porte plusieurs points d'accès, pas un seul.

#### FR-MOD-003 [EARS-U]: Le fichier source quitte le dossier partagé
> THE système SHALL écrire le document déposé dans `projects/<project_id>/source/` et SHALL NOT
> écrire dans `projects/_uploads/`.

- **Original behavior:** `projects/_uploads/<filename>`, `src/tgi/tgi.py:276-282`, partagé et
  indexé par nom de fichier, lu ensuite par `src/tgi/services/doc_parser.py:120`.
- **New behavior:** un fichier par projet, dans le projet.
- **Reason for change:** NFR2, et la collision de noms de fichiers entre deux projets.

### Removed Requirements

#### FR-DEL-001: Dossier d'upload partagé
- **Description:** suppression de `projects/_uploads/`.
- **Reason:** remplacé par FR-MOD-003.
- **Cleanup:** le code d'écriture `src/tgi/tgi.py:276-282` ; le champ `doc_path` de l'état
  (`src/tgi/services/state_manager.py:110`). Le champ voisin `doc_text`
  (`src/tgi/services/state_manager.py:111`) survit, porté désormais par l'état de version.

#### FR-DEL-002: Versionnement git des projets
- **Description:** suppression de `src/tgi/services/git_service.py` en entier, des appels
  `src/tgi/tgi.py:302`, `:403`, `:414`, `:430`, `:448`, `:459`, des routes
  `GET /projects/{id}/history`, `POST /projects/{id}/rollback`,
  `GET /projects/{id}/partials/history`, et du gabarit `templates/partials/history.html`.
- **Reason:** remplacé par les versions numérotées, qui sont nommables, supprimables une à une
  et compatibles avec le zip. Deux mécanismes d'historique pour un seul besoin divergent.
- **Cleanup:** les `.git/` et `.gitignore` déjà créés dans les dossiers de projets existants
  restent en place sur le disque et ne sont jamais lus, puisque FR-NEW-046 ignore entièrement
  les dossiers dépourvus de `project.json`.

#### FR-DEL-003: Validation humaine de la carte
- **Description:** suppression de `POST /projects/{id}/validate-map`
  (`src/tgi/tgi.py:353`), du garde 409 (`src/tgi/tgi.py:375`), du champ d'état
  correspondant et du gabarit `templates/partials/map.html`.
- **Reason:** décision utilisatrice, DEC-002.
- **Cleanup:** l'événement SSE `map_validated`.

#### FR-DEL-004: Les sept onglets
- **Description:** suppression des sept onglets déclarés en
  `src/tgi/templates/project.html:356-364`, soit DOC, CARTE, EXIGENCES, SCÉNARIOS & TESTS,
  RECHERCHE, CHAT, HISTORIQUE, de leur barre d'onglets, du volet `x-show="activeTab === 'doc'"`
  qui rend le document distillé, et des routes et gabarits qui les servent :
  `GET /projects/{id}/partials/{map,scenarios,requirements,tests,history}`,
  `GET /projects/{id}/scenarios/{sid}/tests`, `POST /projects/{id}/chat`,
  `PUT /projects/{id}/tests/{tid}`, `PUT /projects/{id}/requirements/{ref}`,
  `POST /projects/{id}/discards/{index}`, `POST /projects/{id}/scenarios/{sid}/rerun`,
  `POST /projects/{id}/redistil`, `GET /projects/{id}/tests`,
  `GET /projects/{id}/requirements`.
- **Reason:** décision utilisatrice, DEC-003. L'édition unitaire d'un test dans l'interface est
  remplacée par l'édition du classeur Excel, que l'utilisatrice fait déjà.
- **Cleanup:** `templates/partials/{map,scenarios,scenario_tests,requirements,tests,history}.html`,
  et le volet DOC, qui est rendu en ligne dans `project.html` et n'a pas de gabarit partiel
  propre, ce qui est précisément pourquoi il était facile à oublier dans un décompte.

#### FR-DEL-005: Export zip de sept fichiers
- **Description:** suppression de `GET /projects/{id}/export` (`src/tgi/tgi.py:467-509`).
- **Reason:** remplacé par le téléchargement direct du xlsx d'une version, FR-NEW-023, et par
  l'export QC, FR-NEW-034. Le zip du dossier de projet reste faisable par l'utilisatrice
  elle-même, ce que NFR2 garantit.
- **Cleanup:** la fonction `export_project` et la construction du zip
  (`src/tgi/tgi.py:467-509`), ainsi que le lien « ⬇ Export ZIP » de l'en-tête de
  `templates/project.html`.

## 7. Non-Functional Requirements

### 7.1 Performance

La liste de 500 projets répond en moins d'une seconde. Un événement de progression au moins
toutes les 2 secondes pendant une exécution. L'exécution complète reste de l'ordre de 3 à 4
minutes sur la SFD de référence, inchangée : cet incrément ne touche pas le pipeline.

### 7.2 Security

Pas d'authentification utilisateur : l'outil tourne sur le poste ou le réseau interne, et
l'ajout d'un compte n'est pas demandé. La seule donnée sensible est la clé d'API des modèles,
couverte par FR-NEW-028 et stockée en `0o600` par FR-NEW-026. La classe de traversée de chemin
relevée en 2.4 est fermée par FR-NEW-003 et FR-NEW-040.

### 7.3 Usability

Interface en français. Deux pages seulement : le travail et les paramètres. Aucun écran
intermédiaire entre le dépôt et le lancement.

### 7.4 Reliability

Un échec de modèle ne détruit pas le travail déjà écrit (FR-NEW-025). Un `state.json` corrompu
dégrade une version, jamais l'application (FR-NEW-015, FR-NEW-033). Une version supprimée à la
main depuis l'explorateur de fichiers est un cas normal, pas une panne (EXC-005a).

### 7.5 Observability

OpenTelemetry, déjà en place (`src/tgi/tracing.py`). Spans conservés : `llm.chat`,
`api.list_models`. Spans ajoutés : `project.create`, `version.run`, `version.delete`,
`qc.export`, `models.write`. Collecteur : fichier JSONL sous `TGI_LOGS`, par défaut
`$HOME/.cache/tgi/logs`. Jamais tracés : clés d'API, prompts, réponses de modèle. Le nom du
fichier source est tracé, son contenu ne l'est pas.

### 7.6 Deployment

Contexte client, Euro-Information. Exécution sur poste Windows de l'utilisatrice, décrite dans
`WINDOWS.md`, sans accès PyPI, d'où le dossier `vendor/`. Aucun service infonuagique, aucune
base de données, aucun secret géré ailleurs que dans `models.json` sur le poste. Les modèles
sont des points d'accès internes EI. Pas de CI/CD autre que `make check` en local.

### 7.7 Scalability

Le parc visé est de 2 utilisatrices et quelques dizaines de projets. La limite connue est le
balayage de répertoire, mesuré acceptable à 500 projets. Au-delà, un cache mémoire invalidé au
rafraîchissement suffirait, et n'est pas construit ici.

## 8. Data Model

```
Project                              projects/<project_id>/project.json
  id              str                12 hexadécimaux
  name            str
  source_filename str
  created_at      str                ISO 8601 UTC
  next_version    int                compteur monotone, jamais décrémenté

SourceDocument                       projects/<project_id>/source/<source_filename>
                                     exactement un fichier

Version                              projects/<project_id>/v<n>/state.json
  id              str                "v1", "v2", ...
  status          str                running | done | failed | corrompue
  model           str                nom de l'entrée de modèle employée
  created_at      str
  error           str|null
  prompts         dict[str, str]     clé -> chemin relatif, ex. "prompts/distiller.md"
  context, scenarios, requirements, discards   inchangés par rapport à l'état actuel

PromptSet                            projects/<project_id>/v<n>/prompts/*.md
ModelEntry                           <config_dir>/models.json
  name, base_url, api_key, model     str
```

Relations : un `Project` porte exactement un `SourceDocument` et zéro à N `Version`. Une
`Version` porte un `PromptSet` et référence une `ModelEntry` par son `name`, sans la copier :
retirer un modèle de la table n'altère pas l'historique, la version garde le nom employé.

## 9. Impact Analysis

### 9.1 Affected Components

| File/Module | Impact | Description |
|---|---|---|
| `src/tgi/tgi.py` | Réécriture | 24 routes aujourd'hui, 18 après : 23 supprimées, `GET /` réécrite, 17 créées |
| `src/tgi/services/state_manager.py` | Réécriture | axe version, `project.json`, suppression de la fusion en place |
| `src/tgi/services/git_service.py` | Suppression | fichier entier |
| `src/tgi/services/llm.py` | Modification | `build_llm_client()`, fin du singleton figé |
| `src/tgi/services/model_store.py` | Création | lecture et écriture de `models.json` |
| `src/tgi/qc_export.py` | Création | feuille `QC` |
| `src/tgi/config.py` | Modification | `config_dir`, fin du défaut `changeme` comme valant configuré |
| `src/tgi/templates/` | Réécriture | 9 gabarits deviennent 4 : `base.html`, `project.html`, `parametres.html`, `partials/progress.html` |
| `src/tgi/progress.py` | Modification | progression portée par version |
| `src/tgi/events.py` | Modification | flux par version |
| `src/tgi/locks.py` | Modification | verrou par projet pour l'exécution, verrou pour `models.json` |
| `src/tgi/workbook.py` | Inchangé | le classeur de recette ne bouge pas dans cet incrément |

Les 18 routes d'arrivée, énumérées pour qu'aucune arithmétique ne soit à refaire :
`GET /`, `GET /parametres`, `GET /api/v1/projects`, `POST /api/v1/projects`,
`GET /api/v1/projects/{project_id}/source`, `POST /api/v1/projects/{project_id}/source`,
`GET /api/v1/projects/{project_id}/prompts`, `POST /api/v1/projects/{project_id}/runs`,
`GET /api/v1/projects/{project_id}/versions`,
`GET /api/v1/projects/{project_id}/versions/{version}`,
`GET /api/v1/projects/{project_id}/versions/{version}/events`,
`GET /api/v1/projects/{project_id}/versions/{version}/xlsx`,
`POST /api/v1/projects/{project_id}/versions/{version}/qc`,
`GET /api/v1/projects/{project_id}/versions/{version}/qc.xlsx`,
`DELETE /api/v1/projects/{project_id}/versions/{version}`,
`GET /api/v1/models`, `POST /api/v1/models`, `DELETE /api/v1/models/{name}`.

Les 23 routes supprimées sont les 24 actuelles moins `GET /` (`src/tgi/tgi.py:238`), qui est
réécrite plutôt que retirée. Dix-huit d'entre elles sont nommées dans FR-DEL-002 à FR-DEL-005,
`GET /projects/{project_id}/partials/history` apparaissant dans deux de ces listes et n'étant
comptée qu'une fois ;
les cinq restantes, qui disparaissent parce que leur fonction est reprise par le nouveau
contrat et non parce qu'une exigence les retire nommément, sont
`POST /upload` (`:267`, remplacée par `POST /api/v1/projects`),
`GET /projects/{project_id}` (`:312`, remplacée par la page unique),
`GET /projects/{project_id}/stream` (`:321`, remplacée par le flux par version),
`POST /projects/{project_id}/run` (`:368`, remplacée par `POST .../runs`) et
`GET /projects/{project_id}/partials/progress` (`:668`, dont le gabarit survit sous une
nouvelle URL). Les 23 sont ainsi énumérées et non seulement comptées.

### 9.2 Affected Requirements

Aucune : `specs/` était vide, ce document est le premier.

### 9.3 Affected Tests

Sur 304 tests existants, 62 sont réécrits ou supprimés, 69 sont étendus sans perdre leurs
assertions actuelles, et 173 ne bougent pas. Le partage détaillé est en 12.3.

| Test File | Tests | Action | Description |
|---|---|---|---|
| `tests/functional/test_api.py` | 36 | À réécrire | exerce `POST /upload`, la porte de validation et les sept onglets, tous supprimés |
| `tests/test_state_manager.py` | 16 | À réécrire | l'état passe de `state.json` racine à `project.json` plus un état par version |
| `tests/test_state_races.py` | 3 | À réécrire | mêmes structures, verrou désormais par projet |
| `tests/test_git_service.py` | 7 | À supprimer | le module disparaît, FR-DEL-002 |
| `tests/test_llm.py` | 42 | À étendre | ajout de `build_llm_client()`, FR-MOD-002 ; les 42 existants restent valides |
| `tests/test_config.py` | 17 | À étendre | `config_dir`, et le refus effectif qui remplace l'avertissement consultatif |
| `tests/test_progress.py` | 10 | À adapter | la progression est portée par une version |
| `tests/test_workbook.py` | 6 | Inchangés | `workbook.py` n'est pas touché |
| `tests/test_coverage_report.py` | 9 | Inchangés | |
| `tests/test_grammar.py` | 23 | Inchangés | |
| les 10 autres fichiers | 135 | Inchangés | `doc_parser`, `distiller`, `tracing_otlp`, `stats`, `validate`, `testset`, `test_schema`, `chat_context`, `logging_config`, `orchestrator_pipeline` |
| `tests/` | +91 | Création | la suite `E2E-` de la section 12 |

Les 7 tests de `tests/test_git_service.py` sont la seule suppression sèche. Elle est justifiée
par DEC-004 : le module qu'ils couvrent n'existe plus.

### 9.4 Affected Documentation

| Document | Section | Action | Description |
|---|---|---|---|
| `README.md` | parcours, routes | Réécrire | 18 routes, deux pages |
| `AGENTS.md` | Structure, Conventions | Mettre à jour | `git_service` retiré, `model_store` et `qc_export` ajoutés |
| `.agent_docs/pipeline.md` | validation humaine | Mettre à jour | la porte disparaît, voir section 13 |
| `WINDOWS.md` | premier lancement | Mettre à jour | les modèles se saisissent dans l'interface, plus en variables |
| `INSTALL.md` | configuration | Mettre à jour | `TGI_CONFIG_DIR` |
| `docs/architecture.html` | diagrammes | Mettre à jour | versions, plus de git |

### 9.5 Dependencies & Risks

Aucune dépendance ajoutée ni retirée ; `openpyxl>=3.1.5` suffit pour la feuille QC.
Rupture pour les projets existants, assumée et cadrée par FR-NEW-046 : ils sont lisibles en
liste, pas exécutables. Un seul projet est concerné, sur le poste de développement. Pas de
migration, pas de retour arrière prévu autre que le retour au commit précédent.

## 10. Documentation Requirements

`README.md` : nouveau parcours, les 18 routes, la table de modèles, la disposition disque.
`AGENTS.md` : index de structure, conventions de persistance, mention explicite que la porte de
validation n'existe plus et pourquoi. `.agent_docs/pipeline.md` : section « validation humaine »
réécrite avec la décision DEC-002 et sa justification. `WINDOWS.md` et `INSTALL.md` :
`TGI_CONFIG_DIR`, et le fait qu'aucune variable de modèle n'est requise au démarrage.

## 11. Traceability Matrix

Les neuf premières lignes sont les scénarios, et pour elles les trois colonnes portent bien la
nature annoncée. Les lignes suivantes regroupent des préoccupations transverses, exigences non
fonctionnelles et suppressions ; pour celles-là les colonnes ne font que répartir les tests en
trois groupes et ne prétendent pas à la nature indiquée en 12.1.

| Scenario | Functional Req | E2E (Happy) | E2E (Failure) | E2E (Edge) |
|---|---|---|---|---|
| SC-001 | FR-NEW-016, FR-NEW-017, FR-NEW-018, FR-NEW-019 | E2E-001 | E2E-003, E2E-004, E2E-006, E2E-009 | E2E-005, E2E-002, E2E-007, E2E-008 |
| SC-002 | FR-NEW-001, FR-NEW-003, FR-NEW-004, FR-NEW-005, FR-NEW-006, FR-NEW-007, FR-MOD-003, FR-DEL-001 | E2E-010 | E2E-012, E2E-013, E2E-014, E2E-018, E2E-019, E2E-020, E2E-021 | E2E-016, E2E-017, E2E-011, E2E-015 |
| SC-003 | FR-NEW-008, FR-NEW-009 | E2E-022 | E2E-023, E2E-024, E2E-027 | E2E-025, E2E-026, E2E-028, E2E-090 |
| SC-004 | FR-NEW-020, FR-NEW-021, FR-NEW-022, FR-NEW-023, FR-NEW-024, FR-NEW-025, FR-NEW-029, FR-NEW-030, FR-NEW-041 | E2E-029 | E2E-030, E2E-031, E2E-032, E2E-033, E2E-034, E2E-037, E2E-039, E2E-041 | E2E-035, E2E-036, E2E-038, E2E-040 |
| SC-005 | FR-NEW-010, FR-NEW-011, FR-NEW-012, FR-NEW-015, FR-NEW-047, FR-MOD-001 | E2E-042 | E2E-045, E2E-046, E2E-049, E2E-089 | E2E-047, E2E-043, E2E-044, E2E-048, E2E-091 |
| SC-006 | FR-NEW-013, FR-NEW-014 | E2E-050 | E2E-052, E2E-053, E2E-056 | E2E-051, E2E-054, E2E-055 |
| SC-007 | FR-NEW-031, FR-NEW-032, FR-NEW-033, FR-NEW-046 | E2E-057 | E2E-059, E2E-060 | E2E-058, E2E-061, E2E-062, E2E-063 |
| SC-008 | FR-NEW-026, FR-NEW-027, FR-NEW-028 | E2E-064 | E2E-066, E2E-067, E2E-068, E2E-070, E2E-071, E2E-072 | E2E-073, E2E-065, E2E-069, E2E-074 |
| SC-009 | FR-NEW-034, FR-NEW-035, FR-NEW-036, FR-NEW-037, FR-NEW-038, FR-NEW-039 | E2E-075 | E2E-077, E2E-078, E2E-080 | E2E-079, E2E-082, E2E-076, E2E-081 |
| NFR1 disque seul | FR-NEW-045, FR-NEW-002 | E2E-085 | E2E-088 | E2E-083, E2E-036 |
| NFR2 | FR-NEW-002, FR-NEW-045 | E2E-083 | E2E-084 | E2E-085 |
| NFR4 | FR-NEW-029 | E2E-086 | E2E-030, E2E-070, E2E-072 | E2E-086 |
| NFR3 | FR-NEW-026 | E2E-087 | E2E-072 | E2E-064 |
| Suppression git | FR-DEL-002 | E2E-088 | E2E-084 | E2E-085, E2E-083 |
| Suppression porte de validation | FR-DEL-003 | E2E-029 | E2E-088 | E2E-042, E2E-010 |
| Suppression des onglets | FR-DEL-004 | E2E-088 | E2E-089 | E2E-058, E2E-085 |
| Suppression export zip | FR-DEL-005 | E2E-029 | E2E-088 | E2E-083, E2E-034 |
| Client LLM par exécution | FR-MOD-002 | E2E-029 | E2E-031, E2E-032 | E2E-044, E2E-070 |
| Sécurité chemins, attaques réelles | FR-NEW-040, FR-NEW-003, FR-NEW-056 | E2E-015 | E2E-094, E2E-095, E2E-096, E2E-097 | E2E-007, E2E-063 |
| Rejets du routeur, sans valeur de preuve | FR-NEW-040 | E2E-015 | E2E-094 | E2E-026, E2E-054 |
| Pipeline réellement piloté | FR-NEW-048, FR-NEW-049, FR-NEW-062 | E2E-092 | E2E-041, E2E-031 | E2E-029, E2E-035, E2E-040 |
| Cycle de vie d'une exécution | FR-NEW-050, FR-NEW-051, FR-NEW-052, FR-NEW-053 | E2E-029 | E2E-093, E2E-032, E2E-041 | E2E-031, E2E-038, E2E-048 |
| Contrats de la table de modèles | FR-NEW-054, FR-NEW-055 | E2E-064 | E2E-066, E2E-067, E2E-068 | E2E-073, E2E-030, E2E-070 |
| Formes dégradées et ordres | FR-NEW-059, FR-NEW-060, FR-NEW-061 | E2E-050 | E2E-013, E2E-014, E2E-052 | E2E-046, E2E-051, E2E-060 |
| Observabilité et outillage | FR-NEW-057, FR-NEW-058 | E2E-099 | E2E-098 | E2E-069, E2E-085 |
| Interface | FR-NEW-042, FR-NEW-043, FR-NEW-044 | E2E-029 | E2E-089 | E2E-058, E2E-086 |

## 12. End-to-End Test Suite

> **Ceci est le contrat.** Un agent d'implémentation s'en sert comme définition du terminé.

### 12.1 Test Summary

Les 99 tests sont spécifiés dans l'ordre des scénarios. Le tableau ci-dessous donne
l'identifiant, la catégorie, le scénario et la priorité ; les spécifications complètes suivent
en 12.2.

| Test ID | Action | Category | Scenario | FR refs | Priority |
|---|---|---|---|---|---|
| E2E-001 | New | happy | SC-001 | FR-NEW-010, FR-NEW-016, FR-NEW-017, FR-NEW-018, FR-NEW-048 | Critical |
| E2E-002 | New | state transition | SC-001 | FR-NEW-018, FR-NEW-016, FR-NEW-017, FR-NEW-048 | Critical |
| E2E-003 | New | failure | SC-001 | FR-NEW-019 | High |
| E2E-004 | New | failure | SC-001 | FR-NEW-019 | High |
| E2E-005 | New | edge | SC-001 | FR-NEW-017, FR-NEW-019 | Medium |
| E2E-006 | New | failure | SC-001 | FR-NEW-040 | Medium |
| E2E-007 | New | security | SC-001 | FR-NEW-019, FR-NEW-040 | Critical |
| E2E-008 | New | side effect | SC-001 | FR-NEW-017, FR-NEW-018, FR-NEW-016, FR-NEW-047 | High |
| E2E-009 | New | failure | SC-001 | FR-NEW-021 | High |
| E2E-010 | New | happy | SC-002 | FR-NEW-001, FR-NEW-002, FR-MOD-003, FR-DEL-001, FR-DEL-003 | Critical |
| E2E-011 | New | side effect | SC-002 | FR-NEW-007, FR-NEW-029 | Critical |
| E2E-012 | New | failure | SC-002 | FR-MOD-003, FR-DEL-001, FR-NEW-003 | Critical |
| E2E-013 | New | failure | SC-002 | FR-NEW-004, FR-NEW-005, FR-NEW-006, FR-NEW-059 | Critical |
| E2E-014 | New | failure | SC-002 | FR-NEW-005, FR-NEW-004, FR-NEW-059 | High |
| E2E-015 | New | security | SC-002 | FR-NEW-003 | Critical |
| E2E-016 | New | edge | SC-002 | FR-NEW-003, FR-NEW-008 | Medium |
| E2E-017 | New | edge | SC-002 | FR-NEW-006, FR-NEW-041, FR-NEW-005, FR-NEW-059 | Medium |
| E2E-018 | New | failure | SC-002 | FR-NEW-001, FR-NEW-004 | Medium |
| E2E-019 | New | failure | SC-002 | FR-NEW-041, FR-NEW-006 | High |
| E2E-020 | New | failure | SC-002 | FR-NEW-001 | High |
| E2E-021 | New | failure | SC-002 | FR-NEW-001, FR-NEW-004, FR-NEW-005, FR-NEW-007 | High |
| E2E-022 | New | happy | SC-003 | FR-NEW-008, FR-NEW-003, FR-NEW-009, FR-MOD-003 | Critical |
| E2E-023 | New | failure | SC-003 | FR-NEW-008 | Medium |
| E2E-024 | New | failure | SC-003 | FR-NEW-008 | High |
| E2E-025 | New | edge | SC-003 | FR-NEW-008 | Medium |
| E2E-026 | New | edge | SC-003 | FR-NEW-040, FR-NEW-008 | Critical |
| E2E-027 | New | failure | SC-003 | FR-NEW-009, FR-NEW-003 | Critical |
| E2E-028 | New | data integrity | SC-003 | FR-NEW-008 | High |
| E2E-029 | New | happy | SC-004 | FR-NEW-020, FR-NEW-022, FR-NEW-023, FR-NEW-030, FR-MOD-002, FR-DEL-003, FR-DEL-005, FR-NEW-049, FR-NEW-052, FR-NEW-062 | Critical |
| E2E-030 | New | failure | SC-004 | FR-NEW-029, FR-NEW-054, FR-NEW-055 | Critical |
| E2E-031 | New | failure | SC-004 | FR-NEW-024, FR-NEW-030, FR-MOD-002, FR-NEW-050, FR-NEW-051, FR-NEW-052 | Critical |
| E2E-032 | New | failure | SC-004 | FR-NEW-024, FR-NEW-025, FR-MOD-002, FR-MOD-001, FR-NEW-050, FR-NEW-051 | Critical |
| E2E-033 | New | failure | SC-004 | FR-NEW-021, FR-NEW-011, FR-NEW-020 | Critical |
| E2E-034 | New | failure | SC-004 | FR-NEW-023, FR-NEW-014, FR-NEW-039, FR-DEL-005 | High |
| E2E-035 | New | edge | SC-004 | FR-NEW-023, FR-MOD-001, FR-NEW-045, FR-NEW-049, FR-NEW-057 | High |
| E2E-036 | New | side effect | SC-004 | FR-NEW-002, FR-NEW-045, FR-NEW-025, FR-NEW-062 | High |
| E2E-037 | New | failure | SC-004 | FR-NEW-040, FR-NEW-020, FR-NEW-055 | Medium |
| E2E-038 | New | performance | SC-004 | FR-NEW-022, FR-NEW-049, FR-NEW-052 | Medium |
| E2E-039 | New | failure | SC-004 | FR-NEW-041, FR-NEW-025, FR-NEW-024 | High |
| E2E-040 | New | data integrity | SC-004 | FR-NEW-022, FR-NEW-049, FR-NEW-052 | High |
| E2E-041 | New | failure | SC-004 | FR-NEW-024, FR-NEW-049, FR-NEW-050, FR-NEW-051, FR-NEW-052 | High |
| E2E-042 | New | happy | SC-005 | FR-NEW-010, FR-NEW-011, FR-NEW-012, FR-NEW-020, FR-DEL-003, FR-NEW-049, FR-NEW-053 | Critical |
| E2E-043 | New | data integrity | SC-005 | FR-MOD-001, FR-NEW-010, FR-NEW-012 | Critical |
| E2E-044 | New | state transition | SC-005 | FR-NEW-017, FR-NEW-030, FR-NEW-047, FR-MOD-002 | Critical |
| E2E-045 | New | failure | SC-005 | FR-NEW-012, FR-NEW-044, FR-NEW-015, FR-NEW-010 | High |
| E2E-046 | New | failure | SC-005 | FR-NEW-015, FR-NEW-012, FR-NEW-047, FR-NEW-060, FR-NEW-061 | High |
| E2E-047 | New | edge | SC-005 | FR-NEW-011, FR-NEW-012 | Medium |
| E2E-048 | New | state transition | SC-005 | FR-NEW-011, FR-NEW-024, FR-NEW-050, FR-NEW-053 | High |
| E2E-049 | New | failure | SC-005 | FR-NEW-021 | High |
| E2E-050 | New | happy | SC-006 | FR-NEW-013, FR-NEW-012, FR-NEW-010, FR-NEW-060 | Critical |
| E2E-051 | New | edge | SC-006 | FR-NEW-013, FR-NEW-009, FR-NEW-012, FR-NEW-060, FR-NEW-061 | Critical |
| E2E-052 | New | failure | SC-006 | FR-NEW-014, FR-NEW-040 | Critical |
| E2E-053 | New | failure | SC-006 | FR-NEW-013, FR-NEW-040, FR-NEW-044, FR-NEW-060 | Medium |
| E2E-054 | New | edge | SC-006 | FR-NEW-040 | Critical |
| E2E-055 | New | side effect | SC-006 | FR-NEW-011 | High |
| E2E-056 | New | failure | SC-006 | FR-NEW-013 | High |
| E2E-057 | New | happy | SC-007 | FR-NEW-031 | Critical |
| E2E-058 | New | edge | SC-007 | FR-NEW-031, FR-NEW-042, FR-NEW-046, FR-DEL-004 | High |
| E2E-059 | New | failure | SC-007 | FR-NEW-031, FR-NEW-032, FR-NEW-033, FR-NEW-046 | High |
| E2E-060 | New | failure | SC-007 | FR-NEW-033, FR-NEW-031, FR-NEW-061 | High |
| E2E-061 | New | side effect | SC-007 | FR-NEW-031, FR-NEW-032, FR-NEW-002 | Critical |
| E2E-062 | New | performance | SC-007 | FR-NEW-031 | Medium |
| E2E-063 | New | security | SC-007 | FR-NEW-032, FR-NEW-040 | High |
| E2E-064 | New | happy | SC-008 | FR-NEW-026, FR-NEW-027, FR-NEW-028, FR-NEW-043, FR-NEW-054 | Critical |
| E2E-065 | New | side effect | SC-008 | FR-NEW-027, FR-NEW-028, FR-NEW-026 | High |
| E2E-066 | New | failure | SC-008 | FR-NEW-027 | High |
| E2E-067 | New | failure | SC-008 | FR-NEW-027, FR-NEW-054 | High |
| E2E-068 | New | failure | SC-008 | FR-NEW-027, FR-NEW-054, FR-NEW-059 | High |
| E2E-069 | New | security | SC-008 | FR-NEW-028, FR-NEW-043 | Critical |
| E2E-070 | New | failure | SC-008 | FR-NEW-029, FR-NEW-043, FR-MOD-002 | Critical |
| E2E-071 | New | failure | SC-008 | FR-NEW-027, FR-NEW-055 | Medium |
| E2E-072 | New | failure | SC-008 | FR-NEW-029, FR-NEW-026, FR-NEW-042, FR-NEW-043 | Critical |
| E2E-073 | New | edge | SC-008 | FR-NEW-027 | Medium |
| E2E-074 | New | data integrity | SC-008 | FR-NEW-027 | High |
| E2E-075 | New | happy | SC-009 | FR-NEW-034, FR-NEW-035, FR-NEW-036, FR-NEW-038, FR-NEW-010 | Critical |
| E2E-076 | New | side effect | SC-009 | FR-NEW-034, FR-NEW-045 | High |
| E2E-077 | New | failure | SC-009 | FR-NEW-039, FR-NEW-038, FR-NEW-014 | High |
| E2E-078 | New | failure | SC-009 | FR-NEW-039, FR-NEW-037 | High |
| E2E-079 | New | edge | SC-009 | FR-NEW-036, FR-NEW-035, FR-NEW-037 | Critical |
| E2E-080 | New | failure | SC-009 | FR-NEW-037, FR-NEW-036, FR-NEW-034 | High |
| E2E-081 | New | data integrity | SC-009 | FR-NEW-035, FR-NEW-034 | Critical |
| E2E-082 | New | edge | SC-009 | FR-NEW-038, FR-NEW-035 | Medium |
| E2E-083 | New | data integrity | NFR2 | FR-NEW-002, FR-NEW-010, FR-NEW-008, FR-DEL-002, FR-DEL-005, FR-NEW-056 | Critical |
| E2E-084 | New | failure | NFR2 | FR-NEW-031, FR-NEW-015, FR-NEW-046, FR-NEW-033, FR-DEL-002 | Critical |
| E2E-085 | New | data integrity | NFR1 | FR-NEW-045, FR-NEW-002, FR-MOD-003, FR-DEL-001, FR-DEL-002, FR-DEL-004, FR-NEW-056, FR-NEW-058 | Critical |
| E2E-086 | New | edge | NFR4 | FR-NEW-029, FR-NEW-042, FR-NEW-007 | Critical |
| E2E-087 | New | side effect | NFR3 | FR-NEW-026, FR-NEW-027 | Critical |
| E2E-088 | New | state transition | NFR1 | FR-DEL-002, FR-DEL-003, FR-DEL-004, FR-DEL-005 | High |
| E2E-089 | New | failure | SC-005 | FR-NEW-044, FR-NEW-042, FR-DEL-004 | Medium |
| E2E-090 | New | side effect | SC-003 | FR-NEW-008, FR-NEW-045 | Medium |
| E2E-091 | New | side effect | SC-005 | FR-NEW-002, FR-NEW-010, FR-NEW-011 | High |
| E2E-092 | New | side effect | SC-001 | FR-NEW-048, FR-NEW-017, FR-NEW-049, FR-NEW-062 | Critical |
| E2E-093 | New | failure | SC-005 | FR-NEW-053, FR-NEW-021, FR-NEW-014, FR-NEW-052, FR-NEW-061 | Critical |
| E2E-094 | New | security | SC-003 | FR-NEW-040 | Critical |
| E2E-095 | New | security | SC-006 | FR-NEW-040, FR-NEW-013 | Critical |
| E2E-096 | New | security | SC-007 | FR-NEW-040, FR-NEW-042, FR-NEW-044 | Critical |
| E2E-097 | New | security | SC-004 | FR-NEW-056, FR-NEW-045, FR-NEW-048 | Critical |
| E2E-098 | New | failure | NFR1 | FR-NEW-057, FR-NEW-010, FR-NEW-058 | High |
| E2E-099 | New | side effect | SC-004 | FR-NEW-058, FR-NEW-028, FR-NEW-057 | Medium |

**Coverage statistics:** happy 9, failure 43, side effects 12, edge 14, state transitions 4,
security 8, data integrity 7, performance 2, soit **99 tests**. **Happy:failure ratio 1:4.8**,
ce qui dépasse 1:1.

Les 8 derniers, E2E-092 à E2E-099, sont nés de l'audit d'implémentabilité et non de la
conception initiale, et quatre d'entre eux remplacent une couverture de sécurité qui n'en était
pas. Le défaut a été trouvé en deux temps, et les deux méritent d'être consignés parce qu'ils
se ressemblent :

1. **La charge était absorbée par le routeur.** E2E-026 et E2E-054 employaient `..%2F..%2F` ;
   Starlette décode `%2F` avant le routage et un segment contenant `/` ne peut appareiller un
   `{param}`, donc la requête recevait le 404 du routeur sans qu'aucun gestionnaire ne
   s'exécute. Les deux tests étaient verts sur du code sans la moindre validation. Ils sont
   conservés et **reclassés Edge**, pour que personne ne les compte comme une preuve.
2. **Le leurre était incomplet.** Leurs remplaçants en `%2E%2E` atteignaient bien le
   gestionnaire, mais visaient un dossier dépourvu de `project.json` ou de `state.json` : la
   lecture échouait et le 404 tombait tout seul. Ils étaient donc encore verts sans validation.
   E2E-094, E2E-095 et E2E-096 posent désormais des **leurres complets**, un projet et une
   version valides à l'emplacement visé, de sorte que l'absence de validation produise un 200
   qui divulgue `ROOT-LEAK`, `PARENT-LEAK` ou `VERSION-LEAK`, ou efface le répertoire des
   projets.

Un test de sécurité vert avant le correctif n'est pas un test qui passe, c'est un test qui
n'attaque pas, et il faut deux conditions pour qu'il attaque : que la charge atteigne le puits,
et que le puits ait quelque chose à rendre.

### 12.2 New Test Specifications

**Pilote et montage communs.** Pilote HTTP : `AsyncClient(ASGITransport(app))`. Pilote FS :
assertion sur le système de fichiers. Tout vit sous `tmp_path` : `TGI_PROJECTS_DIR`,
`TGI_CONFIG_DIR`, `TGI_LOGS`. Le LLM est toujours simulé, jamais de réseau.

Montages partagés, à créer dans `tests/conftest.py` :
- `spec_md` : fichier `specification_habilitations.md` de 12 288 octets, contenant le titre
  `F03.EU05.CU01 Déléguer temporairement` et les références `F03.EU05.CU01.RM01`, `.RM02`,
  `.EM01`, `.M01`.
- `project_with_source` : dépose `spec_md`, renvoie `pid`.
- `models_file` : `models.json` portant une entrée
  `{"name": "watsonx-mistral-large", "base_url": "https://eu-de.ml.cloud.ibm.com", "api_key": "sk-test-0001", "model": "mistralai/mistral-large"}`.
- `no_models` : `TGI_CONFIG_DIR` sur un dossier vide, sans `models.json`.
- `fake_llm_run` : client simulé rendant 1 scénario, 2 tests, 3 étapes, et comptant ses appels
  dans `.calls`.

#### E2E-001: les prompts proposés sont les prompts par défaut et l'édition part avec la version
- **Category:** Core Journey
- **Scenario:** SC-001
- **Requirements:** FR-NEW-016, FR-NEW-017
- **Driver:** HTTP client + file system
- **Preconditions:** `models_file`, `project_with_source` donnant `pid`.
- **Steps:**
  - Given `GET /api/v1/projects/{pid}/prompts` renvoie 200 et `json()["distiller"]` égale le
    contenu UTF-8 exact de `src/tgi/prompts/distiller.md`
  - When `POST /api/v1/projects/{pid}/runs` avec
    `{"model": "watsonx-mistral-large", "prompts": {"distiller": "Tu listes les exigences. Ne jamais interroger."}}`
  - Then statut 202, corps `{"version": "v1"}`
  - And le fichier `projects/{pid}/v1/prompts/distiller.md` existe et son texte égale
    `"Tu listes les exigences. Ne jamais interroger."`
  - And `projects/{pid}/v1/state.json` a `prompts.distiller` égal à `"prompts/distiller.md"`
  - And l'empreinte sha256 de `src/tgi/prompts/distiller.md` est inchangée
- **Cleanup:** `tmp_path`
- **Priority:** Critical

#### E2E-002: la v2 repart du prompt par défaut et n'hérite pas de l'édition de la v1
- **Category:** State Transition
- **Scenario:** SC-001
- **Requirements:** FR-NEW-018
- **Driver:** HTTP client + file system
- **Preconditions:** état de E2E-001, v1 terminée.
- **Steps:**
  - Given `projects/{pid}/v1/prompts/distiller.md` contient l'édition
  - When `GET /api/v1/projects/{pid}/prompts` puis
    `POST /api/v1/projects/{pid}/runs` avec `{"model": "watsonx-mistral-large", "prompts": {}}`
  - Then le corps du GET a `distiller` égal au prompt livré, et non à
    `"Tu listes les exigences. Ne jamais interroger."`
  - And `projects/{pid}/v2/prompts/distiller.md` égale le prompt livré octet pour octet
  - And `projects/{pid}/v1/prompts/distiller.md` contient toujours l'édition
- **Priority:** Critical

#### E2E-003: une clé de prompt inconnue est refusée en 422
- **Category:** Error
- **Scenario:** SC-001
- **Requirements:** FR-NEW-019
- **Driver:** HTTP client + file system
- **Preconditions:** `models_file`, `project_with_source`.
- **Steps:**
  - When `POST /api/v1/projects/{pid}/runs` avec
    `{"model": "watsonx-mistral-large", "prompts": {"destiller": "x"}}`
  - Then statut 422, corps exactement `{"detail": "prompt inconnu: destiller"}`
  - And `projects/{pid}/v1` n'existe pas
- **Priority:** High

#### E2E-004: un prompt vide est refusé et le défaut n'est pas écrasé par du vide
- **Category:** Error
- **Scenario:** SC-001
- **Requirements:** FR-NEW-019
- **Driver:** HTTP client + file system
- **Steps:**
  - When `POST .../runs` avec `{"model": "watsonx-mistral-large", "prompts": {"distiller": "   "}}`
  - Then 422, `{"detail": "prompt vide: distiller"}`
  - And `projects/{pid}/v1` n'existe pas
- **Priority:** High

#### E2E-005: un prompt de 10 008 caractères unicode est stocké sans altération
- **Category:** Edge
- **Scenario:** SC-001
- **Requirements:** FR-NEW-017
- **Steps:**
  - When `POST .../runs` avec `prompts.distiller` égal à `"Exigence é😀 " * 834`. Le motif fait
    12 caractères, dont une lettre accentuée et un emoji hors du plan multilingue de base, donc
    la chaîne fait 10 008 caractères
  - Then 202
  - And `projects/{pid}/v1/prompts/distiller.md` lu en UTF-8 égale la chaîne envoyée, et sa
    longueur en caractères est 10 008, ce qui vérifie qu'aucune troncature à l'octet n'a coupé
    un caractère en deux
- **Priority:** Medium

#### E2E-006: éditer le prompt d'un projet inexistant répond 404
- **Category:** Error
- **Scenario:** SC-001
- **Requirements:** FR-NEW-040
- **Steps:**
  - When `POST /api/v1/projects/aaaaaaaaaaaa/runs` avec un prompt valide
  - Then 404, `{"detail": "projet inconnu: aaaaaaaaaaaa"}`
- **Priority:** Medium

#### E2E-007: une clé de prompt en traversée de chemin n'écrit rien hors de la version
- **Category:** Security
- **Scenario:** SC-001
- **Requirements:** FR-NEW-019, FR-NEW-040
- **Steps:**
  - When `POST .../runs` avec `{"prompts": {"../../../../etc/passwd": "x"}}`, puis avec
    `{"prompts": {"distiller/../../escape": "x"}}`
  - Then les deux répondent 422 `{"detail": "prompt inconnu: ..."}`
  - And `list(tmp_path.rglob("passwd*")) == []` et `list(tmp_path.rglob("escape*")) == []`
- **Priority:** Critical

#### E2E-008: le prompt utilisé est relu depuis la version par une application neuve
- **Category:** Side Effect
- **Scenario:** SC-001
- **Requirements:** FR-NEW-017, FR-NEW-018, FR-NEW-016, FR-NEW-047
- **Driver:** direct call + HTTP client
- **Preconditions:** E2E-001 terminé ; construire une **seconde** instance `create_app()` sur le
  même répertoire de projets, simulant un redémarrage.
- **Steps:**
  - When `GET /api/v1/projects/{pid}/versions/v1` sur la nouvelle instance
  - Then 200 et `json()["prompts"]["distiller"]` égale
    `"Tu listes les exigences. Ne jamais interroger."`, relu du disque et non de la mémoire
- **Priority:** High

#### E2E-009: éditer le prompt pendant une génération répond 409
- **Category:** Error
- **Scenario:** SC-001
- **Requirements:** FR-NEW-021
- **Preconditions:** LLM simulé bloqué sur un `asyncio.Event`, v1 reste `running`.
- **Steps:**
  - When un second `POST .../runs` avec `{"prompts": {"distiller": "autre"}}`
  - Then 409, `{"detail": "génération déjà en cours"}`
  - And `projects/{pid}/v2` n'existe pas
- **Cleanup:** libérer l'événement et attendre la tâche dans un `finally`
- **Priority:** High

#### E2E-010: déposer une spécification crée un projet autoportant
- **Category:** Core Journey
- **Scenario:** SC-002
- **Requirements:** FR-NEW-001, FR-MOD-003
- **Steps:**
  - When `POST /api/v1/projects` multipart avec
    `file=("specification_habilitations.md", 12 288 octets, "text/markdown")`
  - Then 201, `json()["id"]` correspond à `^[0-9a-f]{12}$`,
    `json()["source_filename"] == "specification_habilitations.md"`
  - And `projects/{id}/project.json` existe
  - And `projects/{id}/source/specification_habilitations.md` existe avec `st_size == 12288`
  - And `(projects / "_uploads").exists() is False`
- **Priority:** Critical

#### E2E-011: déposer ne lance aucune génération et n'appelle aucun modèle
- **Category:** Side Effect
- **Scenario:** SC-002
- **Requirements:** FR-NEW-007
- **Steps:**
  - When le même dépôt, avec `fake_llm_run` injecté
  - Then `fake_llm_run.calls == []`
  - And `sorted(p.name for p in (projects / id).iterdir()) == ["project.json", "source"]`
  - And `GET /api/v1/projects/{id}/versions` renvoie 200 et `{"versions": []}`
- **Priority:** Critical

#### E2E-012: deux projets nourris du même nom de fichier gardent chacun sa source
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-MOD-003, FR-DEL-001
- **Steps:**
  - When `POST /api/v1/projects` avec `specification_habilitations.md` et le corps `b"A" * 1024`,
    puis le **même nom** avec le corps `b"B" * 2048`
  - Then deux identifiants distincts, `id1 != id2`
  - And `projects/{id1}/source/specification_habilitations.md` vaut `b"A" * 1024`
  - And `projects/{id2}/source/specification_habilitations.md` vaut `b"B" * 2048`
- **Priority:** Critical

#### E2E-013: un fichier de zéro octet est refusé en 400
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-004
- **Steps:**
  - When `POST /api/v1/projects` avec `file=("vide.md", b"", "text/markdown")`
  - Then 400, `{"detail": "document vide"}`
  - And `list(projects.iterdir()) == []`
- **Priority:** Critical

#### E2E-014: un png n'est pas un document et est refusé en 415
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-005
- **Steps:**
  - When `POST /api/v1/projects` avec `file=("capture.png", en-tête PNG + 300 octets, "image/png")`
  - Then 415, `{"detail": "format non supporté: .png"}`
  - And aucun dossier de projet créé
- **Priority:** High

#### E2E-015: un nom de fichier en traversée de chemin est assaini dans le dossier du projet
- **Category:** Security
- **Scenario:** SC-002
- **Requirements:** FR-NEW-003
- **Steps:**
  - When `POST /api/v1/projects` avec `file=("../../../etc/passwd.md", b"# spec\n" * 100, "text/markdown")`
  - Then 201 et `json()["source_filename"] == "passwd.md"`, le nom de base étant pris avant
    l'assainissement
  - And le fichier est à `projects/{id}/source/passwd.md`
  - And `(tmp_path / "etc").exists() is False`
  - And aucun fichier du dépôt ne porte un nom contenant `..`, ce qui exclut l'aplatissement
    `.._.._.._etc_passwd.md` que produirait l'ordre inverse
  - And le même appel avec le séparateur Windows `..\..\..\etc\passwd.md` donne également
    `passwd.md`
- **Priority:** Critical

#### E2E-016: un nom de fichier unicode est conservé tel quel sur le disque
- **Category:** Edge
- **Scenario:** SC-002
- **Requirements:** FR-NEW-003
- **Steps:**
  - When dépôt de `spécification_été_📄.docx` avec des octets docx valides
  - Then 201
  - And `projects/{id}/source/spécification_été_📄.docx` existe, comparaison faite après
    `unicodedata.normalize("NFC", nom)`
- **Priority:** Medium

#### E2E-017: un document de 60 Mo est refusé en 413
- **Category:** Edge
- **Scenario:** SC-002
- **Requirements:** FR-NEW-006
- **Steps:**
  - When dépôt d'un `.md` de 62 914 560 octets
  - Then 413, `{"detail": "document trop volumineux (max 50 Mo)"}`
  - And `list(projects.iterdir()) == []`
- **Priority:** Medium

#### E2E-018: un dépôt sans partie file répond 422
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-001
- **Steps:**
  - When `POST /api/v1/projects` avec `data={"name": "x"}` et aucune partie `file`
  - Then 422 et `json()["detail"][0]["loc"] == ["body", "file"]`
- **Priority:** Medium

#### E2E-019: un disque plein pendant l'écriture ne laisse pas de projet à moitié créé
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-041
- **Preconditions:** l'écriture de la source est remplacée par un appel levant
  `OSError(errno.ENOSPC, "No space left on device")` après 4 096 octets.
- **Steps:**
  - When dépôt de `specification_habilitations.md`
  - Then 507, `{"detail": "disque plein, projet non créé"}`
  - And `list(projects.iterdir()) == []`
- **Priority:** High

#### E2E-020: deux dépôts simultanés produisent deux identifiants distincts
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-001
- **Steps:**
  - When deux `POST /api/v1/projects` du même nom dans un seul `asyncio.TaskGroup`
  - Then les deux répondent 201, `id1 != id2`, et `len(list(projects.iterdir())) == 2`
- **Priority:** High

#### E2E-021: un docx corrompu est refusé en 400
- **Category:** Error
- **Scenario:** SC-002
- **Requirements:** FR-NEW-001
- **Steps:**
  - When dépôt de `file=("spec.docx", b"PK\x03\x04" + b"\x00" * 500, mime docx)`
  - Then 400, `{"detail": "document illisible"}`
  - And `list(projects.iterdir()) == []`
- **Priority:** High

#### E2E-022: la source déposée se retélécharge à l'octet près
- **Category:** Core Journey
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Preconditions:** `project_with_source`, 12 288 octets, empreinte sha256 notée `S`.
- **Steps:**
  - When `GET /api/v1/projects/{pid}/source`
  - Then 200, `len(response.content) == 12288`, `sha256(response.content).hexdigest() == S`
  - And l'en-tête `content-disposition` contient `filename="specification_habilitations.md"`
  - And `content-type == "text/markdown; charset=utf-8"`
- **Priority:** Critical

#### E2E-023: télécharger la source d'un projet inconnu répond 404
- **Category:** Error
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Steps:**
  - When `GET /api/v1/projects/bbbbbbbbbbbb/source`
  - Then 404, `{"detail": "projet inconnu: bbbbbbbbbbbb"}`
- **Priority:** Medium

#### E2E-024: une source supprimée à la main répond 404 et pas 500
- **Category:** Error
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Preconditions:** `project_with_source`, puis suppression du fichier source sur disque.
- **Steps:**
  - When `GET /api/v1/projects/{pid}/source`
  - Then 404, `{"detail": "source absente"}`
  - And `GET /api/v1/projects` liste toujours le projet, avec `status == "source_manquante"`
- **Priority:** High

#### E2E-025: un nom unicode est exposé en RFC 5987 dans le content-disposition
- **Category:** Edge
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Preconditions:** projet créé depuis `spécification_été_📄.docx`.
- **Steps:**
  - When `GET .../source`
  - Then 200 et `content-disposition` contient
    `filename*=UTF-8''sp%C3%A9cification_%C3%A9t%C3%A9_%F0%9F%93%84.docx` ainsi qu'un repli
    ASCII `filename="specification_ete_.docx"`
- **Priority:** Medium

#### E2E-026: une URL mal formée est rejetée avant d'atteindre un gestionnaire
- **Category:** Edge
- **Scenario:** SC-003
- **Requirements:** FR-NEW-040
- **Steps:**
  - When `GET /api/v1/projects/..%2F..%2Fetc/source`
  - Then 404, et aucun corps de réponse ne contient `root:`
  - **Ce test ne vérifie pas FR-NEW-040 et ne prétend pas l'attaquer.** Starlette décode `%2F`
    avant le routage, et un segment contenant `/` ne peut appareiller un `{param}` : la requête
    reçoit le 404 du routeur sans qu'aucun gestionnaire ne s'exécute, donc il est vert même sur
    du code sans validation. Il est conservé parce que ce comportement du routeur mérite d'être
    verrouillé, et classé **Edge** et non Security pour que personne ne le compte comme une
    preuve. L'attaque réelle est en E2E-094.
- **Priority:** Critical

#### E2E-027: un projet n'accepte qu'une seule source
- **Category:** Error
- **Scenario:** SC-003
- **Requirements:** FR-NEW-009
- **Steps:**
  - When `POST /api/v1/projects/{pid}/source` avec un autre fichier `autre.md`
  - Then 409, `{"detail": "le projet a déjà une source"}`
  - And `sorted(p.name for p in (projects / pid / "source").iterdir()) == ["specification_habilitations.md"]`
- **Priority:** Critical

#### E2E-028: un pdf binaire fait l'aller-retour sans altération de son sha256
- **Category:** Data Integrity
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Preconditions:** projet créé depuis un PDF de 1 048 576 octets, empreinte `P`.
- **Steps:**
  - When `GET .../source`
  - Then 200, `sha256(response.content).hexdigest() == P`, `content-type == "application/pdf"`
- **Priority:** High

#### E2E-029: Run produit une barre de progression puis un xlsx téléchargeable
- **Category:** Core Journey
- **Scenario:** SC-004
- **Requirements:** FR-NEW-020, FR-NEW-022, FR-NEW-023, FR-NEW-030, FR-MOD-002, FR-DEL-003, FR-DEL-005
- **Preconditions:** `models_file`, `project_with_source`, `fake_llm_run`.
- **Steps:**
  - When `POST .../runs` avec `{"model": "watsonx-mistral-large"}`, abonnement à
    `GET .../versions/v1/events`, attente de `status == "done"`, puis
    `GET .../versions/v1/xlsx`
  - Then le POST répond 202 et `{"version": "v1"}`
  - And au moins un événement `progress` est reçu, avec `data` JSON portant `version`,
    `percent` entier entre 0 et 100
  - And un événement terminal `done` est reçu
  - And le GET du classeur répond 200 avec
    `content-type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`
  - And `load_workbook(BytesIO(content)).sheetnames[:2] == ["Synthèse", "Traçabilité"]` et la
    cellule `A2` de `Traçabilité` vaut `"F03.EU05.CU01.RM01"`
  - And `projects/{pid}/v1/testplan.xlsx` existe
- **Priority:** Critical

#### E2E-030: sans aucun modèle configuré la génération est refusée en 409
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-029
- **Preconditions:** `no_models`, `project_with_source`.
- **Steps:**
  - When `POST .../runs` avec `{"model": "watsonx-mistral-large"}`
  - Then 409, corps exactement `{"detail": "aucun modèle configuré"}`
  - And `projects/{pid}/v1` n'existe pas
  - And `fake_llm_run.calls == []`
- **Priority:** Critical

#### E2E-031: un endpoint injoignable fait échouer la version avec un message lisible
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-024
- **Preconditions:** entrée de modèle dont `base_url` vaut `http://127.0.0.1:1` ; le transport
  simulé lève `httpx.ConnectError`.
- **Steps:**
  - When `POST .../runs` puis attente de l'état terminal
  - Then le POST répond 202 et la version atteint `status == "failed"`
  - And `projects/{pid}/v1/state.json` a `error == "endpoint injoignable: http://127.0.0.1:1"`
  - And un événement SSE `error` est reçu, portant `"endpoint injoignable"`
  - And `GET .../versions/v1/xlsx` répond 409 `{"detail": "version en échec"}`
- **Priority:** Critical

#### E2E-032: un 401 en milieu de run conserve le travail déjà écrit
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-024, FR-NEW-025
- **Preconditions:** LLM simulé réussissant les 2 premiers appels de scénario, puis levant une
  `httpx.HTTPStatusError` de statut 401.
- **Steps:**
  - When `POST .../runs` puis attente de l'état terminal
  - Then `status == "failed"` et `state.json` a `error == "authentification refusée (401)"`
  - And `state.json` porte 2 scénarios en `status == "done"`, non effacés
  - And `projects/{pid}/v1/testplan.xlsx` n'existe pas
- **Priority:** Critical

#### E2E-033: deux onglets qui lancent le même projet ne créent qu'une version
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-021
- **Preconditions:** LLM simulé bloqué sur un événement.
- **Steps:**
  - When deux `POST .../runs` sur le même `pid` depuis deux clients
  - Then l'un répond 202 `{"version": "v1"}`, l'autre 409 `{"detail": "génération déjà en cours"}`
  - And les dossiers de version du projet sont exactement `["v1"]`
- **Cleanup:** libérer l'événement, attendre la tâche
- **Priority:** Critical

#### E2E-034: télécharger le xlsx d'une version en cours répond 409
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-023
- **Steps:**
  - When `GET .../versions/v1/xlsx` pendant que v1 est `running`
  - Then 409, `{"detail": "génération en cours"}`
- **Priority:** High

#### E2E-035: un document sans aucune exigence produit un xlsx à en-têtes seules
- **Category:** Edge
- **Scenario:** SC-004
- **Requirements:** FR-NEW-023
- **Preconditions:** source `vide_mais_valide.md` de contenu `"# Titre\n\nAucune exigence.\n"` ;
  LLM simulé rendant `{"context": "", "scenarios": [], "discards": []}`.
- **Steps:**
  - When exécution complète puis téléchargement
  - Then 200, la feuille `Traçabilité` a `max_row == 1`, et la cellule `B3` de `Synthèse`, qui
    porte le nombre de tests, vaut 0
- **Priority:** High

#### E2E-036: la fin de run écrit le xlsx et ne touche pas project.json
- **Category:** Side Effect
- **Scenario:** SC-004
- **Requirements:** FR-NEW-002
- **Steps:**
  - Given v1 créée par `POST .../runs`, puis les empreintes sha256 de `project.json` et du
    fichier source relevées **après** la réponse 202, le compteur ayant déjà été incrémenté
  - When l'exécution atteint son état terminal
  - Then les deux empreintes sont inchangées
  - And `json.loads(projects/{pid}/project.json)["next_version"] == 2`
  - And `projects/{pid}/v1/testplan.xlsx` existe
  - And aucun fichier n'a été écrit hors de `projects/{pid}/v1/`
- **Priority:** High

#### E2E-037: lancer un projet inconnu répond 404
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-040
- **Steps:**
  - When `POST /api/v1/projects/cccccccccccc/runs`
  - Then 404, `{"detail": "projet inconnu: cccccccccccc"}`
- **Priority:** Medium

#### E2E-038: soixante scénarios émettent un événement de progression au moins toutes les deux secondes
- **Category:** Performance
- **Scenario:** SC-004
- **Requirements:** FR-NEW-022
- **Preconditions:** LLM simulé avec `await asyncio.sleep(0.05)` par appel, 60 scénarios.
- **Steps:**
  - When exécution, en horodatant chaque événement SSE avec `time.monotonic()`
  - Then l'exécution atteint son état terminal en moins de 30 s
  - And l'écart maximal entre deux événements `progress` consécutifs est inférieur ou égal à 2,0 s
  - And le nombre d'événements `progress` est supérieur ou égal à 60
- **Priority:** Medium

#### E2E-039: un disque plein pendant l'écriture du xlsx ne laisse pas de fichier tronqué
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-041
- **Preconditions:** l'écriture du classeur est remplacée par un appel levant `OSError(ENOSPC)`.
- **Steps:**
  - When exécution complète
  - Then `status == "failed"` et `state.json` a `error == "disque plein, classeur non écrit"`
  - And `projects/{pid}/v1/testplan.xlsx` n'existe pas
  - And aucun fichier `.tmp` ne reste dans le dossier de la version
- **Priority:** High

#### E2E-040: la progression est monotone et finit à cent
- **Category:** Data Integrity
- **Scenario:** SC-004
- **Requirements:** FR-NEW-022
- **Steps:**
  - When une exécution à 10 scénarios, en collectant tous les `percent`
  - Then la suite est croissante au sens large, la dernière valeur est 100, et aucune valeur
    n'est hors de l'intervalle 0 à 100
- **Priority:** High

#### E2E-041: un modèle qui renvoie du JSON illisible trois fois fait échouer la version
- **Category:** Error
- **Scenario:** SC-004
- **Requirements:** FR-NEW-024
- **Preconditions:** le transport HTTP est simulé par `httpx.MockTransport`, et non `chat_json`
  lui-même, dont c'est précisément la boucle de reprise que l'on mesure. Il rend une
  distillation **valide**, puis, pour tout appel de génération de scénario, un statut 200 dont
  `choices[0].message.content` vaut `"pas du json"`. Le document ne porte qu'un seul scénario,
  `SC-001`.
- **Steps:**
  - When exécution
  - Then exactement 3 requêtes HTTP de génération sont reçues pour `SC-001`, et pas 4 : la
    première tentative est comprise dans le compte de FR-NEW-051
  - And le scénario `SC-001` porte `status == "needs_human"`
  - And la version porte `status == "failed"` et `error == "réponse du modèle illisible"`, tous
    les scénarios ayant fini `needs_human`, ce qui est le cas limite de FR-NEW-050
- **Priority:** High

#### E2E-042: trois relances produisent v1, v2, v3
- **Category:** Core Journey
- **Scenario:** SC-005
- **Requirements:** FR-NEW-010, FR-NEW-011, FR-NEW-012, FR-NEW-020, FR-DEL-003
- **Steps:**
  - When trois exécutions complètes successives
  - Then les trois réponses portent `{"version": "v1"}`, `{"version": "v2"}`, `{"version": "v3"}`
  - And les dossiers `v1`, `v2`, `v3` contiennent chacun `state.json`, `prompts/`, `testplan.xlsx`
  - And `GET .../versions` renvoie les identifiants dans l'ordre `["v3", "v2", "v1"]`
- **Priority:** Critical

#### E2E-043: la v2 n'écrase pas les résultats de la v1
- **Category:** Data Integrity
- **Scenario:** SC-005
- **Requirements:** FR-MOD-001
- **Preconditions:** v1 terminée ; LLM simulé rendant pour v2 un nom de test différent,
  `"Création nominale v2"`.
- **Steps:**
  - When exécution de v2
  - Then l'empreinte sha256 de `projects/{pid}/v1/state.json` est identique à celle d'avant
  - And le test `TEST-0001` vaut `"Création nominale"` en v1 et `"Création nominale v2"` en v2
- **Priority:** Critical

#### E2E-044: chaque version garde le modèle et les prompts qu'elle a utilisés
- **Category:** State Transition
- **Scenario:** SC-005
- **Requirements:** FR-NEW-017, FR-NEW-030, FR-NEW-047, FR-MOD-002
- **Preconditions:** v1 exécutée avec `watsonx-mistral-large` ; ajout de `granite-8b` puis
  retrait de `watsonx-mistral-large` de la table.
- **Steps:**
  - When exécution de v2 avec `{"model": "granite-8b"}`
  - Then `v1/state.json` a `model == "watsonx-mistral-large"` et `v2/state.json`
    `model == "granite-8b"`
  - And `v1/prompts/` porte toujours ses trois fichiers `.md`
- **Priority:** Critical

#### E2E-045: un dossier de version supprimé à la main disparaît de la liste
- **Category:** Error
- **Scenario:** SC-005
- **Requirements:** FR-NEW-012
- **Preconditions:** v1, v2, v3 terminées, puis suppression du dossier `v2` sur disque.
- **Steps:**
  - When `GET .../versions` puis `GET .../versions/v2/xlsx`
  - Then la liste vaut `["v3", "v1"]`
  - And le téléchargement répond 404 `{"detail": "version inconnue: v2"}`
  - And les classeurs de `v1` et `v3` répondent toujours 200
- **Priority:** High

#### E2E-046: une version au state.json corrompu est listée comme corrompue
- **Category:** Error
- **Scenario:** SC-005
- **Requirements:** FR-NEW-015, FR-NEW-012, FR-NEW-047
- **Preconditions:** v1 terminée, puis `v1/state.json` remplacé par `b"{ not json"`.
- **Steps:**
  - When `GET .../versions` puis `GET .../versions/v1/xlsx`
  - Then la liste contient `{"id": "v1", "status": "corrompue"}`
  - And le téléchargement répond 409 `{"detail": "version corrompue: v1"}`
  - And `GET /api/v1/projects` répond 200 et liste toujours le projet
- **Priority:** High

#### E2E-047: la dixième version s'appelle v10 et se classe après v9
- **Category:** Edge
- **Scenario:** SC-005
- **Requirements:** FR-NEW-011
- **Preconditions:** neuf exécutions terminées, v1 à v9.
- **Steps:**
  - When une dixième exécution
  - Then 202 `{"version": "v10"}` et le dossier `v10` existe
  - And `GET .../versions` renvoie les identifiants dans l'ordre
    `["v10", "v9", "v8", "v7", "v6", "v5", "v4", "v3", "v2", "v1"]`
- **Priority:** Medium

#### E2E-048: relancer après un échec crée la version suivante
- **Category:** State Transition
- **Scenario:** SC-005
- **Requirements:** FR-NEW-011
- **Preconditions:** v1 en échec selon les conditions de E2E-031, modèles sains ensuite.
- **Steps:**
  - When `POST .../runs`
  - Then 202 `{"version": "v2"}`, v1 reste `failed`, v2 atteint `done`
- **Priority:** High

#### E2E-049: deux générations parallèles sur deux projets aboutissent toutes les deux
- **Category:** Error
- **Scenario:** SC-005
- **Requirements:** FR-NEW-021
- **Steps:**
  - When `POST .../runs` sur `pidA` et `pidB` dans un seul `TaskGroup`
  - Then les deux répondent 202 et atteignent `done`
  - And les deux `testplan.xlsx` existent
  - And l'état de `pidA` ne contient que le titre de la source de `pidA`
- **Priority:** High

#### E2E-050: supprimer la v2 laisse la v1 et la v3 intactes
- **Category:** Core Journey
- **Scenario:** SC-006
- **Requirements:** FR-NEW-013
- **Steps:**
  - When `DELETE /api/v1/projects/{pid}/versions/v2`
  - Then 204 et corps vide
  - And `projects/{pid}/v2` n'existe pas
  - And les empreintes sha256 de `v1/testplan.xlsx` et `v3/testplan.xlsx` sont inchangées
  - And `GET .../versions` renvoie `["v3", "v1"]`
- **Priority:** Critical

#### E2E-051: supprimer la seule version laisse le projet listé avec zéro version
- **Category:** Edge
- **Scenario:** SC-006
- **Requirements:** FR-NEW-013
- **Steps:**
  - When `DELETE .../versions/v1` alors que v1 est la seule
  - Then 204
  - And `GET /api/v1/projects` liste toujours `{pid}`
  - And `GET .../versions` renvoie `{"versions": []}`
  - And `projects/{pid}/source/specification_habilitations.md` existe toujours
- **Priority:** Critical

#### E2E-052: supprimer une version en cours d'exécution répond 409
- **Category:** Error
- **Scenario:** SC-006
- **Requirements:** FR-NEW-014
- **Preconditions:** v1 `running`, LLM bloqué.
- **Steps:**
  - When `DELETE .../versions/v1`
  - Then 409, `{"detail": "version en cours d'exécution"}`
  - And `projects/{pid}/v1/state.json` existe toujours
- **Cleanup:** libérer l'événement, attendre, puis la suppression répond 204
- **Priority:** Critical

#### E2E-053: supprimer une version inconnue répond 404
- **Category:** Error
- **Scenario:** SC-006
- **Requirements:** FR-NEW-013
- **Steps:**
  - When `DELETE .../versions/v7` sur un projet n'ayant que v1
  - Then 404, `{"detail": "version inconnue: v7"}`
- **Priority:** Medium

#### E2E-054: une URL de suppression mal formée est rejetée avant le gestionnaire
- **Category:** Edge
- **Scenario:** SC-006
- **Requirements:** FR-NEW-040
- **Steps:**
  - When `DELETE .../versions/..%2Fsource` puis `DELETE .../versions/..%2F..%2F{autre_pid}`
  - Then 404 dans les deux cas, jamais 204
  - And `projects/{pid}/source/specification_habilitations.md` existe toujours
  - And `projects/{autre_pid}` existe toujours
  - **Même avertissement qu'en E2E-026** : les charges en `%2F` sont absorbées par le routeur,
    donc ce test est vert sans validation et ne prouve rien sur FR-NEW-040. Classé **Edge**.
    L'attaque réelle est en E2E-095.
- **Priority:** Critical

#### E2E-055: une suppression ne renumérote rien et le numéro supprimé n'est pas réutilisé
- **Category:** Side Effect
- **Scenario:** SC-006
- **Requirements:** FR-NEW-011
- **Preconditions:** v1, v2, v3 terminées, puis `DELETE .../versions/v3`.
- **Steps:**
  - When `POST .../runs`
  - Then 202 `{"version": "v4"}`, le compteur `next_version` de `project.json` n'ayant pas été
    décrémenté
  - And les empreintes sha256 des `state.json` de `v1` et `v2` sont inchangées
- **Priority:** High

#### E2E-056: deux suppressions concurrentes donnent un 204 et un 404
- **Category:** Error
- **Scenario:** SC-006
- **Requirements:** FR-NEW-013
- **Steps:**
  - When deux `DELETE .../versions/v2` dans un seul `TaskGroup`
  - Then l'ensemble des statuts est exactement `{204, 404}`
  - And le corps du 404 est `{"detail": "version inconnue: v2"}`
  - And `projects/{pid}/v2` n'existe pas et `v1` est intacte
- **Priority:** High

#### E2E-057: la liste des projets se rafraîchit depuis le disque
- **Category:** Core Journey
- **Scenario:** SC-007
- **Requirements:** FR-NEW-031
- **Preconditions:** trois projets de `created_at` respectifs `2026-10-01T09:00:00Z`,
  `2026-10-01T10:00:00Z`, `2026-10-01T11:00:00Z`.
- **Steps:**
  - When `GET /api/v1/projects`
  - Then 200 et les identifiants viennent du plus récent au plus ancien
  - And chaque entrée porte `source_filename` et `version_count`
- **Priority:** Critical

#### E2E-058: aucun projet répond 200 avec une liste vide
- **Category:** Edge
- **Scenario:** SC-007
- **Requirements:** FR-NEW-031
- **Steps:**
  - When `GET /api/v1/projects` sur un répertoire vide
  - Then 200 et `json() == {"projects": []}`
  - And `GET /` répond 200 et son corps contient `Aucun projet`
- **Priority:** High

#### E2E-059: un dossier sans project.json est ignoré
- **Category:** Error
- **Scenario:** SC-007
- **Requirements:** FR-NEW-031, FR-NEW-032, FR-NEW-033, FR-NEW-046
- **Preconditions:** un projet valide, plus `projects/.DS_Store`, `projects/__pycache__/` sans
  `project.json`, et `projects/brouillon/notes.txt`.
- **Steps:**
  - When `GET /api/v1/projects`
  - Then 200 avec exactement 1 entrée, celle du projet valide
- **Priority:** High

#### E2E-060: un project.json corrompu reste listé avec le statut corrompu
- **Category:** Error
- **Scenario:** SC-007
- **Requirements:** FR-NEW-033
- **Preconditions:** un projet dont `project.json` vaut `b"\x00\x01corrupt"`.
- **Steps:**
  - When `GET /api/v1/projects`
  - Then 200 et non 500, l'entrée valant exactement les trois clés
    `{"id": "<nom du dossier>", "name": "<nom du dossier>", "status": "corrompu"}`, sans
    `source_filename` ni `version_count`, conformément à la forme dégradée de FR-NEW-033
  - And `GET /` répond 200
- **Priority:** High

#### E2E-061: un dossier copié à chaud apparaît au rafraîchissement sans redémarrage
- **Category:** Side Effect
- **Scenario:** SC-007
- **Requirements:** FR-NEW-031
- **Steps:**
  - Given l'application démarrée et `GET /api/v1/projects` renvoyant 0 entrée
  - When un dossier de projet préparé est copié dans le répertoire pendant que l'application
    tourne, puis `GET /api/v1/projects`
  - Then la seconde réponse porte 1 entrée avec l'identifiant copié
  - And `(projects / "index.json").exists() is False`
- **Priority:** Critical

#### E2E-062: cinq cents projets se listent en moins d'une seconde
- **Category:** Performance
- **Scenario:** SC-007
- **Requirements:** FR-NEW-031
- **Steps:**
  - When `GET /api/v1/projects` sur 500 dossiers valides, chronométré
  - Then 200, 500 entrées, durée inférieure à 1,0 s
- **Priority:** Medium

#### E2E-063: un lien symbolique vers l'extérieur n'est pas listé comme projet
- **Category:** Security
- **Scenario:** SC-007
- **Requirements:** FR-NEW-032
- **Preconditions:** `projects/evasion` est un lien symbolique vers `tmp_path/ailleurs`, lequel
  porte un `project.json` valide.
- **Steps:**
  - When `GET /api/v1/projects`
  - Then 200 et aucune entrée n'a `id == "evasion"`
  - And le corps ne contient pas `ailleurs`
- **Priority:** High

#### E2E-064: ajouter un modèle écrit le fichier models.json sur le disque
- **Category:** Core Journey
- **Scenario:** SC-008
- **Requirements:** FR-NEW-026, FR-NEW-027
- **Preconditions:** `TGI_CONFIG_DIR` sur un dossier sans `models.json`.
- **Steps:**
  - When `POST /api/v1/models` avec
    `{"name": "granite-8b", "base_url": "https://eu-de.ml.cloud.ibm.com", "api_key": "sk-test-0001", "model": "ibm/granite-3-8b-instruct"}`
  - Then 201 et le corps porte `api_key == "sk-***0001"`
  - And `models.json` existe, `json.loads(...)["models"][0]["api_key"] == "sk-test-0001"`
  - And le mode du fichier est `0o600`
  - And une exécution lancée ensuite répond 202
- **Priority:** Critical

#### E2E-065: les entrées préconfigurées et l'ajout coexistent dans la liste
- **Category:** Side Effect
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When ajout de `granite-8b` sur un fichier portant déjà `watsonx-mistral-large`, puis
    `GET /api/v1/models`
  - Then 200 et les noms valent `["watsonx-mistral-large", "granite-8b"]` dans cet ordre
  - And le fichier sur disque porte les deux entrées dans le même ordre
- **Priority:** High

#### E2E-066: ajouter deux fois le même nom de modèle répond 409
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When `POST /api/v1/models` avec `name == "watsonx-mistral-large"`, déjà présent
  - Then 409, `{"detail": "modèle déjà défini: watsonx-mistral-large"}`
  - And le fichier porte toujours exactement 1 entrée, `api_key` inchangée
- **Priority:** High

#### E2E-067: un modèle sans base_url est refusé en 422
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When `POST /api/v1/models` avec `{"name": "x", "api_key": "k", "model": "m"}`
  - Then 422 et `json()["detail"][0]["loc"] == ["body", "base_url"]`
  - And l'empreinte sha256 du fichier est inchangée
- **Priority:** High

#### E2E-068: une base_url en ftp est refusée en 422
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When `POST /api/v1/models` avec `base_url == "ftp://host/x"`, puis `"pas une url"`
  - Then 422 dans les deux cas, `{"detail": "base_url invalide: ftp://host/x"}` puis
    `{"detail": "base_url invalide: pas une url"}`
- **Priority:** High

#### E2E-069: la clé d'API n'est jamais renvoyée en clair
- **Category:** Security
- **Scenario:** SC-008
- **Requirements:** FR-NEW-028, FR-NEW-043
- **Preconditions:** une entrée dont `api_key` vaut `sk-test-0001`.
- **Steps:**
  - When `GET /api/v1/models`, `GET /`, `GET /parametres`, et le flux SSE d'une exécution
  - Then aucun corps de réponse ne contient `sk-test-0001`
  - And `GET /api/v1/models` renvoie `api_key == "sk-***0001"`
  - And le fichier de traces OpenTelemetry sous `TGI_LOGS` ne contient aucune occurrence de
    `sk-test-0001`
- **Priority:** Critical

#### E2E-070: retirer le dernier modèle fait repasser la génération en 409
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-029
- **Steps:**
  - When `DELETE /api/v1/models/watsonx-mistral-large` puis `POST .../runs`
  - Then la suppression répond 204 et la liste sur disque vaut `[]`
  - And l'exécution répond 409 `{"detail": "aucun modèle configuré"}`
  - And `GET /` répond toujours 200
- **Priority:** Critical

#### E2E-071: retirer un modèle inconnu répond 404
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When `DELETE /api/v1/models/inexistant`
  - Then 404, `{"detail": "modèle inconnu: inexistant"}`
- **Priority:** Medium

#### E2E-072: un models.json illisible laisse l'interface démarrer et la génération refuser
- **Category:** Error
- **Scenario:** SC-008
- **Requirements:** FR-NEW-029
- **Preconditions:** `models.json` écrit puis passé en mode `0o000`, test ignoré si exécuté en
  root.
- **Steps:**
  - When `GET /`, `GET /api/v1/models`, `POST .../runs`
  - Then `GET /` répond 200
  - And `GET /api/v1/models` répond 200 avec
    `{"models": [], "warning": "fichier de modèles illisible"}`
  - And l'exécution répond 409 `{"detail": "aucun modèle configuré"}`
- **Cleanup:** remettre `0o600` dans un `finally`
- **Priority:** Critical

#### E2E-073: un nom de modèle de 10 000 caractères est refusé en 422
- **Category:** Edge
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When `POST /api/v1/models` avec `name` valant `"é" * 10000`
  - Then 422, `{"detail": "nom de modèle trop long (max 120)"}`
  - And avec `name` valant `"é" * 120`, 201, et le nom revient inchangé par
    `GET /api/v1/models`
- **Priority:** Medium

#### E2E-074: deux ajouts concurrents se retrouvent tous les deux dans le fichier
- **Category:** Data Integrity
- **Scenario:** SC-008
- **Requirements:** FR-NEW-027
- **Steps:**
  - When deux `POST /api/v1/models`, `granite-8b` et `llama-3-70b`, dans un seul `TaskGroup`
  - Then les deux répondent 201
  - And le fichier porte exactement 3 entrées, de noms
    `{"watsonx-mistral-large", "granite-8b", "llama-3-70b"}`
- **Priority:** High

#### E2E-075: l'export QC produit une feuille QC aux six colonnes attendues
- **Category:** Core Journey
- **Scenario:** SC-009
- **Requirements:** FR-NEW-034, FR-NEW-035
- **Preconditions:** v1 terminée portant le scénario `SC021`, conteneur `F03.EU05.CU01` titré
  `Déléguer temporairement`, test `TEST-0042` nommé `Délégation nominale`, description
  `Le délégataire reçoit le portefeuille`, références
  `["F03.EU05.CU01.RM01", "F03.EU05.CU01.RM02"]`, 2 étapes.
- **Steps:**
  - When `POST .../versions/v1/qc` puis `GET .../versions/v1/qc.xlsx`
  - Then le POST répond 201 avec `{"path": "v1/qc.xlsx", "warnings": []}`
  - And `projects/{pid}/v1/qc.xlsx` existe et le GET répond 200
  - And `sheetnames == ["QC"]` et la ligne 1 vaut exactement
    `["Subject", "Test Name", "Description", "Step Name", "Step Description", "Expected Results"]`
  - And `A2 == "F03.EU05.CU01-RM_Déléguer temporairement_SC021"`
  - And `B2 == "TRA_TEST-0042_Délégation nominale__F03.EU05.CU01.RM01,F03.EU05.CU01.RM02"`
  - And `C2` commence par `"Le délégataire reçoit le portefeuille"` et finit par
    `"\nExigences validées : F03.EU05.CU01.RM01, F03.EU05.CU01.RM02"`
  - And `D2 == "Étape 1"` et `D3 == "Étape 2"`
- **Priority:** Critical

#### E2E-076: l'export QC ne modifie pas le xlsx de recette
- **Category:** Side Effect
- **Scenario:** SC-009
- **Requirements:** FR-NEW-034
- **Steps:**
  - Given l'empreinte sha256 de `v1/testplan.xlsx`
  - When `POST .../versions/v1/qc`
  - Then 201 et l'empreinte de `testplan.xlsx` est inchangée
  - And l'empreinte de `v1/state.json` est inchangée
- **Priority:** High

#### E2E-077: exporter en QC une version en cours répond 409
- **Category:** Error
- **Scenario:** SC-009
- **Requirements:** FR-NEW-039
- **Steps:**
  - When `POST .../versions/v1/qc` pendant que v1 est `running`
  - Then 409, `{"detail": "génération en cours"}`
  - And `v1/qc.xlsx` n'existe pas
- **Priority:** High

#### E2E-078: exporter en QC une version sans aucun test répond 409
- **Category:** Error
- **Scenario:** SC-009
- **Requirements:** FR-NEW-039
- **Steps:**
  - When `POST .../versions/v1/qc` sur une version `done` dont `scenarios == []`
  - Then 409, `{"detail": "aucun test à exporter"}`
  - And `v1/qc.xlsx` n'existe pas
- **Priority:** High

#### E2E-079: le TYPE du Subject suit le préfixe de l'exigence
- **Category:** Edge
- **Scenario:** SC-009
- **Requirements:** FR-NEW-036
- **Preconditions:** cinq tests du conteneur `F03.EU05.CU01` dont les premières références sont
  respectivement `...RM01`, `...EM02`, `...M03`, `...N04`, `...T05`.
- **Steps:**
  - When construction de l'export puis lecture de la colonne A
  - Then les cinq `Subject` commencent respectivement par `F03.EU05.CU01-RM_`,
    `F03.EU05.CU01-EMOE_`, `F03.EU05.CU01-IHM_`, `F03.EU05.CU01-IHM_`, `F03.EU05.CU01-IHM_`
  - And pour un test de références `["F03.EU05.CU01.M03", "F03.EU05.CU01.RM01"]`, le type est
    celui de la **première**, donc `-IHM_`
- **Priority:** Critical

#### E2E-080: un préfixe d'exigence inconnu produit INCONNU et un avertissement
- **Category:** Error
- **Scenario:** SC-009
- **Requirements:** FR-NEW-037
- **Preconditions:** un test dont l'unique référence est `F03.EU05.CU01.ZZ01`.
- **Steps:**
  - When `POST .../versions/v1/qc`
  - Then 201 et `json()["warnings"]` contient exactement
    `"préfixe d'exigence inconnu: ZZ (F03.EU05.CU01.ZZ01)"`
  - And `v1/qc.xlsx` existe et sa cellule `A2` commence par `F03.EU05.CU01-INCONNU_`
- **Priority:** High

#### E2E-081: une ligne par étape, Subject et Test Name répétés
- **Category:** Data Integrity
- **Scenario:** SC-009
- **Requirements:** FR-NEW-035
- **Preconditions:** deux tests, de 3 et 2 étapes.
- **Steps:**
  - When construction de l'export puis lecture de toutes les lignes
  - Then `max_row == 6`, soit 1 en-tête et 5 étapes
  - And les lignes 2 à 4 répètent les mêmes valeurs en colonnes A et B, les lignes 5 et 6 celles
    du second test
  - And la colonne `Step Name` vaut
    `["Étape 1", "Étape 2", "Étape 3", "Étape 1", "Étape 2"]`
  - And aucune cellule `Expected Results` n'est vide
- **Priority:** Critical

#### E2E-082: une description de 40 000 caractères est tronquée à la limite Excel
- **Category:** Edge
- **Scenario:** SC-009
- **Requirements:** FR-NEW-038
- **Preconditions:** un test dont la description vaut `"é" * 40000`.
- **Steps:**
  - When construction de l'export
  - Then 201, `len(sheet["C2"].value) == 32767`, la valeur finit par `…`
  - And `load_workbook` ouvre le fichier sans erreur
- **Priority:** Medium

#### E2E-083: un projet zippé, l'original supprimé, dézippé ailleurs, se liste et fonctionne
- **Category:** Data Integrity
- **Scenario:** NFR2
- **Requirements:** FR-NEW-002
- **Driver:** file system + HTTP client
- **Preconditions:** un projet avec sa source, `v1` et `v2` terminées, et
  `POST .../versions/v2/qc` ayant répondu 201, donc `qc.xlsx` présent dans `v2` et absent de
  `v1`.
- **Steps:**
  - Given `shutil.make_archive` du dossier du projet
  - When le dossier d'origine est supprimé, `GET /api/v1/projects` renvoie
    `{"projects": []}`, puis l'archive est dépliée dans un répertoire neuf servi par une
    **nouvelle** instance `create_app()`
  - Then `GET /api/v1/projects` sur la nouvelle instance renvoie 1 entrée d'identifiant `pid`
    et de `version_count` 2
  - And `GET .../source` renvoie les octets d'origine, empreinte sha256 égale
  - And `GET .../versions/v1/xlsx` répond 200 et le classeur s'ouvre, ses deux premières
    feuilles valant `["Synthèse", "Traçabilité"]`
  - And `GET .../versions/v2/qc.xlsx` répond 200
  - And `POST .../runs` répond 202 `{"version": "v3"}`, donc le projet est exécutable et pas
    seulement consultable
- **Priority:** Critical

#### E2E-084: un projet dézippé sans state.json ne casse pas la liste
- **Category:** Error
- **Scenario:** NFR2
- **Requirements:** FR-NEW-031, FR-NEW-015, FR-NEW-046, FR-NEW-033, FR-DEL-002
- **Steps:**
  - Given un projet déplié dont `project.json` a été retiré, et un second dont `v1/state.json`
    vaut `b"{"`
  - When `GET /api/v1/projects` puis `GET /`
  - Then le dossier sans `project.json` est absent de la liste, `GET /` répond 200, aucun 500
  - And le projet au `v1/state.json` corrompu est listé, sa version `v1` portant
    `status == "corrompue"`
  - And `POST .../runs` sur ce projet répond 202 `{"version": "v2"}`
- **Priority:** Critical

#### E2E-085: l'arbre projects ne contient que du json, du md et du xlsx
- **Category:** Data Integrity
- **Scenario:** NFR1
- **Requirements:** FR-NEW-045
- **Driver:** file system
- **Preconditions:** deux projets, deux versions chacun, export QC construit.
- **Steps:**
  - When collecte de `{p.suffix for p in projects.rglob("*") if p.is_file()}`
  - Then l'ensemble est inclus dans `{".json", ".md", ".xlsx", ".docx", ".pdf"}`, les deux
    derniers n'apparaissant que sous `source/`
  - And `list(projects.rglob("*.db"))`, `*.sqlite`, `*.sqlite3` et `list(projects.rglob(".git"))`
    sont tous vides
  - And ni `projects/index.json`, ni `projects/registry.json`, ni `projects/_uploads` n'existent
- **Priority:** Critical

#### E2E-086: l'interface démarre sans aucun modèle configuré
- **Category:** Edge
- **Scenario:** NFR4
- **Requirements:** FR-NEW-029, FR-NEW-042, FR-NEW-007
- **Preconditions:** `TGI_CONFIG_DIR` vide, aucun `models.json`, `TGI_LLM_API_KEY` non défini,
  de sorte que le défaut `"changeme"` de `src/tgi/config.py:15` ne compte plus comme configuré.
- **Steps:**
  - When construction de l'application, `GET /`, `GET /api/v1/models`,
    `POST /api/v1/projects`, `POST .../runs`
  - Then `GET /` répond 200 et son corps contient `aucun modèle configuré`
  - And `GET /api/v1/models` répond 200 `{"models": []}`
  - And le dépôt répond 201, car déposer ne demande pas de modèle
  - And l'exécution répond 409 `{"detail": "aucun modèle configuré"}`
  - And après `POST /api/v1/models` d'une entrée valide, la même exécution répond 202
- **Priority:** Critical

#### E2E-087: le fichier de modèles est créé par l'outil quand il est absent
- **Category:** Side Effect
- **Scenario:** NFR3
- **Requirements:** FR-NEW-026
- **Preconditions:** `TGI_CONFIG_DIR` désignant un dossier qui n'existe pas.
- **Steps:**
  - When `POST /api/v1/models` d'une entrée valide
  - Then 201, le dossier existe désormais, et `models.json` s'analyse en
    `{"models": [{...}]}`
  - And une seconde instance d'application sur le même `TGI_CONFIG_DIR` renvoie ce modèle par
    `GET /api/v1/models`
- **Priority:** Critical

#### E2E-088: aucun dépôt git n'est créé et les anciennes routes ont disparu
- **Category:** State Transition
- **Scenario:** NFR1
- **Requirements:** FR-DEL-002, FR-DEL-003, FR-DEL-004, FR-DEL-005
- **Steps:**
  - Given un projet créé et une exécution terminée
  - When `GET /projects/{pid}/history`, `POST /projects/{pid}/rollback`,
    `POST /projects/{pid}/validate-map` et `GET /projects/{pid}/export`, aux chemins exacts
    qu'ils occupaient avant cet incrément
  - Then les quatre répondent 404
  - And `(projects / pid / ".git").exists() is False` et `list(projects.rglob(".git")) == []`
- **Priority:** High

#### E2E-089: un lien profond vers une version supprimée répond 404 sans casser la navigation
- **Category:** Error
- **Scenario:** SC-005
- **Requirements:** FR-NEW-044, FR-NEW-042, FR-DEL-004
- **Preconditions:** v1 et v2 terminées, puis `DELETE .../versions/v2`.
- **Steps:**
  - When `GET /?project={pid}&version=v2`
  - Then 404 et le corps HTML contient `version inconnue: v2`
  - And `GET /` répond 200 et son corps contient `{pid}`
- **Priority:** Medium

#### E2E-090: télécharger la source ne modifie rien dans le dossier du projet
- **Category:** Side Effect
- **Scenario:** SC-003
- **Requirements:** FR-NEW-008
- **Steps:**
  - Given un relevé `{chemin: (taille, mtime_ns)}` de tous les fichiers du projet
  - When `GET .../source` trois fois
  - Then le relevé pris ensuite est égal à celui pris avant
- **Priority:** Medium

#### E2E-091: une nouvelle version ne touche ni la source ni project.json
- **Category:** Side Effect
- **Scenario:** SC-005
- **Requirements:** FR-NEW-002
- **Steps:**
  - Given v1 terminée, empreintes sha256 de `project.json` et du fichier source relevées
  - When exécution de v2
  - Then l'empreinte de la source est inchangée
  - And `project.json` ne diffère que par `next_version`, passé de 2 à 3
  - And le premier niveau de `projects/{pid}` vaut exactement
    `{"project.json", "source", "v1", "v2"}`
- **Priority:** High

#### E2E-092: le prompt édité est bien celui que le modèle reçoit
- **Category:** Side Effect
- **Scenario:** SC-001
- **Requirements:** FR-NEW-048, FR-NEW-017, FR-NEW-049
- **Driver:** HTTP client + double de LLM
- **Preconditions:** `models_file`, `project_with_source`, et un `fake_llm_run` qui enregistre
  pour chaque appel la valeur de `messages[0]["content"]` dans `.system_prompts`.
- **Steps:**
  - When `POST .../runs` avec `{"model": "watsonx-mistral-large", "prompts": {"scenario_generator": "PROMPT-EDITE-7f3a"}}`
  - Then 202, puis l'exécution atteint `done`
  - And tout appel de génération de scénario a un message système égal exactement à
    `"PROMPT-EDITE-7f3a"`
  - And tout appel de distillation a un message système égal au contenu livré de
    `src/tgi/prompts/distiller.md`, non édité
  - And **ce test échoue sur une implémentation qui se contente d'écrire les fichiers de
    prompts** : c'est sa seule raison d'exister, E2E-001 et E2E-008 n'observant que le disque
- **Priority:** Critical

#### E2E-093: une exécution orpheline est libérée au démarrage
- **Category:** Error
- **Scenario:** SC-005
- **Requirements:** FR-NEW-053, FR-NEW-021, FR-NEW-014
- **Driver:** file system + HTTP client
- **Preconditions:** un projet dont `v1/state.json` est écrit à la main avec
  `status` valant `"running"`, simulant un arrêt brutal.
- **Steps:**
  - When une nouvelle instance `create_app()` démarre sur ce répertoire
  - Then `GET .../versions` porte `{"id": "v1", "status": "failed"}` et
    `v1/state.json` a `error == "exécution interrompue par un redémarrage"`
  - And `POST .../runs` répond 202 `{"version": "v2"}`, donc le projet n'est plus bloqué
  - And `DELETE .../versions/v1` répond 204
- **Priority:** Critical

#### E2E-094: un identifiant de projet `%2E%2E` ne lit rien hors du répertoire
- **Category:** Security
- **Scenario:** SC-003
- **Requirements:** FR-NEW-040
- **Driver:** HTTP client + file system
- **Preconditions:** `projects/{pid}` avec sa v1 et sa source. Et surtout, un **leurre complet**
  hors du répertoire des projets, de sorte que `projects/..` soit un projet valide à tous
  égards sauf son identifiant : `tmp_path/project.json` valant
  `{"id": "..", "name": "PARENT-LEAK", "source_filename": "leak.md", "next_version": 1}` et
  `tmp_path/source/leak.md` valant `b"ROOT-LEAK"`.
  **Cette complétude est la condition pour que le test attaque.** Un leurre réduit au seul
  fichier source laisserait le gestionnaire échouer à lire `project.json` et rendre 404 de
  lui-même, donc le test serait vert sans aucune validation.
- **Steps:**
  - When `GET /api/v1/projects/%2E%2E/source`, charge littérale qui se décode en `..` et atteint
    bien le gestionnaire, contrairement à `..%2F..%2F` que Starlette décode avant le routage
  - Then 404 `{"detail": "projet inconnu: .."}`
  - And le corps de la réponse ne contient ni `ROOT-LEAK` ni `PARENT-LEAK`, et l'en-tête
    `content-disposition` est absent
  - And, relu par le système de fichiers, l'empreinte sha256 de `tmp_path/project.json` est
    inchangée
- **Red before the fix because:** sans la validation de FR-NEW-040, `..` se concatène en
  `projects/..`, `project.json` s'y lit, `source_filename` résout vers `source/leak.md` et la
  réponse rend 200 avec `ROOT-LEAK` : l'assertion de statut et celle sur le corps tombent
  toutes deux.
- **Priority:** Critical

#### E2E-095: un identifiant de version `%2E%2E` ne supprime rien
- **Category:** Security
- **Scenario:** SC-006
- **Requirements:** FR-NEW-040, FR-NEW-013
- **Driver:** HTTP client + file system
- **Preconditions:** `projects/{pid}` avec `project.json`, `source/` et `v1`. Et un **leurre
  complet** à `projects/state.json` valant `{"id": "..", "status": "done"}`, de sorte que
  `projects/{pid}/..`, c'est-à-dire `projects/` lui-même, se lise comme une version terminée.
  Sans ce leurre, FR-NEW-014 oblige à lire le statut avant de supprimer, la lecture échoue et
  le 404 tombe tout seul : le test serait vert sans validation. Empreintes sha256 de tous les
  fichiers sous `projects/` relevées.
- **Steps:**
  - When `DELETE /api/v1/projects/{pid}/versions/%2E%2E`
  - Then 404 `{"detail": "version inconnue: .."}`, jamais 204
  - And, **relu par le système de fichiers et non par l'API**, `projects/` existe toujours,
    ainsi que `projects/{pid}/project.json`, `projects/{pid}/source/` et `projects/{pid}/v1/`,
    toutes empreintes inchangées
- **Red before the fix because:** sans FR-NEW-040, `..` résout vers `projects/`, le leurre s'y
  lit comme `done`, FR-NEW-060 autorise donc la suppression, et le `rmtree` de FR-NEW-013
  efface **le répertoire des projets en entier**, y compris le projet d'origine.
- **Priority:** Critical

#### E2E-096: les paramètres de requête de la page d'accueil sont validés comme le chemin
- **Category:** Security
- **Scenario:** SC-007
- **Requirements:** FR-NEW-040, FR-NEW-042, FR-NEW-044
- **Driver:** HTTP client + file system
- **Preconditions:** un projet valide `{pid}`, et **deux leurres complets**, pour la même raison
  qu'en E2E-094 et E2E-095 : `tmp_path/project.json` valant
  `{"id": "..", "name": "PARENT-LEAK", "source_filename": "x.md"}` et `projects/state.json`
  valant `{"id": "..", "status": "done", "model": "VERSION-LEAK"}`. Relevé
  `{p for p in tmp_path.rglob("*")}` pris avant.
- **Steps:**
  - When `GET /?project=..`, puis `GET /?project={pid}&version=..`
  - Then 404 dans les deux cas, le corps HTML portant `projet inconnu: ..` puis
    `version inconnue: ..`
  - And aucun des deux corps ne contient `PARENT-LEAK` ni `VERSION-LEAK`
  - And, relu par le système de fichiers, le relevé pris ensuite égale celui pris avant
- **Red before the fix because:** les deux paramètres sont une source que la section 2.4 ne
  couvrait pas et qu'aucun test n'atteignait ; sans l'extension de FR-NEW-040 aux paramètres de
  requête, `project=..` résout vers `tmp_path`, le leurre s'y lit, et la page rend 200 en
  affichant `PARENT-LEAK`.
- **Priority:** Critical

#### E2E-097: un identifiant de test venu du modèle n'écrit nulle part
- **Category:** Security
- **Scenario:** SC-004
- **Requirements:** FR-NEW-056, FR-NEW-045
- **Driver:** HTTP client + file system
- **Preconditions:** `fake_llm_run` rendant un test dont le champ `id` vaut littéralement
  `"../../evil"`.
- **Steps:**
  - When une exécution complète
  - Then 202 puis `done`
  - And, relu par le système de fichiers, `list(tmp_path.rglob("evil*")) == []`
  - And `list(projects.rglob("tests")) == []` : aucun dossier `tests/` n'est créé
  - And le test figure bien dans `v1/state.json` avec son identifiant tel quel
  - And, assertion structurelle, `rg -n 'add_or_update_tests|def tests_dir' src/tgi` ne rend
    rien, et `StateManager` ne porte ni l'attribut `add_or_update_tests` ni `tests_dir`
- **Red before the fix because:** la dernière assertion, structurelle, est rouge aujourd'hui :
  `src/tgi/services/state_manager.py:170` définit `add_or_update_tests` et `:73` définit
  `tests_dir`. Les assertions de système de fichiers, elles, sont **un garde contre la
  régression et non une attaque** : le puits de `state_manager.py:188` n'a aujourd'hui aucun
  appelant (DRIFT-007), donc il n'écrit rien tant que personne ne le rebranche. Cette
  distinction est dite plutôt que masquée : un « rouge avant le correctif » qui serait faux
  vaudrait moins que pas de test du tout.
- **Priority:** Critical

#### E2E-098: les statistiques comptent les versions du nouveau format
- **Category:** Error
- **Scenario:** NFR1 disque seul
- **Requirements:** FR-NEW-057, FR-NEW-010
- **Driver:** direct call
- **Preconditions:** un projet créé par l'API, avec `v1` et `v2` terminées.
- **Steps:**
  - When `tgi-stats --projects-dir <tmp_path/projects>`
  - Then la sortie rapporte 2 exécutions pour 1 projet
  - And elle ne rapporte pas 0, ce que produirait le balayage `*/state.json` de
    `src/tgi/stats.py:152` sur la nouvelle disposition
- **Priority:** High

#### E2E-099: les opérations ouvrent leurs spans et n'y mettent aucun secret
- **Category:** Side Effect
- **Scenario:** SC-004
- **Requirements:** FR-NEW-058, FR-NEW-028
- **Driver:** HTTP client + file system
- **Preconditions:** `TGI_LOGS` sous `tmp_path`, une entrée de modèle d'`api_key`
  `sk-test-0001`.
- **Steps:**
  - When un dépôt puis une exécution complète
  - Then le fichier OTel JSONL sous `TGI_LOGS` contient exactement un span nommé
    `project.create` et un span nommé `version.run`
  - And le span `version.run` porte les attributs `project_id` et `version`
  - And le fichier ne contient aucune occurrence de `sk-test-0001`
- **Priority:** Medium

### 12.3 Modified Test Specifications

Le parc existant de 304 tests se partage en trois, et les trois chiffres doivent être lus
ensemble pour qu'aucun test ne soit compté deux fois :

| Sort | Tests | Détail |
|---|---|---|
| Réécrits ou supprimés | **62** | `functional/test_api.py` 36, `test_state_manager.py` 16, `test_state_races.py` 3, `test_git_service.py` 7 |
| Étendus ou adaptés, assertions existantes conservées | **69** | `test_llm.py` 42, `test_config.py` 17, `test_progress.py` 10 |
| Inchangés | **173** | tout le reste, dont `test_workbook.py` 6, `test_coverage_report.py` 9, `test_grammar.py` 23 |

62 + 69 + 173 = 304, le total collecté par pytest. Les 69 tests étendus gagnent des cas sans
qu'aucune de leurs assertions actuelles change de sens : c'est une addition, pas une réécriture.
Les 173 inchangés portent sur des modules que cet incrément ne touche pas et doivent passer
**tels quels** ; c'est la seule non-régression que cet incrément peut invoquer, et elle est
réelle.

### 12.4 Removed Tests

#### E2E-DEL-001: les 7 tests de `tests/test_git_service.py`
- **Reason:** `src/tgi/services/git_service.py` est supprimé par FR-DEL-002. Aucun comportement
  qu'ils couvrent ne survit, donc aucun n'est à reporter ailleurs. L'historique qu'ils
  protégeaient est remplacé par les versions, couvertes par E2E-042 à E2E-056.

## 13. Consistency Notes

Une seule incohérence a été trouvée avec la documentation en vigueur, et elle est frontale.

`AGENTS.md`, section « Pipeline essentials », et `.agent_docs/pipeline.md` posent :

> Un humain valide cette carte avant que quoi que ce soit de coûteux ne tourne.

FR-DEL-003 supprime cette porte. La décision est DEC-002, prise par l'utilisatrice sur la base
de la note du 18 septembre, où la simplification du parcours est l'objet d'un consensus
explicite. Le risque assumé est qu'une distillation fautive consomme un appel de modèle par
scénario avant d'être vue, soit l'ordre de grandeur de 83 appels sur la SFD de référence.
L'atténuation retenue n'est pas une porte mais la possibilité de supprimer la version et de
relancer, qui n'existait pas auparavant et qui est précisément ce que SC-005 et SC-006
apportent. `AGENTS.md` et `.agent_docs/pipeline.md` sont mis à jour par la section 10 ; aucune
spécification existante n'est modifiée, puisqu'il n'en existait aucune.

## 14. Migration & Implementation Notes

Ordre d'exécution imposé, chaque étape laissant la suite verte :

1. `model_store.py` et FR-MOD-002, car FR-NEW-029 et FR-NEW-030 en dépendent et rien d'autre
   n'en dépend.
2. La nouvelle disposition disque : `project.json`, `source/`, FR-NEW-040. À faire **avant**
   les versions, qui s'y greffent.
3. Les versions : FR-NEW-010 à FR-NEW-015 et FR-MOD-001.
4. Les routes et le pipeline par version : FR-NEW-020 à FR-NEW-025.
5. Les suppressions : FR-DEL-001 à FR-DEL-005. Les faire ici et non plus tôt, car l'étape 4
   réutilise le code d'exécution que l'étape 5 nettoie.
6. `qc_export.py` : FR-NEW-034 à FR-NEW-039.
7. Les gabarits : FR-NEW-042 et FR-NEW-043.

Les exigences nées de l'audit s'insèrent dans cet ordre et non à la fin : FR-NEW-048, FR-NEW-049,
FR-NEW-050, FR-NEW-051, FR-NEW-052 et FR-NEW-062 appartiennent à l'étape 4, dont elles définissent
le cœur ; FR-NEW-053 et FR-NEW-061 à l'étape 3 ; FR-NEW-054 et FR-NEW-055 à l'étape 1 ;
FR-NEW-056 à l'étape 2, puisqu'elle supprime un puits de l'ancienne persistance ; FR-NEW-059 et
FR-NEW-060 à l'étape 2 également ; FR-NEW-057 et FR-NEW-058 après l'étape 5, une fois la
disposition disque stabilisée.

Faire l'étape 3 avant l'étape 2 casse la construction, le chemin d'une version étant dérivé du
dossier de projet. Faire l'étape 5 avant l'étape 4 laisse la suite rouge entre les deux.

Pas de bascule par drapeau, pas de migration de données : FR-NEW-046 **ignore** les projets
anciens, sans conversion ni marquage, un dossier sans `project.json` n'étant pas un projet au
sens de FR-NEW-031. Retour arrière par retour au commit précédent ; aucune donnée de production
n'est en jeu, un seul projet existant étant concerné.

## 15. Open Questions & TBDs

- Le format QC exact attendu par Euro-Information reste inconnu. La recherche a établi que EI
  accède à ALM par le lanceur client et le portail QCHP, jamais par le greffon Excel, et que la
  documentation du greffon public interdit l'import de la couverture d'exigences, ce qui est
  précisément pourquoi les références sont concaténées dans `Test Name`. Les séparateurs de
  FR-NEW-035 et la convention de `Subject` sont donc **nos inventions**, assumées par DEC-001,
  et à revoir quand Véronique Bertail fournira un fichier d'import réel ou le gabarit de
  l'équipe Q710. Elles sont isolées dans `qc_export.py` pour que la révision soit locale.
- Le libellé exact des trois prompts dans l'interface n'est pas arrêté. Sans incidence sur le
  contrat.

## 16. Glossary

| Term | Definition | Context (if multiple) |
|---|---|---|
| SFD | Spécification fonctionnelle détaillée, le document d'entrée | |
| Recette | Phase de qualification fonctionnelle chez EI, menée par l'équipe TRA | |
| Recette transverse | Qualification couvrant les développements de plusieurs qualifications antérieures et leurs interactions | |
| QC | Quality Center, aujourd'hui ALM, l'outil de gestion de tests d'Euro-Information | |
| ALM | Application Lifecycle Management, le nom actuel de QC | |
| Q710 | Équipe EI qui administre QC et en distribue les gabarits | |
| MOA, MOE | Maîtrise d'ouvrage et maîtrise d'œuvre, les deux équipes qui relisent le cahier | |
| Cas d'utilisation | Un conteneur d'exigences dans la numérotation du document, par exemple `F03.EU05.CU01` | |
| Exigence | Une règle numérotée du document, feuille de la numérotation, par exemple `F03.EU05.CU01.RM01` | |
| RM | Règle métier, préfixe de feuille sur l'axe `F` | |
| EM, EMOE | Exigence de mise en œuvre, préfixe `EM`, rendu `EMOE` dans l'export QC | |
| IHM | Interface homme machine, les exigences de l'axe `E`, préfixes `M`, `N`, `T` | |
| Axe | Famille de numérotation inférée du document, ici `F` et `E` | Dans « axe version », sections 2.3 et 9.1, le mot désigne au contraire la dimension ajoutée à la persistance, pas une famille de numérotation |
| Version | Une exécution numérotée du pipeline sur un projet, `v1`, `v2` | jamais une version du logiciel, qui se dit build |
| Projet | Un document déposé et les versions produites à partir de lui | |
| Distillation | Première phase du pipeline, qui lit le document entier en un appel | |

## 17. Decisions Log

- **DEC-001:** Le format de l'export QC est défini par nous, à partir du classeur existant et
  des exemples de la planche V8, sans attendre le gabarit d'Euro-Information. **Rationale:** le
  gabarit de l'équipe Q710 n'est pas obtenable dans ce cycle et l'export est sur le chemin
  critique de la recette transverse de mi-octobre. **Alternatives considérées:** bloquer
  jusqu'à réception d'un fichier QC réel, rejeté comme trop lent. **Implemented by:**
  FR-NEW-035, FR-NEW-036. **Round:** 3a. **Code evidence:** `src/tgi/workbook.py:37-50`, la
  liste `_TEST_COLUMNS` des colonnes existantes.
- **DEC-002:** La porte de validation humaine de la carte est supprimée. **Rationale:**
  l'utilisatrice la traverse sans la lire et elle impose une visite d'onglet entre le dépôt et
  le lancement. La possibilité de supprimer une version et de relancer remplace la protection.
  **Alternatives considérées:** la garder en un clic sur la page principale, et la rendre
  conditionnelle au nombre d'orphelins détectés, toutes deux écartées par l'utilisatrice.
  **Implemented by:** FR-DEL-003. **Round:** 3a. **Code evidence:** `src/tgi/tgi.py:353` et
  `src/tgi/tgi.py:375`.
- **DEC-003:** Les sept onglets disparaissent, l'édition unitaire d'un test dans l'interface
  comprise. **Rationale:** la relecture se fait dans Excel, que l'utilisatrice retouche déjà à
  la main. **Alternatives considérées:** garder SCÉNARIOS et EXIGENCES en lecture seule,
  écartée pour ne pas conserver 5 routes au service d'un usage non constaté.
  **Implemented by:** FR-DEL-004. **Round:** 3a. **Code evidence:** `src/tgi/tgi.py:514-690`.
- **DEC-004:** Le versionnement git par projet est supprimé au profit de dossiers `v1`, `v2`.
  **Rationale:** deux mécanismes d'historique pour un seul besoin divergent, et un dossier
  `.git` empêche un projet d'être un dossier simplement zippable. Une empreinte de commit n'est
  pas un nom qu'une testeuse peut citer dans un compte rendu de recette.
  **Alternatives considérées:** garder git et poser des étiquettes `v1`, `v2`, écartée parce
  que supprimer une version deviendrait une réécriture d'historique.
  **Implemented by:** FR-DEL-002. **Round:** 3b. **Code evidence:**
  `src/tgi/services/git_service.py:36`, `:55-80`, `:131-141`.
- **DEC-005:** Les versions sont des dossiers, approche 1, et non un tableau dans un
  `state.json` unique. **Rationale:** NFR2 est satisfait par construction, la suppression d'une
  version est la suppression d'un dossier, et une version effacée depuis l'explorateur de
  fichiers reste un cas gérable. **Alternatives considérées:** tableau dans un fichier unique,
  écartée parce qu'une écriture interrompue perdrait toutes les versions d'un coup.
  **Implemented by:** FR-NEW-010. **Round:** 2. **Code evidence:**
  `src/tgi/services/state_manager.py:87-98` pour l'écriture atomique existante.
- **DEC-006:** La numérotation des versions est un compteur monotone, jamais réutilisé.
  **Rationale:** deux artefacts différents sous le nom `v3` rendraient faux un audit de
  recette. **Alternatives considérées:** `max(existantes) + 1`, qui réutilise le numéro après
  suppression. **Implemented by:** FR-NEW-011. **Round:** 4.
- **DEC-007:** Un préfixe d'exigence inconnu ne fait pas échouer l'export QC ; il produit
  `TYPE = INCONNU` et un avertissement. **Rationale:** faire échouer tout l'export sur un
  préfixe inattendu bloquerait une qualification en cours, ce qui est l'inverse du besoin.
  **Alternatives considérées:** 422 et export tout ou rien, écartée. **Implemented by:**
  FR-NEW-037. **Round:** 4.
- **DEC-008:** Les trois prompts du pipeline sont éditables, et non un seul.
  **Rationale:** la note du 18 septembre annonce que la recette transverse demandera « des
  adaptations de prompt spécifiques », et la phase concernée est la génération de scénarios.
  **Alternatives considérées:** une seule zone de saisie, écartée. **Implemented by:**
  FR-NEW-016. **Round:** 4. **Code evidence:** `src/tgi/prompts/`.
- **DEC-009:** Les projets au format antérieur ne sont ni convertis ni listés, simplement
  ignorés. **Rationale:** un seul projet existe, sur le poste de développement, et aucune
  donnée de production n'est en jeu ; écrire un convertisseur coûterait plus que le recréer.
  Les signaler par un statut dédié contredirait FR-NEW-031, pour lequel un dossier sans
  `project.json` n'est pas un projet. **Alternatives considérées:** migration automatique au
  démarrage, et affichage sous un statut `ancien_format`, toutes deux écartées.
  **Implemented by:** FR-NEW-046. **Round:** 4.
- **DEC-010:** L'identifiant de dossier d'un projet reste opaque, 12 hexadécimaux, le nom
  lisible vivant dans `project.json`. **Rationale:** deux SFD de même nom ne doivent jamais
  entrer en collision, ce qui est exactement le défaut relevé sur `projects/_uploads`.
  **Alternatives considérées:** un dossier nommé d'après le fichier, écartée.
  **Implemented by:** FR-NEW-001. **Round:** 4. **Code evidence:** `src/tgi/tgi.py:276-282`.
- **DEC-011:** Les tests de cette spécification ont été conçus par un agent indépendant, à
  contexte neuf, et non par l'auteur des exigences. **Rationale:** règle de la phase 4.0 à
  profondeur L. **Implemented by:** n/a — aucun impact code. **Round:** 4.
- **DEC-012:** Une erreur de connexion ou un 401 fait échouer la version entière ; une réponse
  illisible sur un scénario isolé marque ce scénario `needs_human` et laisse l'exécution
  continuer. **Rationale:** sur 83 appels, perdre 40 minutes de travail pour une réponse mal
  formée est exactement la plainte que FR-NEW-025 existe pour traiter, alors qu'une coupure
  réseau ou d'authentification ne se répare pas en continuant. **Alternatives considérées:**
  toute défaillance de scénario met fin à la version, écartée. **Implemented by:** FR-NEW-050.
  **Round:** 6, arbitrage de la phase 6.3. **Code evidence:**
  `src/tgi/agents/orchestrator.py:251-257`, où une `LLMJSONError` donne aujourd'hui
  `needs_human` sans arrêter l'exécution.

## 18. Implementability Gate

> **Compteur remis à zéro.** Les trois rounds consignés ci-dessous ont été menés sur le
> parapluie `SPEC-0001`, avant la scission. Ils sont conservés parce qu'ils expliquent pourquoi
> ce document existe, et parce que 15 de ses exigences et 8 de ses tests en sont issus. Le gate
> de ce document est à passer à neuf, après que SPEC-0001a aura passé le sien : les deux
> constats F qui restaient ouverts, F-01 sur les leurres incomplets et F-02 sur les sept routes
> non testées, sont désormais l'un dans SPEC-0001a et l'autre dans la table des sources ajoutées
> ci-dessus.

### Historique, mené sur le parapluie SPEC-0001

| Round | F (functional, blocking) | A (drift, traced) | Verdict |
|---|---|---|---|
| 1 | 20 (10 BLOCKING, 10 MINOR) | 9 | NOT-IMPLEMENTABLE |
| 2 | 6 (4 BLOCKING, 2 MINOR) | 2 | NOT-IMPLEMENTABLE |
| 3 | 3 (2 BLOCKING, 1 MINOR) | 2 | NOT-IMPLEMENTABLE, **plafond de trois rounds atteint** |

**Statut : ESCALADÉ.** Le document n'est pas commité. Deux constats F restent ouverts, tous deux
dans le même domaine, et le plafond de trois rounds est atteint. Voir « Escalade » ci-dessous.

**Amendments applied, round 1 :** 15 exigences ajoutées, FR-NEW-048 à FR-NEW-062 ; 8 tests
ajoutés, E2E-092 à E2E-099 ; 4 tests corrigés, E2E-036, E2E-041, E2E-083 et les
postconditions de SC-004 ; 3 exigences précisées, FR-NEW-035 (noms de champs du schéma),
FR-NEW-040 (paramètres de requête et charge `%2E%2E`), FR-NEW-042 (`version` sans `project`).

**Amendments applied, round 2 :** E2E-094, E2E-095 et E2E-096 reçoivent des **leurres
complets** ; E2E-097 voit son « rouge avant le correctif » corrigé et reçoit une assertion
structurelle qui, elle, est réellement rouge ; E2E-026 et E2E-054 sont reclassés Edge et sortis
de la couverture de sécurité ; la section 2.4 gagne une table des **sources que cet incrément
ajoute** ; la section 14 est alignée sur FR-NEW-046 et reçoit l'ordre d'insertion des 15
nouvelles exigences ; les catégories de 12.1 sont recomptées, sécurité 8 et edge 14.

**Amendments applied, round 3 :** le total annoncé en 12.1 passe de 91 à 99 ; la citation de
FR-NEW-062 passe de `orchestrator.py:222` à `:223`, ligne où `tests_per_scenario` est réellement
consommé ; les 15 exigences nées du round 1 reçoivent leurs références dans la colonne
`FR refs` de 12.1, de sorte qu'aucune des 70 exigences ne descende sous 3 tests. Les deux
constats A du round 3 sont corrigés directement plutôt qu'enregistrés : ce sont des erreurs sur
le document, pas des désalignements avec le code.

**Drift registered :** DRIFT-001 à DRIFT-009 au round 1, DRIFT-010 au round 2.

### Escalade, après trois rounds

Le plafond de trois rounds est atteint et le verdict reste `NOT-IMPLEMENTABLE`. Ce qui doit
être dit explicitement, parce que c'est le signal que le contrat demande de rapporter : **les
constats F des rounds 2 et 3 sont tous nouveaux, aucun n'est un survivant du round précédent**,
et ils se concentrent tous dans un seul domaine, la fermeture de la classe de traversée de
chemin.

La suite est instructive, parce que chaque round a fermé une condition et découvert la suivante :

1. **Round 1.** Les tests de sécurité n'existaient pas sous une forme attaquante : la charge
   `..%2F..%2F` est absorbée par le routeur de Starlette avant d'atteindre un gestionnaire.
2. **Round 2.** La charge `%2E%2E` atteint bien le gestionnaire, mais la cible `projects/..` ne
   portait pas de `project.json` : la lecture échouait et le 404 tombait tout seul.
3. **Round 3.** Les leurres sont présents mais **incomplets au regard du modèle de données de la
   section 8** : il leur manque `created_at`, `next_version`, `prompts`. Une implémentation qui
   valide strictement les rejette comme corrompus et répond 404 sans aucune vérification de
   chemin. E2E-095 et E2E-096b résistent à ce traitement, E2E-094 et E2E-096a non.

Trois fois de suite, la correction a été juste et insuffisante. Ce motif ne se résout pas par un
quatrième round : il dit que la fermeture d'une classe CWE-22 sur 9 routes, avec ses leurres,
ses canaux de vérification distincts et sa preuve de rougeur avant correctif, est un lot à part
entière, et non une section d'un lot de refonte d'interface. La décision qui débloque est une
décision de périmètre, prise par l'utilisateur, et non un round de plus.

**Constats F survivants, et eux seuls :**

- **F-01, bloquant.** Les leurres de E2E-094 et E2E-096a sont incomplets au regard de la
  section 8, et FR-NEW-033 ne définit `corrompu` que pour la liste des projets, pas pour
  `GET .../source` ni pour `GET /?project=`. Une implémentation stricte répond donc 404 sans
  valider, et les deux tests sont verts avant le correctif.
- **F-02, bloquant.** Sept routes prennent `{project_id}` ou `{version}` et les portent vers un
  chemin disque sans qu'aucun test ne leur envoie une valeur mal formée :
  `POST .../runs`, `GET .../prompts`, `GET .../versions/{version}`,
  `GET .../versions/{version}/events`, `GET .../versions/{version}/xlsx`,
  `POST .../versions/{version}/qc` et `GET .../versions/{version}/qc.xlsx`.
  `POST /api/v1/projects/%2E%2E/runs` écrirait un dossier `v1/` hors du répertoire des projets.
- **F-03, mineur.** Cinq exigences du round 1 n'ont pas de test propre : FR-NEW-052 (trame SSE
  et rejeu), FR-NEW-054 (`champ vide`), FR-NEW-059 (ordre des refus au dépôt), FR-NEW-061
  (tri des projets corrompus), FR-NEW-062 (refus de `tests_per_scenario`). Elles sont
  référencées par des tests voisins mais aucun n'vérifie leur comportement propre.

Le round 2 a trouvé que les quatre tests de sécurité écrits au round 1 pour corriger F-10
**étaient encore verts avant le correctif**, pour une raison différente de la première :
`projects/..` ne portait pas de `project.json`, donc le gestionnaire échouait à lire et rendait
404 de lui-même. L'auditeur l'a établi en exécutant réellement le routeur, pas en le
raisonnant. Deux conditions sont donc requises pour qu'un test de traversée attaque : que la
charge atteigne le gestionnaire, et que la cible ait quelque chose à rendre. Le round 1 n'avait
traité que la première.

#### DRIFT-010: le balayage de classe ignorait les sources que cette spécification ajoute
- **Spec says:** la section 2.4 énumère toute source atteignant un puits de système de fichiers.
- **Code does:** le balayage ne portait que sur le code existant. FR-NEW-019 et FR-NEW-010
  introduisent une clé venue du corps de la requête qui atteint `v<n>/prompts/<clé>.md`, et
  FR-NEW-042 deux paramètres de requête qui atteignent le disque ; aucun n'était dans la table.
- **Nature:** incomplete sweep
- **Resolution during implementation:** la table des sources ajoutées, en fin de section 2.4,
  les dispose toutes ; la clé de prompt est fermée par la liste blanche de FR-NEW-019 plutôt que
  par une expression régulière.
- **Detected by:** E2E-007, qui envoie `../../../../etc/passwd` comme clé de prompt et asserte
  `list(tmp_path.rglob("passwd*")) == []`.
- **Blocks which requirement:** FR-NEW-019
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

La trouvaille qui justifie ce gate à elle seule est F-01, devenue FR-NEW-048 : chaque agent lit
son prompt une fois, depuis une constante de module, à la construction
(`src/tgi/agents/distiller.py:134`). Une implémentation qui écrivait bien
`v<n>/prompts/<clé>.md` puis exécutait les prompts livrés **passait les 91 tests** d'origine,
SC-001 étant observé uniquement sur le disque. La fonctionnalité que l'utilisatrice a demandée
en premier aurait été livrée inopérante, avec une suite verte.

La seconde du même ordre est F-10 : les deux tests de traversée de chemin d'origine, E2E-026 et
E2E-054, employaient `..%2F..%2F`, que Starlette décode **avant** le routage. Un segment
contenant `/` ne peut pas appareiller un `{param}`, donc la requête recevait le 404 du routeur
sans qu'aucun gestionnaire ne s'exécute : les deux tests étaient verts sur du code sans aucune
validation. Un test de sécurité vert avant le correctif n'est pas un test qui passe, c'est un
test qui n'attaque pas.

## 19. Implementation Drift Register

> Le comportement spécifié est correct ; l'énoncé sur le code actuel ne l'est pas, ou la
> capacité qu'une exigence suppose n'existe pas encore. **Résolu PENDANT l'implémentation de
> cette spécification, pas plus tard.** Une entrée encore ouverte à la fusion devient une entrée
> `backlog/BL-NNNN_*.md` portant cette preuve mot pour mot, et ce déplacement est une décision
> que quelqu'un signe, pas un silence.

#### DRIFT-001: l'écrasement des résultats vient de `add_or_update_tests`
- **Spec says:** « Relancer une génération fusionne les résultats en place par identifiant
  (`src/tgi/services/state_manager.py:170-182`) », section 2.1 et FR-MOD-001.
- **Code does:** `add_or_update_tests` n'a **aucun appelant** dans `src/tgi`. L'écrasement se
  produit par `distil` qui remplace la liste `scenarios`
  (`src/tgi/agents/orchestrator.py:114-117`) et par `update_scenario(..., {"tests": ...})`
  (`src/tgi/services/state_manager.py:134-141`, appelé en
  `src/tgi/agents/orchestrator.py:270-281`).
- **Nature:** false statement
- **Resolution during implementation:** supprimer `add_or_update_tests`, et écrire l'état par
  version au travers de `update_scenario` sur `v<n>/state.json`.
- **Detected by:** E2E-043, qui compare les empreintes de `v1/state.json` avant et après la v2.
- **Blocks which requirement:** FR-MOD-001
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-002: le nombre de reprises vaut 5 et doit être ramené à 3
- **Spec says:** « 3 tentatives au total », FR-NEW-024 et FR-NEW-051.
- **Code does:** `llm_json_retries: int = 5` (`src/tgi/config.py:133`), consommé par
  `src/tgi/services/llm.py:370`.
- **Nature:** transform mismatch
- **Resolution during implementation:** ramener le défaut à 3 et construire le client avec
  `AsyncOpenAI(max_retries=0)`, faute de quoi deux mécanismes de reprise se composent et le
  compte d'appels devient illisible.
- **Detected by:** E2E-041, qui compte exactement 3 requêtes HTTP de génération.
- **Blocks which requirement:** FR-NEW-051
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-003: la liste des appels à `git_service` de FR-DEL-002 est incomplète
- **Spec says:** appels en `src/tgi/tgi.py:302`, `:403`, `:414`, `:430`, `:448`, `:459`,
  FR-DEL-002.
- **Code does:** il y a aussi `src/tgi/tgi.py:681` ; `self._git.commit` en
  `src/tgi/agents/orchestrator.py:145`, `:158`, `:199`, `:285` ; le paramètre `git_service` de
  la signature `Orchestrator(...)` en `src/tgi/agents/orchestrator.py:74` ; et
  `src/tgi/validate.py:30`, `:185-194`.
- **Nature:** false statement
- **Resolution during implementation:** retirer le paramètre `git_service` d'`Orchestrator` et
  l'usage de `GitService` dans `validate.py`, en plus des routes nommées.
- **Detected by:** `make typecheck` dès que `git_service.py` est supprimé, puis
  `tests/test_orchestrator_pipeline.py:17` et `tests/test_validate.py` qui échouent à l'import.
- **Blocks which requirement:** FR-DEL-002
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-004: trois fichiers de tests classés « inchangés » ne le sont pas
- **Spec says:** « les 10 autres fichiers | 135 | Inchangés », sections 9.3 et 12.3.
- **Code does:** `tests/test_orchestrator_pipeline.py:17` et `:89` importent `GitService` ; les
  agents changent de signature par FR-NEW-048, ce qui touche `tests/test_distiller.py`.
- **Nature:** false statement
- **Resolution during implementation:** adapter ces fixtures et recompter la répartition
  62 / 69 / 173 de la section 12.3.
- **Detected by:** pytest, par `ImportError` puis `TypeError` au premier lancement.
- **Blocks which requirement:** aucune, informationnel sur le périmètre
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-005: `configuration_problems()` n'est consultée par personne
- **Spec says:** « rien ne le consulte avant de lancer une génération », section 2.1 et
  FR-NEW-029.
- **Code does:** elle est consultée au démarrage (`src/tgi/tgi.py:177`) et avant une exécution
  de validation (`src/tgi/validate.py:399`). Le démarrage vérifie en outre la fenêtre de
  contexte au travers du singleton (`src/tgi/tgi.py:189-200`).
- **Nature:** false statement
- **Resolution during implementation:** conserver `configuration_problems` pour `tgi-validate`
  seulement, et retirer la vérification de démarrage qui dépend de `llm_client`, lequel
  disparaît avec FR-MOD-002.
- **Detected by:** mypy, puis `tests/test_config.py` dès que `llm_client` est retiré.
- **Blocks which requirement:** FR-MOD-002
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-006: `tests/<test_id>.json` ferait partie de tout projet
- **Spec says:** « contenant [...] `tests/<test_id>.json`
  (`src/tgi/services/state_manager.py:207`) », section 2.1.
- **Code does:** ce fichier n'est écrit que par `update_test`
  (`src/tgi/services/state_manager.py:207-209`), atteint uniquement depuis
  `PUT /projects/{id}/tests/{tid}` (`src/tgi/tgi.py:396`), route supprimée par FR-DEL-004. Un
  projet qui n'a jamais subi d'édition manuelle n'a pas de dossier `tests/`.
- **Nature:** false statement
- **Resolution during implementation:** aucune au-delà de FR-NEW-056, qui supprime le puits.
- **Detected by:** E2E-097, qui vérifie `list(projects.rglob("tests")) == []`.
- **Blocks which requirement:** FR-NEW-056
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-007: le puits `state_manager.py:188` classé « vulnérable » est du code mort
- **Spec says:** « vulnérable : le segment vient de la sortie du modèle », section 2.4.
- **Code does:** le puits est réel mais situé dans `add_or_update_tests`
  (`src/tgi/services/state_manager.py:170`), qui n'a aucun appelant, donc il n'est pas
  atteignable aujourd'hui.
- **Nature:** false statement
- **Resolution during implementation:** le supprimer avec la fonction, par FR-NEW-056. Le
  classement « vulnérable » reste prudent et le reste : la fonction serait rebranchée sans que
  rien ne le signale.
- **Detected by:** E2E-097, et la disparition du symbole vérifiée par `rg`.
- **Blocks which requirement:** FR-NEW-056
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-008: la sévérité de la classe CWE-22 est sous-évaluée dans le bloc de tête
- **Spec says:** `Security: internal finding`, `CVSS: not scored`, bloc de tête.
- **Code does:** il s'agit d'une écriture de fichier arbitraire **non authentifiée** :
  `file.filename` est concaténé sans assainissement (`src/tgi/tgi.py:278`) puis écrit
  (`src/tgi/tgi.py:280-282`), sur un service HTTP dépourvu d'authentification, ce que la
  section 7.2 assume explicitement.
- **Nature:** false statement
- **Resolution during implementation:** scorer la faille, par exemple
  `AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H`, et préciser `Affected` en conséquence. La correction
  elle-même est déjà portée par FR-NEW-003.
- **Detected by:** E2E-015 détecte le correctif de la faille. Pour la cotation elle-même,
  **aucun test automatique ne la détecte** : elle est vérifiée par la grille de la phase 6, dont
  un point de contrôle vérifie que le bloc de tête porte un vecteur CVSS et non `not scored`.
  Cette entrée reste de nature A plutôt que promue en F parce qu'aucun utilisateur ni aucun
  consommateur de contrat n'observe de différence entre deux implémentations : seul le document
  change.
- **Blocks which requirement:** aucune
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.

#### DRIFT-009: `api.list_models` trace le point d'accès du singleton
- **Spec says:** « `LLMClient.list_models()` existe mais aucune route ne l'expose », section 2.1,
  énoncé exact.
- **Code does:** la méthode trace `settings.llm_base_url` (`src/tgi/services/llm.py:442`),
  c'est-à-dire le point d'accès global et non celui de l'instance, ce qui devient faux dès que
  FR-MOD-002 construit un client par exécution.
- **Nature:** bypassed abstraction
- **Resolution during implementation:** lire `base_url` sur l'instance du client.
- **Detected by:** mypy puis `tests/test_llm.py` dès que les champs de `Settings` disparaissent.
- **Blocks which requirement:** FR-MOD-002
- **Status:** resolved — closed during SPEC-0001b implementation (branch feat/SPEC-0001b-lean-ui-versions-models), verified by the functional suite.
