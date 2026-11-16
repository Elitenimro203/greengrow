# 🌱 GreenGrow

> Plateforme d'agriculture urbaine intelligente — Abidjan, Côte d'Ivoire

GreenGrow est un système autonome de culture en bac urbain intégrant des capteurs IoT,
une irrigation automatisée et une IA de détection de maladies des plantes.

---

## Stack technique

- **Backend** : Python 3.11 · FastAPI · SQLAlchemy · Alembic · SQLite (dev) → PostgreSQL (prod)
- **IA** : TensorFlow · MobileNetV3 · TFLite
- **IoT** : MicroPython (ESP32) · Raspberry Pi Zero 2W
- **Frontend** : HTML/CSS/JS (dashboard web, v1)

---

## Prérequis

- Python 3.11+
- Git

---

## Lancement local (backend)

```bash
# 1. Cloner le repo
git clone https://github.com/TON_USERNAME/greengrow.git
cd greengrow

# 2. Créer l'environnement virtuel
python -m venv venv

# Sur Windows :
venv\Scripts\activate
# Sur Mac/Linux :
source venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Édite .env avec tes valeurs

# 5. Créer ou mettre à jour la base de données (migrations)
alembic upgrade head

# 6. Lancer le serveur
uvicorn backend.main:app --reload
```

Le serveur tourne sur http://localhost:8000
La documentation API auto-générée : http://localhost:8000/docs

---

## Lancement du simulateur de capteurs

```bash
# Dans un second terminal (venv activé)
python simulator/sensor_simulator.py
```

Le simulateur enregistre son bac (`bac-sim-01`) tout seul au démarrage.

---

## Lancer les tests

```bash
pytest
```

Les tests utilisent une base en mémoire : ils ne touchent jamais à ta vraie base.
Ils tournent aussi automatiquement sur GitHub à chaque push (onglet Actions).

---

## Structure du projet

```
greengrow/
├── backend/           # API FastAPI
│   ├── config.py      # Configuration (lue depuis .env)
│   ├── api/           # Routes HTTP (bacs, mesures, alertes)
│   ├── services/      # Logique métier (enregistrement, alertes)
│   └── models/        # Tables (entities) et schémas d'entrée/sortie (schemas)
├── migrations/        # Historique du schéma de la base (Alembic)
├── tests/             # Tests automatiques (pytest)
├── simulator/         # Simule les capteurs ESP32 (dev sans hardware)
├── ai/                # Pipeline IA détection maladies
│   ├── training/      # Entraînement modèle
│   └── inference/     # Inférence TFLite
├── docs/              # Documentation
├── .env.example       # Variables d'environnement (template)
├── requirements.txt   # Dépendances Python
└── README.md
```

---

## Variables d'environnement

Voir `.env.example` pour la liste complète.
Ne jamais committer le fichier `.env` — il est dans le `.gitignore`.

---

## Équipe

Projet solo — GIDT-CI · Master MBDS · ESATIC Abidjan
