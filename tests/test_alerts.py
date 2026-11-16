from tests.conftest import reading

T0 = 1_800_000_000


def test_sol_sec_ouvre_une_alerte(client, bac):
    r = client.post("/api/readings", json=reading(moisture_percent=30))
    assert len(r.json()["alerts"]) == 1

    alerts = client.get("/api/alerts/bac01").json()
    assert [a["type"] for a in alerts] == ["moisture_low"]
    assert alerts[0]["resolved_at"] is None


def test_un_probleme_qui_dure_ne_cree_qu_une_seule_alerte(client, bac):
    for i in range(5):
        r = client.post("/api/readings", json=reading(timestamp=T0 + i, moisture_percent=30 - i))
    assert r.json()["alerts"] == []  # déjà signalé : pas de nouvelle alerte

    alerts = client.get("/api/alerts/bac01").json()
    assert len(alerts) == 1
    assert alerts[0]["last_value"] == 26.0  # mais la valeur suit la réalité


def test_retour_a_la_normale_ferme_l_alerte(client, bac):
    client.post("/api/readings", json=reading(timestamp=T0, moisture_percent=30))
    client.post("/api/readings", json=reading(timestamp=T0 + 60, moisture_percent=60))

    assert client.get("/api/alerts/bac01?active=true").json() == []
    assert client.get("/api/alerts/bac01").json()[0]["resolved_at"] is not None


def test_un_nouveau_probleme_rouvre_une_nouvelle_alerte(client, bac):
    for t, moisture in ((0, 30), (60, 60), (120, 30)):
        client.post("/api/readings", json=reading(timestamp=T0 + t, moisture_percent=moisture))
    assert len(client.get("/api/alerts/bac01").json()) == 2
    assert len(client.get("/api/alerts/bac01?active=true").json()) == 1


def test_chaleur_et_secheresse_sont_deux_alertes_distinctes(client, bac):
    r = client.post("/api/readings", json=reading(moisture_percent=30, temperature_celsius=38))
    assert len(r.json()["alerts"]) == 2


def test_les_seuils_sont_ceux_du_bac(client):
    # Un bac de laitue qui veut plus d'eau : 60 % est déjà trop sec pour lui.
    client.post("/api/bacs", json={"bac_id": "laitue01", "nom": "Laitue", "moisture_low": 65})
    r = client.post("/api/readings", json=reading(bac_id="laitue01", moisture_percent=60))
    assert len(r.json()["alerts"]) == 1
