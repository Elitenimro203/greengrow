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


class SimulatedBac:
    """
    Un petit modèle de bac, pour que les courbes ressemblent à la réalité :
    le sol sèche lentement, remonte quand la pompe tourne, et le bac arrose
    tout seul quand le sol devient trop sec (comme le firmware).
    """

    DRYING_PER_SECOND = 0.07   # le sol perd ~4 points par minute (accéléré pour la démo)
    WATERING_PER_SECOND = 1.6  # la pompe en rend ~1,6 par seconde
    AUTO_START_BELOW = 43.0
    AUTO_STOP_ABOVE = 68.0

    def __init__(self) -> None:
        self.moisture = random.uniform(55.0, 65.0)
        self.temperature = random.uniform(27.0, 29.0)
        self.air = random.uniform(65.0, 75.0)
        self.last = time.time()

    def step(self, pump_active: bool) -> None:
        now = time.time()
        elapsed, self.last = now - self.last, now
        rate = self.WATERING_PER_SECOND if pump_active else -self.DRYING_PER_SECOND
        self.moisture = min(95.0, max(5.0, self.moisture + rate * elapsed + random.uniform(-0.2, 0.2)))
        # Température et air : une dérive lente, pas des sauts au hasard.
        self.temperature = min(34.0, max(23.0, self.temperature + random.uniform(-0.15, 0.15)))
        self.air = min(90.0, max(50.0, self.air + random.uniform(-0.6, 0.6)))

    def measurement(self, pump_active: bool) -> dict:
        """
        Remarque : il n'y a PAS de bac_id dans le message. Le serveur sait
        qui parle grâce au topic.
        """
        return {
            "timestamp": time.time(),
            "moisture_percent": round(self.moisture, 1),
            "temperature_celsius": round(self.temperature, 1),
            "humidity_air_percent": round(self.air, 1),
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

    def start(self, seconds: float) -> None:
        self.stop_at = time.time() + min(seconds, self.MAX_WATERING_S)

    def stop(self) -> None:
        self.stop_at = 0.0

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
            self.start(duration)
        elif kind == "pump_off":
            self.stop()
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
    bac = SimulatedBac()

    def publish_event(kind: str) -> None:
        event = {"type": kind, "timestamp": int(time.time()), "moisture_percent": round(bac.moisture, 1)}
        client.publish(f"{prefix}/event", json.dumps(event), qos=1)
        print(f"📣 événement : {kind}")

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
            if ack["result"] == "executed" and command.get("type") == "pump_on":
                publish_event("watering_started")
            elif ack["result"] == "executed" and command.get("type") == "pump_off":
                publish_event("watering_stopped_manual")

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
            was_active = pump.active
            bac.step(was_active)
            # Arrosage automatique, comme le firmware : trop sec -> la pompe
            # démarre ; assez humide -> elle s'arrête.
            if not was_active and bac.moisture < bac.AUTO_START_BELOW:
                pump.start(pump.MAX_WATERING_S)
                publish_event("watering_started")
            elif was_active and bac.moisture > bac.AUTO_STOP_ABOVE:
                pump.stop()
                publish_event("watering_stopped_target")
            measurement = bac.measurement(pump.active)
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
