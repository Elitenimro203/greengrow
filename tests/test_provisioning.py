"""Création du compte MQTT à l'enregistrement d'un bac (broker simulé)."""

import pytest

from backend.config import get_settings
from backend.mqtt import dynsec


@pytest.fixture
def mqtt_on(monkeypatch):
    """Active MQTT et remplace l'appel au broker par un faux qui note ses appels."""
    calls = []

    def fake_provision(site, bac):
        calls.append((site, bac))
        return f"motdepasse-{len(calls)}"

    monkeypatch.setattr(get_settings(), "mqtt_enabled", True)
    monkeypatch.setattr(dynsec, "provision_bac", fake_provision)
    return calls


def test_creer_un_bac_renvoie_ses_identifiants_mqtt(client, mqtt_on):
    r = client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote", "site": "cocody"})
    assert r.status_code == 201
    assert r.json()["mqtt"] == {
        "host": "localhost",
        "port": 8883,
        "username": "bac01",
        "password": "motdepasse-1",
        "topic_prefix": "greengrow/cocody/bac01",
    }
    assert mqtt_on == [("cocody", "bac01")]


def test_le_mot_de_passe_n_est_jamais_relisible(client, mqtt_on):
    client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    assert "mqtt" not in client.get("/api/bacs").json()[0]


def test_si_le_broker_refuse_le_bac_n_est_pas_cree(client, monkeypatch):
    def broken(site, bac):
        raise dynsec.BrokerError("broker injoignable")

    monkeypatch.setattr(get_settings(), "mqtt_enabled", True)
    monkeypatch.setattr(dynsec, "provision_bac", broken)

    r = client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    assert r.status_code == 503
    assert client.get("/api/bacs").json() == []  # ni bac ni site à moitié créés


def test_renouveler_les_identifiants(client, mqtt_on):
    client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    r = client.post("/api/bacs/bac01/mqtt-credentials")
    assert r.status_code == 200
    assert r.json()["password"] == "motdepasse-2"


def test_renouveler_exige_la_cle(client, mqtt_on):
    client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    r = client.post("/api/bacs/bac01/mqtt-credentials", headers={"X-Admin-Key": "x"})
    assert r.status_code == 401
