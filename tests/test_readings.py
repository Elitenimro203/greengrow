from tests.conftest import reading


def test_une_mesure_valide_est_stockee(client, bac):
    r = client.post("/api/readings", json=reading())
    assert r.status_code == 200
    assert r.json() == {"status": "stored", "bac_id": "bac01", "alerts": []}

    stored = client.get("/api/readings/bac01").json()
    assert len(stored) == 1
    assert stored[0]["moisture_percent"] == 60.0


def test_mesure_d_un_bac_inconnu_refusee(client):
    r = client.post("/api/readings", json=reading(bac_id="bac-fantome"))
    assert r.status_code == 404
    assert client.get("/api/bacs").json() == []  # aucun bac créé en douce


def test_valeur_impossible_refusee(client, bac):
    r = client.post("/api/readings", json=reading(moisture_percent=150))
    assert r.status_code == 422


def test_les_mesures_sortent_de_la_plus_recente_a_la_plus_ancienne(client, bac):
    for t in (100, 300, 200):
        client.post("/api/readings", json=reading(timestamp=1_800_000_000 + t, moisture_percent=t / 10))
    values = [m["moisture_percent"] for m in client.get("/api/readings/bac01?limit=2").json()]
    assert values == [30.0, 20.0]


def test_limite_bornee(client, bac):
    assert client.get("/api/readings/bac01?limit=999999").status_code == 422
