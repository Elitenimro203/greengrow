"""Commandes de pompe : identifiant, heure limite, suivi de la réponse du bac."""

import json
import time
from datetime import timedelta

import pytest

from backend.models.entities import Bac, Command, utcnow
from backend.mqtt import ingestion
from backend.mqtt.ingestion import handle_message

EVENT = "greengrow/abidjan/bac01/event"


class FakeBroker:
    """Remplace la connexion au broker : retient ce qui aurait été publié."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, json.loads(payload), retain))


@pytest.fixture
def broker(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(ingestion, "_running", fake)
    return fake


@pytest.fixture
def online_bac(client, bac, db, broker):
    db.query(Bac).update({"online": True})
    db.commit()
    broker.published.clear()  # on oublie l'envoi des seuils fait à la création
    return bac


def ack(db, command_id, result="executed", topic=EVENT, **extra):
    payload = {"type": "cmd_ack", "id": command_id, "result": result, **extra}
    return handle_message(db, topic, json.dumps(payload).encode())


def test_une_commande_part_avec_un_identifiant_et_une_heure_limite(client, online_bac, broker):
    r = client.post("/api/bacs/bac01/commands", json={"type": "pump_on", "duration_s": 15})
    assert r.status_code == 202
    command = r.json()
    assert command["status"] == "sent"

    topic, payload, retain = broker.published[0]
    assert topic == "greengrow/abidjan/bac01/cmd"
    assert retain is False  # une commande ne doit jamais attendre sur le broker
    assert payload["id"] == command["id"]
    assert payload["type"] == "pump_on"
    assert payload["duration_s"] == 15
    # Valable 30 secondes, pas plus : le firmware refuse au-delà de 5 minutes.
    assert 25 <= payload["expires_at"] - time.time() <= 31


def test_deux_commandes_ont_des_identifiants_differents(client, online_bac, broker):
    a = client.post("/api/bacs/bac01/commands", json={"type": "pump_off"}).json()
    b = client.post("/api/bacs/bac01/commands", json={"type": "pump_off"}).json()
    assert a["id"] != b["id"]


def test_l_accuse_de_reception_du_bac_fait_avancer_la_commande(client, online_bac, db):
    command = client.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).json()
    assert ack(db, command["id"]) == "event"

    listed = client.get("/api/bacs/bac01/commands").json()[0]
    assert listed["status"] == "executed"
    assert listed["answered_at"] is not None


def test_un_refus_du_bac_est_garde_avec_sa_raison(client, online_bac, db):
    command = client.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).json()
    ack(db, command["id"], result="rejected", reason="reservoir_empty")

    listed = client.get("/api/bacs/bac01/commands").json()[0]
    assert (listed["status"], listed["reason"]) == ("rejected", "reservoir_empty")


def test_sans_reponse_la_commande_passe_a_expiree(client, online_bac, db):
    client.post("/api/bacs/bac01/commands", json={"type": "pump_on"})
    db.query(Command).update({"expires_at": utcnow() - timedelta(seconds=1)})
    db.commit()
    assert client.get("/api/bacs/bac01/commands").json()[0]["status"] == "expired"


def test_un_bac_ne_peut_pas_valider_la_commande_d_un_autre(client, online_bac, db):
    client.post("/api/bacs", json={"bac_id": "bac02", "nom": "Voisin"})
    command = client.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).json()

    ack(db, command["id"], topic="greengrow/abidjan/bac02/event")
    assert client.get("/api/bacs/bac01/commands").json()[0]["status"] == "sent"


def test_seule_la_premiere_reponse_compte(client, online_bac, db):
    command = client.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).json()
    ack(db, command["id"], result="rejected", reason="fault")
    ack(db, command["id"], result="executed")
    assert client.get("/api/bacs/bac01/commands").json()[0]["status"] == "rejected"


def test_un_accuse_pour_une_commande_inconnue_est_sans_effet(client, online_bac, db):
    assert ack(db, "00000000-0000-0000-0000-000000000000") == "event"
    assert ack(db, 12345) == "event"
    assert client.get("/api/bacs/bac01/commands").json() == []


def test_un_bac_hors_ligne_ne_recoit_pas_de_commande(client, bac, broker):
    broker.published.clear()
    r = client.post("/api/bacs/bac01/commands", json={"type": "pump_on"})
    assert r.status_code == 409
    assert broker.published == []


def test_sans_broker_la_commande_est_refusee(client, bac):
    assert client.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "explode"},
        {"type": "pump_on", "duration_s": 0},
        {"type": "pump_on", "duration_s": 3600},
        {},
    ],
)
def test_une_commande_invalide_est_refusee(client, online_bac, broker, payload):
    assert client.post("/api/bacs/bac01/commands", json=payload).status_code == 422
    assert broker.published == []


def test_pas_plus_de_six_commandes_par_minute_et_par_bac(client, online_bac, broker):
    for _ in range(6):
        assert client.post("/api/bacs/bac01/commands", json={"type": "pump_off"}).status_code == 202
    assert client.post("/api/bacs/bac01/commands", json={"type": "pump_off"}).status_code == 429
    assert len(broker.published) == 6


def test_chaque_commande_est_dans_le_journal_d_audit(client, online_bac):
    command = client.post("/api/bacs/bac01/commands", json={"type": "pump_on", "duration_s": 8}).json()
    entry = client.get("/api/audit").json()[0]
    assert entry["action"] == "command_sent"
    assert entry["target"] == "bac01"
    assert entry["details"] == {"id": command["id"], "type": "pump_on", "duration_s": 8}
