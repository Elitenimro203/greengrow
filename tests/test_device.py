"""Événements envoyés par un bac, alertes associées et envoi des seuils."""

import json

from sqlalchemy import select

from backend.models.entities import Bac
from backend.mqtt import ingestion
from backend.mqtt.ingestion import config_payload, handle_message

EVENT = "greengrow/abidjan/bac01/event"


def event(event_type, **extra) -> bytes:
    return json.dumps({"type": event_type, "timestamp": 1_800_000_000, **extra}).encode()


def test_un_evenement_est_range_dans_le_journal(client, bac, db):
    assert handle_message(db, EVENT, event("watering_started", moisture_percent=41.5)) == "event"
    journal = client.get("/api/events/bac01").json()
    assert journal[0]["type"] == "watering_started"
    assert journal[0]["details"] == {"moisture_percent": 41.5}


def test_le_mode_securite_ouvre_une_alerte_puis_la_ferme(client, bac, db):
    handle_message(db, EVENT, event("fault_no_moisture_rise"))
    active = client.get("/api/alerts/bac01?active=true").json()
    assert [a["type"] for a in active] == ["device_fault"]
    assert "Mode sécurité" in active[0]["message"]

    handle_message(db, EVENT, event("fault_cleared"))
    assert client.get("/api/alerts/bac01?active=true").json() == []


def test_reservoir_vide_puis_rempli(client, bac, db):
    handle_message(db, EVENT, event("reservoir_empty"))
    handle_message(db, EVENT, event("watering_stopped_reservoir_empty"))  # même problème
    assert len(client.get("/api/alerts/bac01?active=true").json()) == 1

    handle_message(db, EVENT, event("reservoir_ok"))
    assert client.get("/api/alerts/bac01?active=true").json() == []


def test_un_arrosage_normal_n_ouvre_pas_d_alerte(client, bac, db):
    for t in ("watering_started", "watering_stopped_target", "cmd_ack"):
        handle_message(db, EVENT, event(t))
    assert client.get("/api/alerts/bac01").json() == []
    assert len(client.get("/api/events/bac01").json()) == 3


def test_les_evenements_invalides_sont_ignores(client, bac, db):
    for payload in (
        b"pas du json",
        b'{"pas_de_type": 1}',
        event("Type Avec Espaces"),
        event("x" * 80),
        b"[]",
    ):
        assert handle_message(db, EVENT, payload).startswith("ignored")
    assert client.get("/api/events/bac01").json() == []


def test_les_details_encombrants_ne_sont_pas_stockes(client, bac, db):
    handle_message(db, EVENT, event("cmd_ack", id="abc", result="executed", blob="x" * 500, nested={"a": 1}))
    assert client.get("/api/events/bac01").json()[0]["details"] == {"id": "abc", "result": "executed"}


def test_modifier_les_seuils_d_un_bac(client, bac, db):
    r = client.patch("/api/bacs/bac01", json={"moisture_low": 50, "moisture_high": 75})
    assert r.status_code == 200
    assert (r.json()["moisture_low"], r.json()["moisture_high"]) == (50.0, 75.0)
    assert json.loads(config_payload(db.scalar(select(Bac)))) == {"moisture_low": 50.0, "moisture_high": 75.0}


def test_les_seuils_que_le_firmware_refuserait_sont_refuses_par_l_api(client, bac):
    for bad in ({"moisture_low": 70, "moisture_high": 72}, {"moisture_high": 99}, {"moisture_low": 2}):
        assert client.patch("/api/bacs/bac01", json=bad).status_code == 422
    assert client.get("/api/bacs").json()[0]["moisture_low"] == 45.0


def test_modifier_un_bac_exige_la_cle(client, bac):
    r = client.patch("/api/bacs/bac01", json={"moisture_low": 50}, headers={"X-Admin-Key": "x"})
    assert r.status_code == 401


def test_les_nouveaux_seuils_sont_envoyes_au_bac(client, bac, monkeypatch):
    sent = []

    class FakeIngestion:
        def publish(self, topic, payload, retain=False):
            sent.append((topic, json.loads(payload), retain))

    monkeypatch.setattr(ingestion, "_running", FakeIngestion())
    client.patch("/api/bacs/bac01", json={"moisture_low": 50})
    assert sent == [("greengrow/abidjan/bac01/config", {"moisture_low": 50.0, "moisture_high": 80.0}, True)]
