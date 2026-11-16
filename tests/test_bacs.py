def test_creer_un_bac_applique_les_seuils_par_defaut(client):
    r = client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    assert r.status_code == 201
    body = r.json()
    assert body["bac_id"] == "bac01"
    assert (body["moisture_low"], body["moisture_high"], body["temp_max"]) == (45.0, 80.0, 35.0)


def test_un_bac_ne_peut_pas_etre_cree_deux_fois(client, bac):
    r = client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Doublon"})
    assert r.status_code == 409


def test_identifiant_de_bac_invalide_refuse(client):
    # Un "/" ou un "#" dans l'identifiant casserait les topics MQTT.
    r = client.post("/api/bacs", json={"bac_id": "bac/01#", "nom": "Piège"})
    assert r.status_code == 422


def test_seuils_incoherents_refuses(client):
    r = client.post(
        "/api/bacs",
        json={"bac_id": "bac02", "nom": "Bac", "moisture_low": 80, "moisture_high": 40},
    )
    assert r.status_code == 422


def test_lister_les_bacs(client, bac):
    client.post("/api/bacs", json={"bac_id": "bac02", "nom": "Second bac", "site": "yopougon"})
    assert [b["bac_id"] for b in client.get("/api/bacs").json()] == ["bac01", "bac02"]
