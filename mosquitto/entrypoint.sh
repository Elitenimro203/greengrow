#!/bin/sh
# Démarrage du broker. Au tout premier lancement, on crée le fichier des
# comptes avec un unique compte administrateur (celui du fichier .env).
set -e

DYNSEC=/mosquitto/data/dynamic-security.json

if [ ! -f "$DYNSEC" ]; then
    if [ -z "$MQTT_ADMIN_PASSWORD" ]; then
        echo "ERREUR : MQTT_ADMIN_PASSWORD est vide. Renseigne-le dans .env." >&2
        exit 1
    fi
    echo "Premier démarrage : création du compte administrateur MQTT."
    mosquitto_ctrl dynsec init "$DYNSEC" "${MQTT_ADMIN_USER:-admin}" "$MQTT_ADMIN_PASSWORD"
fi

chown -R mosquitto:mosquitto /mosquitto/data
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
