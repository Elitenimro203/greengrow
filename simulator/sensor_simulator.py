"""
GreenGrow — Simulateur de bac
==============================
Ce script se comporte comme le ferait l'ESP32 d'un vrai bac : il se connecte
au broker MQTT en TLS avec SON compte, annonce qu'il est en ligne, puis
publie des mesures. Il est soumis aux mêmes règles qu'un vrai bac.

Utilité : développer et tester tout le système sans matériel.

Lancement : python simulator/sensor_simulator.py
(le broker et l'API doivent tourner, voir README)
"""

import json
import os
import random
import ssl
import sys
import time
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

# ---- Configuration ----
API_URL = os.getenv("GREENGROW_API_URL", "http://localhost:8000")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
CA_FILE = os.getenv("MQTT_CA_FILE", "certs/ca.crt")
SITE = "abidjan"
BAC_ID = "bac-sim-01"
INTERVAL_SECONDS = 5

# Les identifiants MQTT du bac simulé sont rangés ici après l'enregistrement.
# Ce fichier est ignoré par Git : un mot de passe ne va jamais dans le dépôt.
CREDENTIALS_FILE = Path(__file__).parent / ".credentials.json"


def get_credentials() -> dict:
    """
    Retourne les identifiants MQTT du bac simulé.

    Au premier lancement, le simulateur demande à l'API d'enregistrer le bac :
    l'API crée son compte sur le broker et renvoie le mot de passe UNE fois.
    Si le bac existe déjà mais que le fichier a été perdu, on demande un
    nouveau mot de passe (l'ancien cesse de fonctionner).
    """
    if CREDENTIALS_FILE.exists():
        return json.loads(CREDENTIALS_FILE.read_text())

    headers = {"X-Admin-Key": ADMIN_API_KEY}
    try:
        response = httpx.post(
            f"{API_URL}/api/bacs",
            json={"bac_id": BAC_ID, "nom": "Bac simulé", "site": SITE},
            headers=headers,
            timeout=10.0,
        )
        if response.status_code == 201:
            creds = response.json()["mqtt"]
        elif response.status_code == 409:
            response = httpx.post(
                f"{API_URL}/api/bacs/{BAC_ID}/mqtt-credentials", headers=headers, timeout=10.0
            )
            response.raise_for_status()
            creds = response.json()
        else:
            response.raise_for_status()
    except httpx.ConnectError:
        sys.exit("❌ API non joignable. Lance d'abord : uvicorn backend.main:app --reload")
    except httpx.HTTPStatusError as exc:
        sys.exit(f"❌ Enregistrement refusé : {exc.response.status_code} {exc.response.text}")

    if creds is None:
        sys.exit("❌ L'API n'a pas créé de compte MQTT : vérifie MQTT_ENABLED=true dans .env")

    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    print(f"🆕 Bac {BAC_ID} enregistré, identifiants rangés dans {CREDENTIALS_FILE.name}")
    return creds


def generate_measurement() -> dict:
    """
    Une mesure réaliste pour une tomate. Remarque : il n'y a PAS de bac_id
    dans le message. Le serveur sait qui parle grâce au topic.
    """
    return {
        "timestamp": time.time(),
        "moisture_percent": round(random.uniform(35.0, 75.0), 1),
        "temperature_celsius": round(random.uniform(24.0, 32.0), 1),
        "humidity_air_percent": round(random.uniform(55.0, 85.0), 1),
        "pump_active": False,
        "source": "simulator",
    }


def main() -> None:
    creds = get_credentials()
    prefix = creds["topic_prefix"]  # greengrow/abidjan/bac-sim-01

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=creds["username"])
    client.username_pw_set(creds["username"], creds["password"])
    # Le simulateur vérifie le certificat du broker avec la CA, comme le fera
    # l'ESP32. S'il n'est pas signé par notre CA, la connexion est refusée.
    client.tls_set(ca_certs=CA_FILE, cert_reqs=ssl.CERT_REQUIRED)

    # Last Will : "si je disparais sans prévenir, publie offline à ma place".
    client.will_set(f"{prefix}/status", "offline", qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"❌ Connexion refusée par le broker : {reason_code}")
            return
        print("🔐 Connecté au broker en TLS")
        c.publish(f"{prefix}/status", "online", qos=1, retain=True)

    client.on_connect = on_connect

    print(f"🌱 GreenGrow Simulator — Bac : {BAC_ID}")
    print(f"📡 Broker : {creds['host']}:{creds['port']}  |  topic : {prefix}/telemetry")
    print("Ctrl+C pour arrêter\n")

    client.connect(creds["host"], creds["port"], keepalive=60)
    client.loop_start()
    try:
        while True:
            time.sleep(INTERVAL_SECONDS)
            measurement = generate_measurement()
            info = client.publish(f"{prefix}/telemetry", json.dumps(measurement), qos=1)
            state = "✅ publié" if info.rc == mqtt.MQTT_ERR_SUCCESS else "⚠️  en attente (déconnecté)"
            print(f"[{time.strftime('%H:%M:%S')}] {state} | {measurement}")
    except KeyboardInterrupt:
        # Arrêt propre : on annonce nous-mêmes qu'on part.
        client.publish(f"{prefix}/status", "offline", qos=1, retain=True).wait_for_publish(2)
        print("\n👋 Simulateur arrêté")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
