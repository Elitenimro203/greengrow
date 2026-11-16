"""
Tests de sécurité contre le VRAI broker.

Ils ne tournent que si on le demande, broker démarré (docker compose up -d) :

    GREENGROW_BROKER_TEST=1 pytest tests/test_broker_real.py -v

Chaque test joue un attaquant et vérifie que le broker le bloque. C'est la
preuve que la sécurité ne repose pas sur notre bonne volonté mais sur la
configuration du broker.
"""

import os
import socket
import ssl
import threading
import time

import paho.mqtt.client as mqtt
import pytest
from dotenv import dotenv_values

pytestmark = pytest.mark.skipif(
    os.getenv("GREENGROW_BROKER_TEST") != "1",
    reason="test contre le vrai broker : GREENGROW_BROKER_TEST=1 pour le lancer",
)

HOST, PORT, CA = "localhost", 8883, "certs/ca.crt"


@pytest.fixture(scope="module")
def accounts():
    """Crée deux bacs sur le broker avec le compte admin du fichier .env."""
    from backend.config import get_settings
    from backend.mqtt import dynsec

    env = dotenv_values(".env")
    settings = get_settings()
    settings.mqtt_admin_password = env["MQTT_ADMIN_PASSWORD"]
    settings.mqtt_backend_password = env["MQTT_BACKEND_PASSWORD"]
    dynsec.ensure_backend_account()
    return {
        "bac-test-a": dynsec.provision_bac("abidjan", "bac-test-a"),
        "bac-test-b": dynsec.provision_bac("abidjan", "bac-test-b"),
        "backend": (settings.mqtt_backend_user, settings.mqtt_backend_password),
    }


def connect(username=None, password=None, ca=CA):
    """Se connecte et retourne (client, code de retour de connexion)."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-{time.time_ns()}")
    if username:
        client.username_pw_set(username, password)
    client.tls_set(ca_certs=ca, cert_reqs=ssl.CERT_REQUIRED)
    connected = threading.Event()
    result = {}

    def on_connect(c, userdata, flags, reason_code, properties):
        result["code"] = reason_code
        connected.set()

    client.on_connect = on_connect
    client.connect(HOST, PORT)
    client.loop_start()
    assert connected.wait(5), "pas de réponse du broker"
    return client, result["code"]


class Listener:
    """Le backend qui écoute tout, pour voir ce qui passe vraiment."""

    def __init__(self, accounts):
        self.received = []
        self.client, code = connect(*accounts["backend"])
        assert not code.is_failure
        subscribed = threading.Event()
        self.client.on_subscribe = lambda *a: subscribed.set()
        self.client.on_message = lambda c, u, m: self.received.append((m.topic, m.payload))
        self.client.subscribe("greengrow/#", qos=1)
        assert subscribed.wait(5)

    def topics(self, wait=1.0):
        time.sleep(wait)
        # On ne regarde que les bacs de test (d'autres bacs peuvent avoir un statut retenu).
        return [t for t, _ in self.received if "bac-test-" in t]


def test_le_port_en_clair_est_ferme():
    with pytest.raises(OSError):
        socket.create_connection((HOST, 1883), timeout=2)


def test_connexion_anonyme_refusee():
    client, code = connect()
    assert code.is_failure
    client.loop_stop()


def test_mauvais_mot_de_passe_refuse(accounts):
    client, code = connect("bac-test-a", "pas-le-bon")
    assert code.is_failure
    client.loop_stop()


def test_un_client_refuse_un_broker_dont_il_ne_connait_pas_la_ca(tmp_path):
    # On donne au client une AUTRE autorité : pour lui, notre broker est un imposteur.
    import subprocess
    import sys

    other = tmp_path / "autre-ca.crt"
    code = (
        "import sys; sys.path.insert(0, 'scripts'); import make_dev_certs as m;"
        "from cryptography.hazmat.primitives import serialization as s;"
        f"open(r'{other}','wb').write(m.make_ca()[1].public_bytes(s.Encoding.PEM))"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.tls_set(ca_certs=str(other), cert_reqs=ssl.CERT_REQUIRED)
    with pytest.raises(ssl.SSLCertVerificationError):
        client.connect(HOST, PORT)


def test_un_bac_publie_sur_son_topic(accounts):
    listener = Listener(accounts)
    bac, code = connect("bac-test-a", accounts["bac-test-a"])
    assert not code.is_failure
    bac.publish("greengrow/abidjan/bac-test-a/telemetry", "{}", qos=1).wait_for_publish(3)
    assert "greengrow/abidjan/bac-test-a/telemetry" in listener.topics()


def test_un_bac_ne_peut_pas_publier_a_la_place_d_un_autre(accounts):
    listener = Listener(accounts)
    bac, _ = connect("bac-test-a", accounts["bac-test-a"])
    for topic in (
        "greengrow/abidjan/bac-test-b/telemetry",  # usurper le voisin
        "greengrow/abidjan/bac-test-b/status",
        "greengrow/abidjan/bac-test-a/cmd",        # s'envoyer une commande
        "greengrow/abidjan/bac-test-b/cmd",        # commander la pompe du voisin
    ):
        bac.publish(topic, "pirate", qos=1)
    assert listener.topics() == []  # le broker a tout jeté


def test_un_bac_ne_peut_pas_espionner_les_autres(accounts):
    spy_received = []
    spy, _ = connect("bac-test-a", accounts["bac-test-a"])
    spy.on_message = lambda c, u, m: spy_received.append(m.topic)
    spy.subscribe([("greengrow/#", 1), ("greengrow/abidjan/bac-test-b/telemetry", 1), ("#", 1)])
    time.sleep(0.5)

    other, _ = connect("bac-test-b", accounts["bac-test-b"])
    other.publish("greengrow/abidjan/bac-test-b/telemetry", "secret", qos=1).wait_for_publish(3)
    time.sleep(1)
    assert spy_received == []


def test_un_bac_recoit_les_commandes_qui_lui_sont_destinees(accounts):
    received = []
    bac, _ = connect("bac-test-a", accounts["bac-test-a"])
    bac.on_message = lambda c, u, m: received.append(m.topic)
    bac.subscribe("greengrow/abidjan/bac-test-a/cmd", qos=1)
    time.sleep(0.5)

    backend, _ = connect(*accounts["backend"])
    backend.publish("greengrow/abidjan/bac-test-a/cmd", "{}", qos=1).wait_for_publish(3)
    backend.publish("greengrow/abidjan/bac-test-b/cmd", "{}", qos=1).wait_for_publish(3)
    time.sleep(1)
    assert received == ["greengrow/abidjan/bac-test-a/cmd"]


def test_un_bac_ne_peut_pas_administrer_le_broker(accounts):
    # Tenter de se créer un compte tout-puissant via le topic d'administration.
    listener_received = []
    bac, _ = connect("bac-test-a", accounts["bac-test-a"])
    bac.on_message = lambda c, u, m: listener_received.append(m.payload)
    bac.subscribe("$CONTROL/dynamic-security/v1/response", qos=1)
    bac.publish(
        "$CONTROL/dynamic-security/v1",
        '{"commands":[{"command":"createClient","username":"pirate","password":"x"}]}',
        qos=1,
    )
    time.sleep(1)
    assert listener_received == []
    client, code = connect("pirate", "x")
    assert code.is_failure
    client.loop_stop()
