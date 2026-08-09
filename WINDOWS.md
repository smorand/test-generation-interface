# Installer et lancer sur Windows, pas à pas

Ce guide s'adresse à quelqu'un qui n'a jamais utilisé de terminal. Il y a trois étapes, une
seule fois, puis un double clic à chaque utilisation.

Comptez vingt minutes la première fois.

---

## Étape 1 : installer les deux outils nécessaires

Il faut deux logiciels : **git** (pour récupérer le projet) et **uv** (pour lancer le
programme). Aucun des deux ne demande de configuration.

### git

1. Aller sur <https://git-scm.com/download/win>
2. Le téléchargement démarre tout seul. Ouvrir le fichier téléchargé.
3. Cliquer **Suivant** jusqu'au bout, puis **Installer**. Ne changer aucune option.

### uv

1. Cliquer sur le menu Démarrer, taper `powershell`
2. Cliquer sur **Windows PowerShell** dans la liste
3. Copier la ligne ci-dessous, la coller dans la fenêtre noire (clic droit pour coller),
   puis appuyer sur Entrée :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

4. Attendre le message de fin. **Fermer la fenêtre PowerShell**, c'est important : les
   outils ne sont visibles qu'après avoir rouvert une fenêtre.

### Vérifier que ça a marché

Ouvrir une **nouvelle** fenêtre PowerShell et taper ces deux lignes, une par une :

```powershell
git --version
uv --version
```

Chacune doit répondre un numéro de version. Si l'une répond « n'est pas reconnu », son
installation a échoué : recommencer cette étape.

---

## Étape 2 : récupérer le programme

Toujours dans PowerShell, copier ces trois lignes une par une :

```powershell
cd $HOME\Documents
git clone https://github.com/smorand/test-generation-interface.git
cd test-generation-interface
```

Le programme est maintenant dans `Documents\test-generation-interface`.

---

## Étape 3 : indiquer où trouver le modèle d'IA

Le programme a besoin de deux informations : l'adresse du serveur d'IA et la clé d'accès.
Elles vous ont été fournies séparément.

1. Ouvrir l'Explorateur de fichiers, aller dans `Documents\test-generation-interface`
2. Faire un clic droit sur le fichier `.env.example`, choisir **Copier**, puis clic droit
   dans le dossier et **Coller**
3. Renommer la copie en `.env` exactement, sans autre extension
4. Clic droit sur `.env`, **Ouvrir avec**, **Bloc-notes**
5. Remplir ces trois lignes, en gardant le reste tel quel :

```
TGI_LLM_BASE_URL=https://adresse-du-serveur/v1
TGI_LLM_API_KEY=votre-cle
TGI_MODEL_GENERATOR=Qwen3.6-27B
TGI_MODEL_JUDGE=Qwen3.6-27B
```

6. Enregistrer, fermer le Bloc-notes.

Si Windows cache les extensions et que le fichier s'appelle `.env.txt`, il ne sera pas lu.
Dans l'Explorateur : onglet **Affichage**, cocher **Extensions de noms de fichiers**, puis
renommer proprement en `.env`.

---

## Utilisation quotidienne

Dans le dossier `test-generation-interface`, **double cliquer sur `tgi.bat`**.

Une fenêtre noire s'ouvre et reste ouverte : c'est normal, c'est le programme qui tourne.
Ne la fermez pas pendant l'utilisation.

Ouvrir ensuite un navigateur à l'adresse : <http://localhost:8080>

La fenêtre noire affiche d'ailleurs l'adresse à ouvrir, dans une ligne
« Ouvrez http://127.0.0.1:8080 dans votre navigateur ».

Pour arrêter : fermer la fenêtre noire.

---

## Vérifier que le modèle d'IA répond, avant de perdre du temps

Avant d'importer un vrai document, faites ce test. Il prend une minute et dit si la
connexion et le modèle fonctionnent.

Dans PowerShell, dans le dossier du programme :

```powershell
uv run tgi-validate
```

À la fin, une ligne indique **VERDICT: USABLE** ou **NOT USABLE**. Si c'est NOT USABLE, le
texte au dessus explique quoi corriger, en général l'adresse, la clé, ou un certificat
d'entreprise (voir la fin de ce document).

---

## Se servir du programme

1. **Importer** : choisir le document de spécifications (Word, PDF ou texte), laisser les
   modèles proposés, et éventuellement changer **Tests par scénario** (5 par défaut).
   Cliquer sur **Importer et analyser**.

2. **Onglet CARTE** : le programme lit le document en entier et en extrait le contexte, les
   scénarios utilisateur et les exigences. Cela prend de quelques secondes à une minute.
   Relisez cette page : c'est le seul endroit où une correction coûte une minute au lieu de
   centaines de tests inutiles. La page signale les cas d'utilisation du document qu'aucun
   scénario ne couvre, et propose d'écarter ce qui ne sert pas à tester (historique de
   versions, éléments hors périmètre). Pour chaque écart proposé : **écarter** ou **garder**.

3. Le bandeau du haut nomme les trois étapes et montre celle où vous êtes:
   **1 Lecture du document**, **2 Relecture de la carte, par vous**, **3 Génération des tests**.
   L'étape 2 est la vôtre: en cliquant sur **✓ Je valide la carte, on peut générer**, vous dites
   que les scénarios et les exigences relevés sont les bons. Rien de coûteux ne tourne avant.
   Si vous changez d'avis après, **↺ Relire** dans l'onglet CARTE relit le document et vous
   redemande de valider.

4. Cliquer sur **▶ Lancer la génération**. La barre de progression indique où en est le
   traitement et le temps restant estimé.

5. **Onglet SCÉNARIOS & TESTS** : le livrable, rangé comme le document. Déplier une
   fonctionnalité, un cas d'utilisation, un scénario, pour voir ses tests.

6. **Onglet EXIGENCES** : la preuve que rien n'a été oublié. Une ligne par exigence du
   document, groupée par cas d'utilisation, avec son énoncé tel qu'il est écrit et les tests
   qui la couvrent. Filtrez sur **non couvertes** pour voir ce qui reste à traiter.

   Le badge **sans énoncé** compte les exigences que le document cite sans jamais les écrire,
   par exemple une notification dont le numéro n'a pas été décidé. Cliquez dessus pour les
   lister: ce sont des trous de la spécification, pas des oublis de l'outil, et rien ne peut
   être testé tant que le document ne les énonce pas.

   L'étape 2 vous les propose d'ailleurs en écart, avec l'étiquette **sans énoncé**. Cliquer
   sur **écarter** les sort du décompte et de la génération, en gardant la trace de votre
   décision; **garder** les laisse visibles, par exemple le temps de faire corriger le
   document. Rien n'est retiré sans votre clic: c'est aussi la liste à renvoyer à l'auteur.

7. **Onglet RECHERCHE** : chercher un test, le corriger à la main.

8. **Onglet CHAT** : poser des questions sur le document, les tests, la couverture. Le chat
   répond, il ne modifie rien.

9. **⬇ Export ZIP** en haut : une archive contenant le document, le corpus distillé, les
   scénarios, les exigences, et surtout **`4-tests.xlsx`** à ouvrir dans Excel. C'est ce
   fichier qu'on relit et qu'on transmet.

Rien n'est perdu : chaque étape est enregistrée, et l'onglet HISTORIQUE permet de revenir
en arrière.

---

## Si ça ne marche pas

**« uv n'est pas reconnu »** : la fenêtre PowerShell a été ouverte avant l'installation de
uv. La fermer, en ouvrir une nouvelle.

**Rien ne s'affiche sur <http://localhost:8080>** : la fenêtre noire est-elle toujours
ouverte ? Si elle s'est fermée seule, relancer `tgi.bat` et lire le message d'erreur qui
s'affiche avant la fermeture.

**« Le port 8080 est déjà utilisé par un autre programme »** : un autre logiciel occupe ce
port, c'est courant sur un poste de travail. Ajouter dans le fichier `.env` :

```
TGI_PORT=8081
```

puis relancer `tgi.bat`, et ouvrir <http://localhost:8081>.

**Erreur de certificat, ou « SSL »** : un proxy d'entreprise inspecte la connexion. Ajouter
dans le fichier `.env` le chemin du certificat fourni par votre équipe réseau :

```
TGI_LLM_CA_BUNDLE=C:\chemin\vers\certificat.pem
```

En dernier recours seulement, et jamais avec des données sensibles :

```
TGI_LLM_VERIFY_SSL=false
```

**Le traitement est très lent** : lancer `uv run tgi-validate`. S'il annonce plusieurs
minutes par scénario, le modèle passe son budget à raisonner. Essayer d'ajouter dans
`.env` :

```
TGI_DISABLE_THINKING=true
```

**Où sont les fichiers ?** Les projets sont dans le sous dossier `projects`. Les journaux
sont dans `%LOCALAPPDATA%\tgi\logs`.

---

## Pour aller plus loin

- `README.md` : ce que fait le programme et comment il est construit
- `VALIDATION.md` : valider un modèle sur une nouvelle infrastructure
- `INSTALL.md` : installation détaillée, toutes plateformes
