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
- Docker Desktop (pour le broker MQTT)

---

## Première installation

```bash
# 1. Cloner le repo
git clone https://github.com/Elitenimro203/greengrow.git
cd greengrow

# 2. Créer et activer l'environnement virtuel
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les secrets
cp .env.example .env
# Ouvre .env et remplis ADMIN_API_KEY, MQTT_ADMIN_PASSWORD et MQTT_BACKEND_PASSWORD
# (trois valeurs longues et différentes ; la commande pour en générer est dans le fichier)

# 5. Créer les certificats TLS de développement (une seule fois)
python scripts/make_dev_certs.py

# 6. Créer la base de données
alembic upgrade head
```

## Lancement au quotidien

```bash
# Terminal 1 : le broker MQTT (reste en arrière-plan)
docker compose up -d

# Terminal 1 : l'API
uvicorn backend.main:app --reload

# Terminal 2 : le bac simulé
python simulator/sensor_simulator.py
```

- API : http://localhost:8000 — documentation interactive : http://localhost:8000/docs
- Le simulateur enregistre son bac (`bac-sim-01`) au premier lancement, reçoit ses
  identifiants MQTT et publie une mesure toutes les 5 secondes.
- Journal du broker : `docker compose logs -f mosquitto`

Explications détaillées : `docs/etape-1-backend.md`, `docs/etape-2-mqtt.md`.

---

## Lancer les tests

```bash
pytest
```

Les tests utilisent une base en mémoire : ils ne touchent jamais à ta vraie base.
Ils tournent aussi automatiquement sur GitHub à chaque push (onglet Actions).

Tests de sécurité contre le vrai broker (broker démarré) :

```bash
GREENGROW_BROKER_TEST=1 pytest tests/test_broker_real.py -v      # Mac/Linux, Git Bash
```

---

## Structure du projet

```
greengrow/
├── backend/           # API FastAPI
│   ├── config.py      # Configuration (lue depuis .env)
│   ├── api/           # Routes HTTP (bacs, mesures, alertes)
│   ├── mqtt/          # Topics, comptes du broker, ingestion des mesures
│   ├── services/      # Logique métier (enregistrement, alertes)
│   └── models/        # Tables (entities) et schémas d'entrée/sortie (schemas)
├── mosquitto/         # Configuration du broker MQTT
├── scripts/           # Outils (certificats TLS de développement)
├── docker-compose.yml # Lance le broker
├── migrations/        # Historique du schéma de la base (Alembic)
├── tests/             # Tests automatiques (pytest)
├── simulator/         # Bac simulé : se connecte en MQTT comme un vrai ESP32
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
