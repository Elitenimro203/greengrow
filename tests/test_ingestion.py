"""
Ingestion MQTT : ce que le backend fait d'un message reçu.
On appelle handle_message directement, sans broker.
"""

import json

from sqlalchemy import select

from backend.models.entities import Alert, Bac, Reading
from backend.mqtt.ingestion import handle_message

TOPIC = "greengrow/abidjan/bac01/telemetry"


def measurement(**overrides) -> bytes:
    data = {
        "timestamp": 1_800_000_000,
        "moisture_percent": 60.0,
        "temperature_celsius": 28.0,
        "humidity_air_percent": 70.0,
        "pump_active": False,
    }
    data.update(overrides)
    return json.dumps(data).encode()


def count(db, table) -> int:
    return len(db.scalars(select(table)).all())


def test_une_mesure_valide_est_stockee(client, bac, db):
    assert handle_message(db, TOPIC, measurement()) == "stored"
    assert client.get("/api/readings/bac01").json()[0]["moisture_percent"] == 60.0


def test_l_identite_vient_du_topic_pas_du_message(client, bac, db):
    # bac01 essaie de se faire passer pour bac02 en l'écrivant dans le message.
    client.post("/api/bacs", json={"bac_id": "bac02", "nom": "Autre bac"})
    handle_message(db, TOPIC, measurement(bac_id="bac02", moisture_percent=11.0))

    assert client.get("/api/readings/bac02").json() == []
    assert client.get("/api/readings/bac01").json()[0]["moisture_percent"] == 11.0


def test_un_bac_inconnu_est_ignore(client, bac, db):
    outcome = handle_message(db, "greengrow/abidjan/bac-fantome/telemetry", measurement())
    assert outcome.startswith("ignored")
    assert count(db, Reading) == 0


def test_le_bon_bac_sur_le_mauvais_site_est_ignore(client, bac, db):
    outcome = handle_message(db, "greengrow/bouake/bac01/telemetry", measurement())
    assert outcome.startswith("ignored")
    assert count(db, Reading) == 0


def test_les_messages_invalides_sont_ignores_sans_planter(client, bac, db):
    for payload in (
        b"ceci n'est pas du JSON",
        b"[1, 2, 3]",
        measurement(moisture_percent=250),
        measurement(temperature_celsius="chaud"),
        b"\xff\xfe\x00",
        b"x" * 5000,
    ):
        assert handle_message(db, TOPIC, payload).startswith("ignored")
    assert count(db, Reading) == 0


def test_un_topic_hors_convention_est_ignore(client, bac, db):
    for topic in ("autre/abidjan/bac01/telemetry", "greengrow/abidjan/bac01", "greengrow/a/b/c/d"):
        assert handle_message(db, topic, measurement()).startswith("ignored")


def test_une_mesure_sans_heure_prend_l_heure_du_serveur(client, bac, db):
    payload = json.loads(measurement())
    del payload["timestamp"]
    assert handle_message(db, TOPIC, json.dumps(payload).encode()) == "stored"
    assert client.get("/api/readings/bac01").json()[0]["measured_at"] > "2026"


def test_les_alertes_fonctionnent_aussi_par_mqtt(client, bac, db):
    handle_message(db, TOPIC, measurement(moisture_percent=20))
    assert [a.type for a in db.scalars(select(Alert))] == ["moisture_low"]


def test_statut_en_ligne_puis_hors_ligne(client, bac, db):
    status = "greengrow/abidjan/bac01/status"
    assert client.get("/api/bacs").json()[0]["online"] is False

    assert handle_message(db, status, b"online") == "status"
    assert client.get("/api/bacs").json()[0]["online"] is True

    handle_message(db, status, b"offline")  # ce que publie le Last Will
    body = client.get("/api/bacs").json()[0]
    assert body["online"] is False
    assert body["last_seen_at"] is not None  # on sait quand il a été vu la dernière fois


def test_un_statut_invalide_est_ignore(client, bac, db):
    assert handle_message(db, "greengrow/abidjan/bac01/status", b"peut-etre").startswith("ignored")
    assert db.scalar(select(Bac)).online is False
