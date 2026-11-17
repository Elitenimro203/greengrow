# 🛠️ Guide Setup — Git, Python & GreenGrow
> Pour quelqu'un qui part de zéro avec Git. Pas de raccourci, pas de magie noire.

---

## 1. Comprendre Git en 2 minutes

Git est une **machine à remonter le temps pour ton code**.

Imagine que tu travailles sur un document Word. Chaque fois que tu fais une
avancée importante, tu sauvegardes une version : "Version_finale.docx",
"Version_finale_v2.docx", "Version_VRAIMENT_finale.docx"...

Git fait ça proprement. Chaque sauvegarde s'appelle un **commit**.
La différence : Git retient exactement ce qui a changé, quand, et pourquoi.

**GitHub** = le Google Drive de tes repos Git.
Ton code est sur ton ordinateur ET sur GitHub. Si ton PC brûle, ton code survit.

### Les 6 commandes que tu utiliseras 95% du temps

```bash
git status          # "Qu'est-ce qui a changé depuis mon dernier commit ?"
git add .           # "Prépare TOUS les fichiers modifiés pour le prochain commit"
git commit -m "msg" # "Crée un checkpoint avec ce message explicatif"
git push            # "Envoie mes commits locaux vers GitHub"
git pull            # "Récupère les changements depuis GitHub"
git log --oneline   # "Montre l'historique des commits"
```

C'est tout. Pour l'instant, c'est tout ce dont tu as besoin.

---

## 2. Installation — Étape par étape

### Étape 1 : Installer Git

**Windows :**
1. Va sur https://git-scm.com/download/win
2. Télécharge et installe (options par défaut, clique "Next" partout)
3. Ouvre "Git Bash" (installé automatiquement) — c'est ton terminal Git

**Vérification :**
```bash
git --version
# Doit afficher quelque chose comme : git version 2.46.0
```

### Étape 2 : Configurer ton identité Git

```bash
# Ces infos apparaissent sur chaque commit que tu fais
git config --global user.name "Ton Prénom Nom"
git config --global user.email "ton.email@exemple.com"
```

Fais ça une fois. C'est permanent.

### Étape 3 : Créer ton compte GitHub

1. Va sur https://github.com
2. "Sign up" avec ton email
3. Choisis un username propre — ce sera visible sur ton profil pro

### Étape 4 : Installer Python (3.11 à 3.14)

1. Va sur https://www.python.org/downloads/
2. Télécharge une version entre 3.11 et 3.14 (le projet est testé sur 3.11 et 3.14)
3. **IMPORTANT** : Coche "Add Python to PATH" pendant l'installation

**Vérification :**
```bash
python --version
# Doit afficher une version entre 3.11 et 3.14
```

---

## 3. Créer le repo GreenGrow

### Sur GitHub d'abord

1. Connecte-toi sur GitHub
2. Clique sur le "+" en haut à droite → "New repository"
3. Remplis :
   - Repository name : `greengrow`
   - Description : `Plateforme d'agriculture urbaine intelligente — Abidjan`
   - Visibilité : **Private** pour l'instant (tu rendras public quand tu veux)
   - ⚠️ NE PAS cocher "Add a README" — on le fait nous-mêmes
4. Clique "Create repository"
5. Copie l'URL qui apparaît (format : `https://github.com/TON_USERNAME/greengrow.git`)

### Sur ton ordinateur

```bash
# 1. Crée un dossier greengrow où tu veux (ex: Bureau)
mkdir greengrow
cd greengrow

# 2. Initialise Git dans ce dossier
git init
# Résultat : "Initialized empty Git repository in .../greengrow/.git/"
# Ce dossier .git est le cerveau de ton repo — ne le touche jamais à la main

# 3. Copie les fichiers du scaffold (voir section suivante)

# 4. Connecte ton repo local à GitHub
git remote add origin https://github.com/TON_USERNAME/greengrow.git
# "origin" est le nom conventionnel pour le repo distant

# 5. Vérifie la connexion
git remote -v
# Doit afficher : origin  https://github.com/... (fetch) et (push)
```

---

## 4. Installer le scaffold GreenGrow

Copie tous les fichiers fournis dans ton dossier `greengrow/` en respectant
exactement l'arborescence :

```
greengrow/
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── api/__init__.py
│   ├── services/__init__.py
│   └── models/__init__.py
├── simulator/
│   └── sensor_simulator.py
├── ai/
│   ├── __init__.py
│   ├── training/__init__.py
│   └── inference/__init__.py
├── docs/
├── .gitignore
├── .env.example
├── requirements.txt
└── README.md
```

---

## 5. Créer l'environnement virtuel Python

```bash
# Dans le dossier greengrow/
python -m venv venv
```

**Pourquoi un environnement virtuel ?**
Sans ça, toutes tes installations pip sont "globales" sur ton PC.
Si un projet A a besoin de FastAPI version 0.100 et le projet B de la version 0.115,
ils se marchent dessus. Le `venv` isole les dépendances de chaque projet.
C'est la règle numéro 1 en Python pro — tu la prends dès le premier jour.

```bash
# Activer le venv
# Windows (Git Bash) :
source venv/Scripts/activate
# Windows (CMD) :
venv\Scripts\activate.bat
# Mac/Linux :
source venv/bin/activate

# Tu sauras que le venv est actif car ton terminal affichera "(venv)" au début
# Exemple : (venv) $ _
```

```bash
# Installer les dépendances
pip install -r requirements.txt

# Vérifier l'installation
pip list
# Tu dois voir fastapi, uvicorn, sqlalchemy, etc.
```

---

## 6. Configurer les variables d'environnement

```bash
# Copie le template
cp .env.example .env

# Édite .env (avec VS Code, Notepad++, ou n'importe quel éditeur texte)
# Pour l'instant, tu peux laisser les valeurs par défaut — elles fonctionnent en dev
```

---

## 7. Tester que tout marche

### Terminal 1 — Lance l'API

```bash
# Venv activé, dans le dossier greengrow/
uvicorn backend.main:app --reload
```

Tu dois voir :
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

Ouvre http://localhost:8000 dans ton navigateur.
Tu dois voir : `{"status":"ok","project":"GreenGrow","version":"0.1.0"}`

🎉 **Ton premier endpoint API GreenGrow tourne.**

### Terminal 2 — Lance le simulateur

```bash
# Nouveau terminal, venv activé
python simulator/sensor_simulator.py
```

Tu verras les données simulées s'afficher toutes les 5 secondes.
L'API n'a pas encore de route `/api/readings` — tu verras des warnings.
C'est **normal**. Le simulateur tourne, c'est ce qui compte maintenant.

---

## 8. Premier commit Git

```bash
# Étape 1 : Vérifie l'état de ton repo
git status
# Tu verras tous les fichiers non suivis en rouge

# Étape 2 : Ajoute tous les fichiers au "staging area"
git add .
# Le "." signifie "tout dans le dossier courant"
# Note : .gitignore empêchera automatiquement venv/ et .env d'être ajoutés

# Étape 3 : Vérifie ce qui sera commité
git status
# Cette fois les fichiers sont en vert

# Étape 4 : Crée le commit
git commit -m "init: scaffold projet GreenGrow

- Structure backend FastAPI
- Simulateur de capteurs
- Configuration .env.example
- .gitignore Python/FastAPI"

# Bonne pratique de message de commit :
# Ligne 1 : "type: description courte" (max 72 caractères)
# Types : init, feat, fix, refactor, docs, test
# Ligne 2 : vide
# Lignes suivantes : détails optionnels

# Étape 5 : Envoie sur GitHub
git push -u origin main
# Le -u origin main ne sera nécessaire qu'au premier push
# Ensuite : git push suffit
```

Va sur GitHub.com/TON_USERNAME/greengrow — ton code est en ligne.

---

## 9. Ton workflow quotidien (à mémoriser)

```bash
# Matin — récupère les changements (si tu travailles sur plusieurs machines)
git pull

# ... tu codes ...

# Soir — tu sauvegardes ton travail
git status                          # Qu'est-ce qui a changé ?
git add .                           # Je prépare tout
git commit -m "feat: description"   # Je crée le checkpoint
git push                            # Je sauvegarde sur GitHub
```

C'est littéralement tout. Répète ça chaque jour.

---

## 10. En cas de problème

### "git push" demande un mot de passe
GitHub n'accepte plus les mots de passe depuis 2021.
Tu dois utiliser un token d'accès :
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token → coche "repo" → Generate
3. Copie le token (ne le perds pas !)
4. Utilise-le comme "mot de passe" quand Git te demande

### "Permission denied"
Lance Git Bash **en tant qu'administrateur** (clic droit → Exécuter en tant qu'administrateur)

### Le venv ne s'active pas
Sous Windows, exécute d'abord :
```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Récapitulatif — Concepts à retenir

| Concept | Définition en 1 ligne |
|---|---|
| **repo** | Dossier versionné par Git |
| **commit** | Checkpoint que tu crées manuellement |
| **staging** | Fichiers préparés pour le prochain commit (après `git add`) |
| **remote** | Copie du repo sur GitHub |
| **push** | Envoie tes commits locaux vers GitHub |
| **pull** | Récupère les commits depuis GitHub |
| **venv** | Environnement Python isolé par projet |
| **.gitignore** | Liste des fichiers que Git doit ignorer |
