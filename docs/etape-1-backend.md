# Étape 1 — Un backend solide

Cette étape ne rajoute presque rien de visible. Elle prépare le terrain pour
que les étapes suivantes (MQTT, firmware, dashboard) se posent sur du solide.
Voici ce qui a changé et pourquoi.

## 1. La base est pensée pour plusieurs bacs

Avant : une mesure d'un bac inconnu créait automatiquement un bac "Prototype".
N'importe qui pouvait donc inventer des bacs en envoyant des mesures.

Maintenant :

- un bac doit être **enregistré** (`POST /api/bacs`) avant d'envoyer quoi que ce soit ;
- une mesure d'un bac inconnu est refusée (erreur 404) ;
- chaque bac appartient à un **site** et porte **ses propres seuils**
  (humidité basse, humidité haute, température max). Ajouter une autre culture,
  c'est créer un bac avec d'autres seuils, sans toucher au code.

Les tables sont dans `backend/models/entities.py` : `sites`, `bacs`, `readings`, `alerts`.

## 2. Une alerte par problème, pas une alerte par mesure

Avant : chaque mesure sous le seuil créait une alerte. Un bac sec toute une
nuit = des centaines d'alertes identiques.

Maintenant (`backend/services/alerts.py`) : une alerte **s'ouvre** quand le
seuil est franchi, reste ouverte tant que le problème dure, et **se ferme**
quand la valeur redevient normale. `GET /api/alerts/{bac_id}?active=true`
donne les problèmes en cours.

## 3. Routes, services, modèles : chacun son rôle

| Couche | Dossier | Rôle |
|---|---|---|
| Routes | `backend/api/` | Traduire HTTP : lire la requête, renvoyer la réponse |
| Services | `backend/services/` | La logique métier (stocker une mesure, décider d'une alerte) |
| Modèles | `backend/models/` | Les tables (`entities.py`) et les formats d'entrée/sortie (`schemas.py`) |

Pourquoi c'est important : à l'étape 2, les mesures arriveront par MQTT et non
plus par HTTP. L'abonné MQTT appellera le **même** service `record_reading`.
La logique n'existe qu'à un endroit.

## 4. Une seule source de configuration

`backend/config.py` lit le fichier `.env` une fois. Avant, le nom de la base
n'était pas le même dans le code et dans `.env.example`. Les appels depuis un
navigateur (CORS) étaient ouverts à tous (`*`) ; ils sont maintenant limités à
une liste (`CORS_ORIGINS`).

## 5. Les migrations (Alembic)

Le schéma de la base va évoluer (commandes de pompe, utilisateurs...). Une
**migration** est un petit fichier qui décrit un changement de schéma. Elles
sont rangées dans `migrations/versions/` et rejouées dans l'ordre.

```bash
alembic upgrade head                              # met la base à jour
alembic revision --autogenerate -m "description"  # après avoir modifié entities.py
```

Sans migrations, changer une table en production oblige à tout effacer. Avec,
la base du bac pilote pourra évoluer sans perdre une seule mesure.

**À faire une fois chez toi** : supprime l'ancien fichier `greengrow_dev.db`
(ou `.greengrow_dev.db`), puis lance `alembic upgrade head`. L'ancien schéma
n'est pas compatible et ne contenait que des données simulées.

## 6. Les tests

`tests/` contient 16 tests qui décrivent le comportement attendu, par exemple
« un problème qui dure ne crée qu'une seule alerte ». Lance-les avec `pytest`.
GitHub les relance à chaque push (`.github/workflows/ci.yml`) : si une future
modification casse quelque chose, on le voit avant de fusionner.

## Essayer

```bash
alembic upgrade head
uvicorn backend.main:app --reload
# autre terminal
python simulator/sensor_simulator.py
```

Puis ouvre http://localhost:8000/docs : tu peux créer un bac, envoyer une
mesure à 30 % d'humidité, et voir l'alerte s'ouvrir puis se fermer.
