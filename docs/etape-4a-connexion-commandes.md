# Étape 4a — Se connecter, et commander la pompe

Jusqu'ici, n'importe qui connaissant l'adresse de l'API pouvait lire tes
mesures, et une seule clé partagée (`X-Admin-Key`) protégeait les
modifications. Cette étape remplace tout ça par de vrais comptes, puis ouvre
la première action à distance : faire tourner la pompe.

Les deux vont ensemble exprès. Avant de laisser quelqu'un déclencher un
arrosage depuis Internet, il faut savoir **qui** il est, **ce qu'il a le
droit de faire**, et garder **la trace** de ce qu'il a fait.

## 1. Ce qui change pour toi

```bash
git pull
pip install -r requirements.txt   # par précaution : cette étape n'ajoute aucune dépendance
alembic upgrade head              # crée les 4 nouvelles tables
python scripts/create_user.py --email toi@exemple.com --nom "Ton nom" --role owner
```

Le script te demande un mot de passe (10 caractères minimum), sans
l'afficher. Ensuite :

- `ADMIN_API_KEY` n'existe plus : tu peux retirer la ligne de ton `.env`.
- Le simulateur et `make_firmware_secrets.py` te demandent ton e-mail et ton
  mot de passe quand ils doivent enregistrer un bac.
- Dans http://localhost:8000/docs, exécute d'abord `POST /api/auth/login` :
  ton navigateur garde le cookie, et les autres routes s'ouvrent.

## 2. Les mots de passe : on ne les stocke pas

Fichier : `backend/services/passwords.py`.

La base ne contient **jamais** un mot de passe, seulement son **empreinte** :
le résultat d'une fonction à sens unique. Vérifier qu'un mot de passe
correspond est facile ; retrouver le mot de passe depuis l'empreinte ne l'est
pas. Si la base fuit un jour, les mots de passe ne fuient pas avec.

Trois idées à retenir :

| Idée | Pourquoi |
|---|---|
| Fonction **lente** (scrypt) | Un SHA-256 se calcule des milliards de fois par seconde : un voleur de base testerait tous les mots de passe courants en quelques minutes. scrypt coûte environ 16 Mo de mémoire et quelques dizaines de millisecondes par essai. |
| **Sel** aléatoire par compte | Deux personnes avec le même mot de passe ont des empreintes différentes, et on ne peut pas préparer une table d'empreintes à l'avance. |
| Paramètres rangés **avec** l'empreinte | `scrypt$16384$8$1$sel$empreinte` : on pourra durcir les réglages plus tard sans casser les comptes existants. |

scrypt fait partie de Python (`hashlib`) : rien à installer, donc rien à
compiler sous Windows.

## 3. La session : comment le serveur te reconnaît

Fichiers : `backend/services/auth.py`, `backend/api/auth.py`.

HTTP n'a pas de mémoire : chaque requête arrive comme si c'était la première.
Pour ne pas renvoyer ton mot de passe à chaque fois :

1. `POST /api/auth/login` avec e-mail + mot de passe, **une** fois.
2. Le serveur tire un **jeton** au hasard (32 octets) et te le donne dans un
   cookie. Dans la base, il ne garde que l'empreinte du jeton.
3. Ton navigateur renvoie le cookie tout seul à chaque requête.
4. `POST /api/auth/logout` supprime la session : le jeton ne vaut plus rien.

Le cookie porte trois protections :

| Attribut | Ce qu'il empêche |
|---|---|
| `HttpOnly` | Le JavaScript de la page ne peut pas lire le cookie. Un script malveillant injecté dans la page ne peut donc pas voler ta session. |
| `SameSite=Strict` | Le navigateur ne joint pas le cookie aux requêtes lancées depuis un **autre** site. |
| `Secure` (en production) | Le cookie ne voyage qu'en HTTPS. Activé quand `APP_ENV=production` (étape 5). |

**Pourquoi une session en base et pas un JWT ?** Un JWT est un jeton
« autonome » : le serveur le vérifie sans consulter la base, ce qui est
pratique à très grande échelle, mais on ne peut pas l'annuler avant son
expiration. Avec une session en base, se déconnecter, désactiver un compte ou
changer un mot de passe coupe l'accès **tout de suite**. Pour un système qui
commande une pompe, c'est ce qu'on veut.

### L'attaque CSRF, et les deux barrières

Imagine : tu es connecté à GreenGrow, et dans un autre onglet tu ouvres un
site piégé. Ce site contient un formulaire caché qui envoie « arrose » à ton
API. C'est **ton** navigateur qui envoie la requête, donc il joindrait ton
cookie. C'est le CSRF (*Cross-Site Request Forgery*).

- Barrière 1 : `SameSite=Strict`, le cookie n'est pas joint.
- Barrière 2 : `check_origin` dans `backend/api/security.py`. Le navigateur
  indique dans l'en-tête `Origin` de quel site vient la requête, et une page
  web ne peut pas mentir sur cet en-tête. Si ce n'est pas notre site : 403.

Deux barrières indépendantes pour le même risque : c'est la **défense en
profondeur**. Si l'une tombe (vieux navigateur, erreur de configuration),
l'autre tient.

## 4. Les rôles, et « fermé par défaut »

| Rôle | Peut |
|---|---|
| `owner` (propriétaire) | tout : bacs, seuils, commandes, journal d'audit |
| `viewer` (lecteur) | regarder les bacs, mesures, alertes, commandes |

Deux codes de refus à ne pas confondre :

- **401** : « je ne sais pas qui tu es » → connecte-toi.
- **403** : « je sais qui tu es, et c'est non » → ton rôle ne le permet pas.

Dans `backend/main.py`, la règle « il faut être connecté » est posée **une
fois** pour tous les routeurs, et non route par route. Une route ajoutée
demain est donc protégée sans que personne ait à y penser. Un test
(`test_toutes_les_routes_de_l_api_sont_protegees`) parcourt la liste de
toutes les routes et échoue si l'une répond sans connexion.

Détail qui compte : cette vérification passe **avant** tout le reste. Un
inconnu qui demande `/api/readings/bac01` reçoit 401, que le bac existe ou
non. Il n'apprend rien.

Il n'y a **pas de page d'inscription**. Un compte se crée avec
`scripts/create_user.py`, sur la machine du serveur. Moins de portes, moins
de portes à surveiller.

## 5. L'anti-devinette

Sans limite, un programme peut essayer des milliers de mots de passe par
minute. Règle : après **5** échecs en **15 minutes** sur un compte, les
tentatives sont refusées (code 429), même avec le bon mot de passe. Même
chose après 20 échecs depuis une même adresse IP.

Deux choix de conception :

- Le compteur, c'est le **journal d'audit** lui-même (on compte les lignes
  `login_failed` récentes). Il survit à un redémarrage du serveur, et
  fonctionnera encore le jour où il y aura plusieurs serveurs.
- La réponse est **identique** que le compte existe ou non, et prend le même
  temps (on calcule une empreinte « pour rien » si l'e-mail est inconnu). Un
  attaquant ne peut pas dresser la liste des comptes.

Limite connue : quelqu'un qui connaît ton e-mail peut te bloquer 15 minutes
en se trompant exprès 5 fois. C'est le prix habituel de cette protection, et
le blocage se lève tout seul.

## 6. Le trajet d'une commande

Fichiers : `backend/services/commands.py`, `backend/api/commands.py`.

```
toi ──POST /api/bacs/bac01/commands──▶ API ──▶ base : "sent"
                                        │
                                        └─MQTT greengrow/abidjan/bac01/cmd─▶ bac
                                                                              │
base : "executed" / "rejected" ◀── ingestion ◀──MQTT .../event (cmd_ack)──────┘
```

Le message envoyé au bac :

```json
{"id": "3a53402d-…", "type": "pump_on", "duration_s": 10, "expires_at": 1794874790}
```

- **`id`** : un identifiant unique tiré au hasard. MQTT en QoS 1 livre « au
  moins une fois », donc parfois deux. Le bac retient les identifiants déjà
  vus et n'exécute une commande qu'une seule fois.
- **`expires_at`** : 30 secondes après l'envoi. Un message resté coincé
  quelque part et livré plus tard est ignoré par le bac. Sans ça, une
  commande envoyée pendant une coupure pourrait arroser trois heures après.
- Le message n'est **pas retenu** par le broker (contrairement aux seuils) :
  une commande n'a de sens que maintenant.

Types acceptés : `pump_on` (avec `duration_s`, de 1 à 120), `pump_off`,
`reset_fault` (sortir du mode sécurité après avoir réparé).

### L'API ne ment pas sur ce qui s'est passé

L'API répond **202 Accepted** avec le statut `sent` : « c'est parti ». Elle
ne dit pas « c'est fait », parce qu'elle n'en sait rien. C'est l'accusé de
réception du **bac** qui fait avancer la commande :

| Statut | Signification |
|---|---|
| `sent` | envoyée, on attend le bac |
| `executed` | le bac l'a exécutée |
| `rejected` | le bac l'a refusée ; `reason` dit pourquoi (`reservoir_empty`, `fault`, `daily_limit`, `already_watering`, `expired`, `duplicate`…) |
| `expired` | aucune réponse avant l'heure limite |

Le bac garde le dernier mot : tous les garde-fous de l'étape 3 (réservoir
vide, mode sécurité, limite par jour, durée maximale) s'appliquent aussi aux
commandes manuelles. Même le propriétaire ne peut pas forcer la pompe à
tourner à sec.

### Les refus côté serveur

- Bac **hors ligne** → 409, rien n'est envoyé. Le bac ignorerait la commande
  de toute façon ; autant le dire tout de suite.
- Plus de **6 commandes par minute** sur un bac → 429.
- Un bac ne peut pas valider la commande d'un **autre** bac : l'accusé de
  réception est rapproché de la commande par son identifiant **et** par le
  bac qui répond, connu grâce au topic (la règle de l'étape 2).

## 7. Le journal d'audit

Fichier : `backend/services/audit.py`. Route : `GET /api/audit` (propriétaire).

Chaque action sensible laisse une ligne : connexion réussie ou ratée,
déconnexion, bac créé ou modifié, mot de passe MQTT renouvelé, commande
envoyée, compte créé. Avec l'heure, l'auteur, la cible et l'adresse IP.

Le jour où la pompe a tourné à 3 h du matin, ce journal répond à « qui, et
depuis où ? ». La ligne est écrite dans la **même transaction** que l'action :
impossible d'avoir l'une sans l'autre. Aucune route ne modifie ni ne supprime
une ligne, et un mot de passe n'y figure jamais.

## 8. Essayer sans matériel

Le simulateur répond maintenant aux commandes, avec le même filtre que le
firmware (identifiant + heure limite).

```bash
docker compose up -d
uvicorn backend.main:app --reload
python simulator/sensor_simulator.py      # te demande e-mail et mot de passe
```

Puis dans http://localhost:8000/docs :

1. `POST /api/auth/login` avec ton e-mail et ton mot de passe.
2. `POST /api/bacs/bac-sim-01/commands` avec `{"type": "pump_on", "duration_s": 8}`.
3. Regarde le terminal du simulateur : `commande pump_on -> executed`.
4. `GET /api/bacs/bac-sim-01/commands` : la commande est passée à `executed`.
5. Renvoie la même commande tout de suite : `rejected`, raison `already_watering`.
6. `GET /api/audit` : tout y est.

## 9. À toi

1. Crée un second compte **sans** `--role owner`, connecte-toi avec dans une
   fenêtre de navigation privée, et essaie d'envoyer une commande. Quel code
   reçois-tu, et pourquoi pas 401 ?
2. Trompe-toi 5 fois de mot de passe, puis donne le bon. Que se passe-t-il ?
   Retrouve ces tentatives dans `GET /api/audit`.
3. Arrête le simulateur (Ctrl+C) et envoie une commande. Pourquoi l'API
   refuse-t-elle au lieu d'envoyer quand même ?
4. Ouvre ta base (`greengrow_dev.db`) et regarde la table `users`. Ton mot de
   passe y est-il ?

## 10. Ce qui reste pour la suite

- **4b** : le tableau de bord web (page de connexion, graphiques, boutons de
  la pompe, mises à jour en direct) et les alertes Telegram.
- **Étape 5** : derrière un serveur web en HTTPS, l'adresse IP vue par l'API
  sera celle du serveur web ; il faudra lire la vraie adresse dans l'en-tête
  qu'il transmet, sinon la limite par IP compterait tout le monde ensemble.
- Changer son mot de passe depuis l'interface, et gérer les comptes depuis
  le tableau de bord, viendront avec le dashboard.
