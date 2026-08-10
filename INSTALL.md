# Installation, pas à pas


> Sur Windows et pour un lecteur non technique, suivre `WINDOWS.md`, plus détaillé et pas à pas.
Guide pour une première installation, sans connaissance préalable du projet.
Comptez 10 minutes. Tout se fait dans un terminal, en copiant les commandes.

Si vous voulez seulement vérifier qu'un modèle fonctionne, sautez à
[VALIDATION.md](VALIDATION.md).

---

## 1. Installer les deux prérequis

Il n'y a que deux choses à installer. Pas besoin d'installer Python vous même,
`uv` s'en occupe.

### Windows

Ouvrez **PowerShell** (touche Windows, tapez `powershell`, Entrée) et collez:

```powershell
winget install --id=astral-sh.uv -e
winget install --id=Git.Git -e
```

**Fermez puis rouvrez PowerShell** pour que les commandes soient reconnues.

### macOS ou Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Git est en général déjà présent. Sinon: `brew install git` sur macOS,
`sudo apt install git` sur Ubuntu.

### Vérifier

```bash
uv --version
git --version
```

Deux numéros de version doivent s'afficher. Si une commande n'est pas reconnue,
fermez et rouvrez le terminal.

> `git` est indispensable: l'application crée un dépôt git par projet pour garder
> l'historique de chaque modification.

---

## 2. Récupérer le code

```bash
git clone https://github.ibm.com/Sebastien-Morand/test-generation-interface.git
cd test-generation-interface
```

Toutes les commandes qui suivent se lancent **depuis ce dossier**.

---

## 3. Installer les dépendances

```bash
uv sync
```

`uv` télécharge Python 3.13 si besoin, crée un environnement isolé et installe
tout. Rien n'est modifié ailleurs sur votre machine.

---

## 4. Configurer l'accès au modèle

Copiez le fichier d'exemple, puis éditez votre copie.

### Windows

```powershell
copy .env.example .env
notepad .env
```

### macOS ou Linux

```bash
cp .env.example .env
nano .env
```

**Quatre lignes suffisent** pour démarrer. Remplacez les valeurs par les vôtres:

```
TGI_LLM_BASE_URL=http://votre-serveur:8000/v1
TGI_LLM_API_KEY=votre-cle
TGI_MODEL_GENERATOR=nom-exact-du-modele
```

| Ligne | Ce que c'est |
|---|---|
| `TGI_LLM_BASE_URL` | l'adresse de votre serveur de modèle, terminée par `/v1` |
| `TGI_LLM_API_KEY` | votre clé. Si le serveur n'en demande pas, mettez n'importe quoi de non vide |
| `TGI_MODEL_GENERATOR` | le nom exact du modèle, tel que le serveur l'attend |

Enregistrez et fermez. Les autres lignes du fichier ont des valeurs par défaut
qui conviennent; vous y reviendrez plus tard si besoin.

> Ce fichier contient votre clé. Il n'est jamais envoyé sur GitHub, il est
> volontairement exclu du suivi de version.

---

## 5. Vérifier que tout répond

```bash
uv run tgi-validate
```

La commande traite un petit document d'exemple fourni avec l'application, puis
affiche un verdict. Comptez une à deux minutes.

Ce que vous voulez lire à la fin:

```
VERDICT: USABLE
```

Si vous lisez `NOT USABLE AS CONFIGURED`, la sortie indique le problème **et** le
réglage à changer. Les cas fréquents sont listés dans
[VALIDATION.md](VALIDATION.md#5-fix-the-usual-failures), notamment le proxy
d'entreprise et les certificats.

---

## 6. Lancer l'application

```bash
uv run tgi
```

Pour simplifier, un raccourci est fourni à la racine du projet:

- **Windows**: double-cliquez sur `tgi.bat` (ou lancez `.\tgi.bat` dans PowerShell).
- **macOS ou Linux**: `./tgi.sh`

Les deux font la même chose que `uv run tgi`.

Laissez cette fenêtre ouverte, c'est le serveur. Ouvrez votre navigateur sur:

**http://localhost:8080**

Pour arrêter le serveur: `Ctrl` + `C` dans la fenêtre du terminal.

---

## 7. Utiliser l'application

1. **Importer** votre document de spécifications (Word, PDF ou texte).
2. **Vérifier le découpage** proposé en scénarios, puis le valider. Cette étape est
   volontairement manuelle: elle évite de lancer des traitements coûteux sur un
   découpage inadapté.
3. **Lancer le traitement**. L'avancement s'affiche en direct, scénario par scénario.
4. **Relire les résultats**. Chaque scénario porte un score de couverture:

   | Couleur | Signification |
   |---|---|
   | Vert | couverture au dessus du seuil, scénario terminé |
   | Orange | à relire, la couverture reste sous le seuil |
   | Rouge | couverture faible, ou erreur technique |
   | Gris | aucune règle métier dans ce scénario, normal pour un sommaire |

   Un bouton **Rejouer** est disponible sur chaque scénario. Les paires de règles très
   proches sont signalées, à vous de trancher: elles ne sont jamais fusionnées
   automatiquement, car une règle et sa négation se ressemblent beaucoup.
5. **Exporter** les tests en archive ZIP.

---

## 8. Où sont les fichiers

| Quoi | Où |
|---|---|
| Vos projets et les tests générés | dossier `projects/` |
| Journal de l'application | `tgi.log` |
| Traces de performance | `tgi-otel.log` |

Les deux journaux sont dans le dossier indiqué par `TGI_LOGS`. Par défaut:
`%LOCALAPPDATA%\tgi\logs` sur Windows, `~/.cache/tgi/logs` ailleurs. Pour choisir
un autre endroit, ajoutez dans `.env`:

```
TGI_LOGS=C:/chemin/vers/logs
TGI_PROJECTS_DIR=C:/chemin/vers/projects
```

Pour voir les statistiques d'un traitement (durées, appels, taux d'échec):

```bash
uv run python -m tgi.stats
```

---

## Si ça ne marche pas

| Symptôme | Cause probable et solution |
|---|---|
| `uv` ou `git` non reconnu | fermez et rouvrez le terminal après l'installation |
| `TGI_LLM_API_KEY is still the placeholder` | vous n'êtes pas dans le dossier du projet, ou le `.env` n'est pas créé. Le fichier est lu depuis le dossier courant |
| `Connection error` | la requête n'atteint pas le serveur: proxy d'entreprise ou certificat. Voir [VALIDATION.md](VALIDATION.md#5-fix-the-usual-failures) |
| `models seen: not listed by this endpoint` | normal avec certaines passerelles, le traitement continue. Vérifiez seulement que les noms de modèles sont exacts |
| Le traitement est très lent | le modèle « réfléchit » avant de répondre. Ajoutez `TGI_DISABLE_THINKING=true` dans `.env` |
| Un scénario est en erreur | cliquez sur **Rejouer**. Le message d'erreur est affiché sur le scénario |

---

## Pour aller plus loin

- [docs/architecture.html](docs/architecture.html) : schémas d'architecture et du
  pipeline, à ouvrir dans un navigateur
- [README.md](README.md) : fonctionnement détaillé, tous les réglages
- [VALIDATION.md](VALIDATION.md) : valider un modèle sur une autre infrastructure
