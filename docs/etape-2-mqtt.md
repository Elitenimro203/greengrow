# Étape 2 — MQTT sécurisé

Jusqu'ici les mesures arrivaient par HTTP, sans que personne ne prouve qui il
était. Maintenant elles arrivent par MQTT chiffré, et chaque bac a sa propre
identité. Voici le chemin d'une mesure :

```
Bac (simulateur ou ESP32)
   │  1. vérifie le certificat du broker (ca.crt)
   │  2. se connecte avec SON compte
   │  3. publie sur greengrow/abidjan/bac01/telemetry
   ▼
Broker Mosquitto (port 8883, TLS)
   │  4. vérifie le mot de passe
   │  5. vérifie que ce compte a le droit d'écrire sur ce topic
   ▼
Backend (abonné à greengrow/+/+/telemetry)
   │  6. lit l'identité du bac dans le TOPIC
   │  7. valide le contenu, stocke, met à jour les alertes
   ▼
Base de données
```

## 1. Ce que TLS garantit (et pourquoi on vérifie le certificat)

TLS fait deux choses distinctes :

- il **chiffre** : personne sur le réseau ne lit les messages ni les mots de passe ;
- il **authentifie le serveur** : le client est sûr de parler au vrai broker.

La deuxième garantie n'existe que si le client **vérifie** le certificat. Le
script `scripts/make_dev_certs.py` crée une petite autorité de certification
(CA) et s'en sert pour signer le certificat du broker. Chaque client reçoit
`ca.crt` et refuse tout broker dont le certificat n'est pas signé par elle.

Un client qui ne vérifie pas (le fameux `setInsecure()` sur ESP32) chiffre
quand même, mais peut-être vers un imposteur qui récupère son mot de passe.
C'est pour ça qu'il est interdit dans ce projet. Le test
`test_un_client_refuse_un_broker_dont_il_ne_connait_pas_la_ca` le démontre.

Fichiers dans `certs/` (jamais dans Git) :

| Fichier | Rôle | Secret ? |
|---|---|---|
| `ca.crt` | à copier dans chaque client, y compris l'ESP32 à l'étape 3 | non |
| `ca.key` | permet de signer des certificats | **oui** |
| `server.crt` | carte d'identité du broker | non |
| `server.key` | prouve que le broker est bien le propriétaire de la carte | **oui** |

## 2. Authentification et autorisation

Deux questions différentes :

- **Authentification — qui es-tu ?** Chaque bac a un compte MQTT (identifiant =
  son `bac_id`, mot de passe aléatoire de 32 caractères).
- **Autorisation — qu'as-tu le droit de faire ?** Chaque compte a un rôle qui
  liste les topics permis. Tout le reste est interdit par défaut.

| Compte | Peut publier | Peut s'abonner |
|---|---|---|
| un bac (`bac01`) | `greengrow/{site}/bac01/telemetry`, `status`, `event` | `greengrow/{site}/bac01/cmd`, `config` |
| `greengrow-backend` | `greengrow/+/+/cmd`, `config` | `greengrow/#` |
| `admin` | gestion des comptes uniquement | — |

Conséquence : un bac volé ou piraté ne peut ni lire les autres bacs, ni
publier à leur place, ni s'envoyer des commandes de pompe.

Les comptes sont gérés par le plugin *dynamic security* de Mosquitto
(`backend/mqtt/dynsec.py`). Le backend crée le compte d'un bac à chaud quand
tu l'enregistres. Le broker ne garde qu'un **hachage** du mot de passe.

## 3. Le mot de passe d'un bac n'est montré qu'une fois

`POST /api/bacs` renvoie les identifiants MQTT dans sa réponse, et c'est la
seule fois où le mot de passe est visible. Il n'est stocké ni en base ni dans
les logs. S'il est perdu ou s'il a fuité :

```
POST /api/bacs/{bac_id}/mqtt-credentials
```

en génère un nouveau, et l'ancien cesse immédiatement de fonctionner.

## 4. L'identité vient du topic, jamais du message

Avant, le message disait `"bac_id": "bac01"` et le serveur le croyait. Un bac
pouvait donc mentir. Maintenant le message ne contient plus de `bac_id` : le
backend lit l'identité dans le topic, et c'est le **broker** qui garantit que
seul le compte `bac01` peut écrire sur les topics de `bac01`
(`backend/mqtt/ingestion.py`).

Règle générale à retenir : ne jamais faire confiance à ce qu'un client
déclare sur lui-même ; s'appuyer sur ce que le système a vérifié.

## 5. Une clé pour les actions sensibles

Enregistrer un bac donne maintenant des identifiants MQTT. Cette route ne
peut donc plus être ouverte à tous : elle exige l'en-tête `X-Admin-Key`
(valeur `ADMIN_API_KEY` du fichier `.env`). Pareil pour l'injection manuelle
d'une mesure par HTTP, gardée comme outil de test.

Si la clé n'est pas configurée, ces routes sont **fermées** (et non ouvertes) :
un oubli ne doit jamais ouvrir une porte. Cette clé est provisoire, elle sera
remplacée par un vrai login à l'étape 4. Les routes de lecture (`GET`) restent
ouvertes jusque-là.

## 6. En ligne / hors ligne : le Last Will

À la connexion, le bac publie `online` (message retenu) sur son topic
`status` et confie au broker un « testament » : *si je disparais sans prévenir,
publie `offline` à ma place*. Le backend range cet état dans la table `bacs`
(`online`, `last_seen_at`) : `GET /api/bacs` montre quels bacs sont vivants.

## 7. Des tests qui jouent l'attaquant

`tests/test_broker_real.py` démarre contre le vrai broker et essaie de tricher :

- se connecter sans compte, ou avec un mauvais mot de passe ;
- utiliser le port 1883 en clair (il n'existe pas) ;
- publier à la place d'un autre bac, ou s'envoyer une commande de pompe ;
- écouter les autres bacs ;
- se créer un compte administrateur.

Tous doivent échouer. GitHub rejoue ces tests à chaque push.

## Essayer

```bash
cp .env.example .env            # puis remplis les 3 secrets
python scripts/make_dev_certs.py
docker compose up -d
alembic upgrade head
uvicorn backend.main:app --reload
# autre terminal
python simulator/sensor_simulator.py
```

Puis ouvre http://localhost:8000/api/bacs : ton bac est `online`. Arrête le
simulateur en fermant brutalement le terminal : environ une minute plus tard,
le broker publie le testament et le bac passe `offline`.

## Limites connues, traitées plus tard

- Le certificat est signé par une CA locale : parfait en développement, remplacé
  par un vrai certificat sur le serveur (étape 5).
- `server.key` est lisible par tous les utilisateurs de ta machine, pour que le
  conteneur puisse le lire. Acceptable pour un certificat de développement.
- Les routes de lecture de l'API n'ont pas encore de login (étape 4).
