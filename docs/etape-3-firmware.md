# Étape 3 — Le firmware du bac (ESP32)

Le bac a maintenant un cerveau. Un ESP32 lit les capteurs, décide seul
d'arroser, et parle au serveur en MQTT chiffré avec les règles de l'étape 2.

## 1. Comment le code est rangé

| Fichier (`firmware/greengrow_bac/`) | Rôle |
|---|---|
| `greengrow_bac.ino` | Le programme : capteurs, Wi-Fi, MQTT, boucle principale |
| `irrigation.h` | **La décision d'arroser** et tous les garde-fous. Aucun matériel dedans |
| `commands.h` | Le filtre des commandes (identifiant unique, expiration) |
| `config.h` | Broches et réglages. Rien de secret |
| `secrets.h` | Wi-Fi, identifiants MQTT, certificat de l'autorité. **Jamais sur GitHub** |
| `diagram.json` | Le montage pour Wokwi |

`irrigation.h` et `commands.h` ne contiennent aucune ligne propre à l'ESP32.
On leur donne l'heure et les mesures, ils répondent. C'est ce qui permet de
les tester automatiquement sur un PC (`firmware/tests/test_logic.cpp`,
26 scénarios) : « capteur en panne, donc la pompe reste éteinte » est vérifié
par GitHub à chaque push, sans brancher un seul fil.

## 2. La pompe ne dépend jamais du réseau

La décision d'arroser est prise **dans le bac**. Si le Wi-Fi tombe ou si le
serveur est en panne, la plante est arrosée quand même. Le serveur envoie
des seuils et reçoit des comptes rendus ; il ne tient pas le robinet.

Corollaire dans la boucle principale : une connexion TLS peut bloquer le
programme plusieurs secondes. Elle n'est donc **jamais tentée pendant que la
pompe tourne**, sinon la durée maximale ne serait plus surveillée.

## 3. La machine à états

```
IDLE ──(sol sec, réservoir ok, pause écoulée, quota ok)──▶ WATERING
WATERING ──(seuil haut atteint / durée max / réservoir vide)──▶ SOAKING
SOAKING ──(l'eau a pénétré : l'humidité a-t-elle monté ?)
     ├─ oui ──▶ IDLE
     └─ non ──▶ FAULT  (mode sécurité)
tout état ──(capteur du sol incohérent 3 fois de suite)──▶ FAULT
FAULT ──(commande reset_fault, après vérification humaine)──▶ IDLE
```

## 4. Les garde-fous, et ce que chacun empêche

| Garde-fou | Valeur (vrai bac / démo) | Ce qu'il empêche |
|---|---|---|
| Durée max d'un arrosage | 30 s / 10 s | Un bac noyé si le capteur ne voit pas l'eau arriver |
| Pause obligatoire | 10 min / 1 min | L'arrosage en rafale : l'eau met du temps à atteindre le capteur |
| Quota par 24 h | 6 arrosages | La boucle lente : un capteur faux qui redemande de l'eau toute la journée |
| Réservoir vide | arrêt immédiat | Une pompe qui tourne à sec et grille |
| Vérification après arrosage | hausse d'au moins 2 points | Tuyau débranché, pompe morte, capteur sorti de terre |
| Capteur incohérent | 3 lectures de suite | Décider d'arroser sur une mesure fausse |
| Limites absolues compilées | 120 s, 12 par jour | Une configuration dangereuse venue du réseau, même d'un serveur piraté |

En mode sécurité, la pompe ne démarre plus, **même sur commande manuelle**, et
le mode est mémorisé : redémarrer le bac ne l'efface pas. Mieux vaut une
plante qui a soif quelques heures qu'un bac noyé. Le bac prévient le serveur,
qui ouvre une alerte « Mode sécurité ».

## 5. Vérifier le certificat du broker

Dans `setup()` :

```cpp
tls.setCACert(CA_CERT);
```

L'ESP32 embarque le certificat de **ton** autorité et refuse tout broker dont
le certificat n'est pas signé par elle. `tls.setInsecure()` ferait
« marcher » la connexion en une ligne, mais accepterait aussi un imposteur :
il est interdit dans ce projet.

Vérifier un certificat demande de connaître la date (il a une période de
validité). Le bac se met donc à l'heure par NTP avant de se connecter.

## 6. Les commandes : identifiant et heure limite

MQTT en QoS 1 garantit qu'un message arrive « au moins une fois », donc
parfois deux. Et le broker garde les messages d'un bac hors ligne. Sans
précaution : tu cliques « arroser », le bac est déconnecté, il se reconnecte
trois heures plus tard et arrose en pleine nuit.

Chaque commande porte donc un `id` et un `expires_at` :

```json
{"id": "6f1c…", "type": "pump_on", "duration_s": 10, "expires_at": 1800000030}
```

Le bac refuse une commande expirée, déjà vue, valable plus de 5 minutes, ou
reçue alors qu'il ne connaît pas l'heure. Il répond toujours par un accusé
(`cmd_ack`, `executed` ou `rejected` avec la raison). L'envoi des commandes
depuis le dashboard arrive à l'étape 4 ; le bac est déjà prêt.

## 7. Côté serveur

- **Seuils** : le serveur publie les seuils du bac sur `…/config` (message
  retenu). `PATCH /api/bacs/{bac_id}` les modifie et les renvoie au bac. Le
  firmware les revérifie avant de les appliquer.
- **Journal** : les événements du bac sont rangés et visibles sur
  `GET /api/events/{bac_id}`.
- **Alertes** : mode sécurité et réservoir vide ouvrent une alerte, fermée
  quand le problème disparaît.

## 8. Lancer la simulation sur Wokwi

Préparation, une fois (broker et API démarrés comme à l'étape 2) :

```bash
python scripts/make_dev_certs.py      # ajoute host.wokwi.internal au certificat
docker compose restart mosquitto
python scripts/make_firmware_secrets.py --bac bac01 --nom "Bac pilote"
```

Le dernier script enregistre le bac et écrit `secrets.h` tout seul.

**Avec Wokwi pour VS Code (conseillé)** : installe les extensions *PlatformIO
IDE* et *Wokwi Simulator*, ouvre le dossier `firmware/greengrow_bac`, compile
(`pio run` ou le bouton ✓), puis lance « Wokwi: Start Simulator ». Dans la
simulation, `host.wokwi.internal` désigne ton PC : c'est ainsi que l'ESP32
simulé atteint ton broker local.

**Avec wokwi.com dans le navigateur** : crée un projet ESP32, copie-y
`greengrow_bac.ino` (comme `sketch.ino`), les fichiers `.h`, `diagram.json` et
`libraries.txt`. Pour atteindre ton PC, le navigateur a besoin de la
passerelle privée de Wokwi lancée sur ton PC.

> Ces deux chemins n'ont pas pu être essayés pendant le développement (Wokwi
> ne tourne pas dans mon environnement). Le code est compilé pour ESP32 par
> GitHub et sa logique est testée, mais la simulation elle-même et l'accès au
> broker local restent à confirmer chez toi. Dis-moi ce que tu observes.

### Ce que tu dois voir

1. Dans le moniteur série : `[mqtt] connecte en TLS, certificat du broker verifie`,
   puis une ligne `[mesure]` toutes les 10 secondes.
2. `GET /api/bacs` : `bac01` est `online`.
3. Descends le curseur d'humidité sous 45 % : la LED « POMPE » s'allume.
   Remonte-le au-dessus de 80 % : elle s'éteint.
4. Laisse le curseur bas : la pompe s'arrête seule après 10 s, puis 20 s plus
   tard le bac passe en **mode sécurité** (LED de la carte qui clignote),
   puisque « l'humidité n'a pas monté ». Une alerte apparaît sur
   `GET /api/alerts/bac01?active=true`.
5. Bascule l'interrupteur du réservoir : la pompe refuse de démarrer.
6. Pousse le curseur tout au bout : le capteur est jugé en panne.

Le mode sécurité se lève avec une commande `reset_fault` (bouton du
dashboard à l'étape 4). En attendant, sur Wokwi, il est gardé en mémoire d'un
lancement à l'autre seulement si la simulation conserve la mémoire flash.

## Limites connues

- Les mesures partent en QoS 0 (la bibliothèque PubSubClient ne publie pas en
  QoS 1). Une mesure perdue toutes les quelques heures est sans conséquence ;
  les événements, eux, sont gardés en file et renvoyés à la reconnexion.
- Le quota journalier repart à zéro si le bac redémarre. Le mode sécurité, lui, est mémorisé.
- `DEMO_MODE` vaut 1 dans `config.h` : à passer à 0 pour le vrai bac (étape 5),
  avec l'étalonnage du vrai capteur d'humidité.
