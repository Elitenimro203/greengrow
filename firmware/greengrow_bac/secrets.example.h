// ============================================================
// GreenGrow — Secrets du bac (MODÈLE)
// ============================================================
// Le vrai fichier s'appelle secrets.h et n'est JAMAIS envoyé sur GitHub
// (il est dans .gitignore). Pour le créer automatiquement :
//
//     python scripts/make_firmware_secrets.py --bac bac01
//
// ou copie ce modèle en secrets.h et remplis-le à la main.
// ============================================================
#pragma once

#define WIFI_SSID "Wokwi-GUEST"   // le Wi-Fi simulé de Wokwi, sans mot de passe
#define WIFI_PASSWORD ""

// Adresse du broker. Sur Wokwi, "host.wokwi.internal" désigne TON PC.
// Le nom doit figurer dans le certificat du broker (make_dev_certs.py le met).
#define MQTT_HOST "host.wokwi.internal"
#define MQTT_PORT 8883

// Identifiants MQTT du bac, donnés une seule fois à son enregistrement.
#define MQTT_USERNAME "bac01"
#define MQTT_PASSWORD "a-remplacer"
#define TOPIC_PREFIX "greengrow/abidjan/bac01"

// Certificat de l'autorité (contenu de certs/ca.crt). Il n'est pas secret,
// mais il est propre à ton installation. C'est lui qui permet à l'ESP32 de
// vérifier qu'il parle au vrai broker.
static const char CA_CERT[] PROGMEM = R"PEM(
-----BEGIN CERTIFICATE-----
colle ici le contenu de certs/ca.crt
-----END CERTIFICATE-----
)PEM";
