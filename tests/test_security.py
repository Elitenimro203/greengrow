"""Les actions sensibles exigent la clé d'administration."""

from tests.conftest import reading

BAC = {"bac_id": "bac01", "nom": "Bac pilote"}


def test_creer_un_bac_sans_cle_est_refuse(client):
    assert client.post("/api/bacs", json=BAC, headers={"X-Admin-Key": ""}).status_code == 401


def test_creer_un_bac_avec_une_mauvaise_cle_est_refuse(client):
    r = client.post("/api/bacs", json=BAC, headers={"X-Admin-Key": "devinette"})
    assert r.status_code == 401
    assert client.get("/api/bacs").json() == []


def test_injecter_une_mesure_sans_cle_est_refuse(client, bac):
    r = client.post("/api/readings", json=reading(), headers={"X-Admin-Key": "nope"})
    assert r.status_code == 401
    assert client.get("/api/readings/bac01").json() == []


def test_sans_cle_configuree_tout_est_ferme(client, monkeypatch):
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_api_key", "")
    assert client.post("/api/bacs", json=BAC).status_code == 503


def test_les_noms_des_comptes_du_systeme_sont_reserves(client):
    r = client.post("/api/bacs", json={"bac_id": "greengrow-backend", "nom": "Usurpateur"})
    assert r.status_code == 422
