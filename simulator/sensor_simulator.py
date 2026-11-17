"""
GreenGrow — Simulateur de bac
==============================
Ce script se comporte comme le ferait l'ESP32 d'un vrai bac : il se connecte
au broker MQTT en TLS avec SON compte, annonce qu'il est en ligne, puis
publie des mesures et répond aux commandes de pompe. Il est soumis aux mêmes
règles qu'un vrai bac.

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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.api_session import open_session  # noqa: E402

load_dotenv()

# ---- Configuration ----
API_URL = os.getenv("GREENGROW_API_URL", "http://localhost:8000")
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

    # Enregistrer un bac est réservé au propriétaire : le simulateur te
    # demande donc de te connecter (une seule fois, au premier lancement).
    api = open_session(API_URL)
    creds = None
    try:
        response = api.post("/api/bacs", json={"bac_id": BAC_ID, "nom": "Bac simulé", "site": SITE})
        if response.status_code == 201:
            creds = response.json()["mqtt"]
        elif response.status_code == 409:
            response = api.post(f"/api/bacs/{BAC_ID}/mqtt-credentials")
            response.raise_for_status()
            creds = response.json()
        else:
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        sys.exit(f"❌ Enregistrement refusé : {exc.response.status_code} {exc.response.text}")

    if creds is None:
        sys.exit("❌ L'API n'a pas créé de compte MQTT : vérifie MQTT_ENABLED=true dans .env")

    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    print(f"🆕 Bac {BAC_ID} enregistré, identifiants rangés dans {CREDENTIALS_FILE.name}")
    return creds


def generate_measurement(pump_active: bool = False) -> dict:
    """
    Une mesure réaliste pour une tomate. Remarque : il n'y a PAS de bac_id
    dans le message. Le serveur sait qui parle grâce au topic.
    """
    return {
        "timestamp": time.time(),
        "moisture_percent": round(random.uniform(35.0, 75.0), 1),
        "temperature_celsius": round(random.uniform(24.0, 32.0), 1),
        "humidity_air_percent": round(random.uniform(55.0, 85.0), 1),
        "pump_active": pump_active,
        "source": "simulator",
    }


class SimulatedPump:
    """
    La pompe du bac simulé, avec le même filtre de commandes que le vrai
    firmware (commands.h) : identifiant jamais vu + heure limite non dépassée.
    """

    MAX_WATERING_S = 20

    def __init__(self) -> None:
        self.stop_at = 0.0
        self.seen_ids: list[str] = []

    @property
    def active(self) -> bool:
        return time.time() < self.stop_at

    def handle(self, command: dict) -> dict | None:
        """Traite une commande et retourne l'accusé de réception à publier."""
        command_id = command.get("id")
        if not isinstance(command_id, str) or not 0 < len(command_id) <= 36:
            return None
        ack = {"type": "cmd_ack", "id": command_id, "timestamp": int(time.time())}
        expires_at = command.get("expires_at", 0)
        if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
            return ack | {"result": "rejected", "reason": "expired"}
        if expires_at - time.time() > 300:
            return ack | {"result": "rejected", "reason": "expiry_too_far"}
        if command_id in self.seen_ids:
            return ack | {"result": "rejected", "reason": "duplicate"}
        self.seen_ids = (self.seen_ids + [command_id])[-16:]

        kind = command.get("type")
        if kind == "pump_on":
            if self.active:
                return ack | {"result": "rejected", "reason": "already_watering"}
            duration = command.get("duration_s", 10)
            if not isinstance(duration, (int, float)) or duration <= 0:
                duration = 10
            self.stop_at = time.time() + min(duration, self.MAX_WATERING_S)
        elif kind == "pump_off":
            self.stop_at = 0.0
        elif kind != "reset_fault":
            return ack | {"result": "rejected", "reason": "unknown_type"}
        return ack | {"result": "executed"}


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
        c.subscribe(f"{prefix}/cmd", qos=1)

    pump = SimulatedPump()

    def on_message(c, userdata, message):
        try:
            command = json.loads(message.payload)
        except ValueError:
            return
        if not isinstance(command, dict):
            return
        ack = pump.handle(command)
        if ack is not None:
            c.publish(f"{prefix}/event", json.dumps(ack), qos=1)
            print(f"🎛️  commande {command.get('type')} -> {ack['result']} {ack.get('reason', '')}")

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"🌱 GreenGrow Simulator — Bac : {BAC_ID}")
    print(f"📡 Broker : {creds['host']}:{creds['port']}  |  topic : {prefix}/telemetry")
    print("Ctrl+C pour arrêter\n")

    client.connect(creds["host"], creds["port"], keepalive=60)
    client.loop_start()
    try:
        while True:
            time.sleep(INTERVAL_SECONDS)
            measurement = generate_measurement(pump.active)
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
