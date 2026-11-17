# Étape 4b — Le tableau de bord, et les alertes sur ton téléphone

Jusqu'ici GreenGrow se pilotait depuis `/docs`, un outil de développeur. Cette
étape lui donne un visage : une page web que tu peux montrer, sur ordinateur
comme sur téléphone, et un message Telegram quand quelque chose ne va pas.

## 1. Essayer

```bash
git pull
docker compose up -d
uvicorn backend.main:app --reload
python simulator/sensor_simulator.py
```

Ouvre **http://localhost:8000** et connecte-toi avec ton compte. Aucune
nouvelle dépendance, aucune migration.

Le simulateur a changé : au lieu de valeurs tirées au hasard, il imite un
vrai bac. Le sol sèche peu à peu, la pompe démarre toute seule sous 43 %,
s'arrête vers 68 %, et le sol remonte. En quelques minutes tu vois un cycle
complet sur le graphique (le séchage est accéléré pour la démonstration).

## 2. Ce que montre la page

De haut en bas, du plus important au détail :

1. **Une phrase** : « Tout va bien », « Arrosage en cours », une alerte, ou
   « Bac hors ligne ». On doit comprendre l'état du bac en une seconde.
2. **L'humidité du sol**, le chiffre qui compte, avec une jauge qui le situe
   dans la **zone idéale** (entre tes deux seuils), puis sa courbe. Les
   bandes bleues marquent les moments où la pompe tournait.
3. **Température, humidité de l'air, pompe.**
4. **Arrosage manuel** (propriétaire seulement), **alertes en cours**,
   **activité récente** (commandes et événements du bac, dans l'ordre).

Passe la souris (ou le doigt) sur une courbe pour lire une valeur précise.
Le bouton en haut à droite bascule entre thème clair et thème sombre. Sur
téléphone, tout passe sur une colonne et l'arrosage remonte sous les chiffres.

## 3. Comment c'est fait : trois fichiers, zéro bibliothèque

```
backend/web/
├── index.html          la structure de la page (aucune donnée dedans)
└── static/
    ├── style.css       l'apparence (couleurs, tailles, mobile, thème sombre)
    ├── app.js          le comportement (appels à l'API, graphiques)
    └── theme.js        applique le thème choisi avant le premier affichage
```

C'est la même application FastAPI qui sert la page **et** l'API
(`backend/main.py`). Un seul programme à lancer, un seul à déployer.

**Pourquoi pas React ou une bibliothèque de graphiques ?** Parce que tu veux
comprendre ton projet de bout en bout. Ici, ce que tu lis dans `app.js` est
exactement ce que le navigateur exécute : pas d'étape de compilation, pas de
dossier `node_modules`, rien à télécharger depuis un autre site. Les
graphiques sont dessinés en SVG par une fonction d'une centaine de lignes
(`drawChart`). Le jour où le tableau de bord grossit vraiment, passer à un
framework restera possible ; l'API, elle, ne changera pas.

### La page ne contient aucune donnée

`GET /` renvoie la même page à tout le monde, connecté ou non. Elle est vide.
C'est `app.js` qui demande ensuite les données à l'API, et l'API exige la
session (étape 4a). Le déroulé :

1. `app.js` appelle `GET /api/auth/me`.
2. Réponse 401 → il affiche le formulaire de connexion.
3. Réponse 200 → il affiche le tableau de bord et charge les bacs.

Les boutons d'arrosage sont cachés pour un lecteur, mais ce n'est que du
confort : s'il appelait l'API à la main, elle répondrait 403. **La sécurité
est dans le serveur, jamais dans la page.**

### « En direct » : le polling

Toutes les 5 secondes, la page redemande l'état à l'API. C'est le *polling* :
simple, robuste, et suffisant quand un bac envoie une mesure par minute. La
page s'arrête de demander quand l'onglet est caché. Juste après une commande,
elle redemande plus vite pour afficher la réponse du bac sans attendre.

L'autre approche (le serveur *pousse* les nouveautés, avec SSE ou WebSocket)
est plus réactive mais demande une connexion ouverte en permanence par
visiteur. On y passera si le besoin apparaît.

## 4. La sécurité côté navigateur

### Le XSS, et pourquoi `textContent`

Imagine qu'un bac s'appelle `<script>voler()</script>`. Si la page insérait
ce nom tel quel dans son HTML, le navigateur **exécuterait** le script, avec
ta session. C'est le XSS (*Cross-Site Scripting*).

Première barrière : `app.js` n'écrit jamais du texte venu du serveur avec
`innerHTML`. Il utilise `textContent`, qui affiche toujours du texte, jamais
du code. Un test vérifie que `innerHTML` n'apparaît nulle part.

### La politique de sécurité du contenu (CSP)

Deuxième barrière, au cas où la première aurait un trou. Le serveur envoie
avec chaque page l'en-tête :

```
Content-Security-Policy: default-src 'self'; ...
```

Traduction : « navigateur, ne charge et n'exécute **que** ce qui vient de mon
propre serveur ». Un script écrit directement dans la page est refusé, un
script venu d'un autre site aussi, et la page ne peut pas envoyer de données
ailleurs. C'est pour ça que tout le JavaScript est dans des fichiers séparés
et qu'aucune police ni bibliothèque ne vient d'un autre site.

Autres en-têtes posés par `security_headers` dans `backend/main.py` :

| En-tête | Effet |
|---|---|
| `X-Frame-Options: DENY` | La page ne peut pas être affichée dans un cadre d'un autre site (piège où l'on te fait cliquer sur un bouton invisible). |
| `X-Content-Type-Options: nosniff` | Le navigateur ne « devine » pas le type d'un fichier. |
| `Cache-Control: no-store` sur `/api/` | Tes données ne restent pas dans un cache. |
| `Strict-Transport-Security` (production) | Le navigateur n'utilisera plus que HTTPS. |

En production (`APP_ENV=production`), `/docs` est désactivé : cette page
décrit toute l'API, c'est un outil de développement.

## 5. Les alertes Telegram

Fichier : `backend/services/notify.py`.

Quand une alerte **s'ouvre** (sol trop sec, température trop haute, mode
sécurité, réservoir vide), le serveur envoie un message. Comme les alertes
sont dédupliquées depuis l'étape 1 (une alerte par problème), ton téléphone
sonne une fois, pas à chaque mesure.

### Le brancher

1. Dans Telegram, ouvre **@BotFather**, envoie `/newbot`, choisis un nom.
   Il te donne un **jeton**. Mets-le dans `.env` : `TELEGRAM_BOT_TOKEN=...`
2. Ouvre la conversation avec ton bot et envoie-lui un message quelconque.
3. `python scripts/telegram_setup.py` : il affiche l'identifiant de la
   conversation. Mets-le dans `.env` : `TELEGRAM_CHAT_ID=...`
4. Relance `python scripts/telegram_setup.py` : tu reçois un message d'essai.
5. Redémarre l'API.

Sans ces deux lignes, il n'y a simplement pas de notification.

### Trois précautions

- **Le jeton est un secret.** Qui le possède peut parler à la place de ton
  bot. Il reste dans `.env` (jamais dans Git), et il n'est jamais écrit dans
  les journaux : la bibliothèque HTTP journalise normalement chaque adresse
  appelée, et celle de Telegram contient le jeton, donc ce journal est coupé.
- **L'envoi ne bloque rien.** Il part dans un fil d'exécution séparé. Si
  Telegram est lent ou en panne, les mesures continuent d'être enregistrées.
- **Après le commit.** Le message part une fois l'alerte réellement
  enregistrée en base, jamais avant.

## 6. Ce qui a été vérifié, et ce qui ne l'a pas été

- Vérifié dans un vrai navigateur (Chromium), avec le broker, l'API et le
  simulateur : connexion, affichage, commande d'arrosage suivie jusqu'à
  « exécutée », refus « un arrosage est déjà en cours », thème sombre,
  largeur de téléphone, aucune erreur dans la console avec la CSP active.
- **Pas vérifié : l'envoi réel vers Telegram.** Je n'ai pas de bot. Les
  tests remplacent Telegram par un faux ; le format de l'appel suit la
  documentation de l'API Bot. C'est `telegram_setup.py` qui te dira si ça
  marche chez toi.
- Pas vérifié sur Safari ni Firefox.

## 7. À toi

1. Dans `style.css`, change `--brand` (le vert) pour une autre couleur, dans
   le bloc clair **et** dans les deux blocs sombres. Recharge la page.
2. Dans `app.js`, trouve `REFRESH_MS` et passe-le à 2000. Que gagnes-tu, et
   qu'est-ce que ça coûte au serveur s'il y a 100 visiteurs ?
3. Ouvre les outils de développement du navigateur (F12), onglet Console, et
   tape `document.body.appendChild(Object.assign(document.createElement("script"), {src: "https://example.com/x.js"}))`.
   Que dit le navigateur ? Quelle règle a parlé ?
4. Connecte-toi avec un compte lecteur. Que manque-t-il sur la page ?

## 8. Et après

Étape 5 : mettre tout ça en ligne (serveur, nom de domaine, HTTPS,
PostgreSQL) et brancher le vrai bac.
