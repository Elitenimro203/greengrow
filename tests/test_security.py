"""Sans connexion on n'entre pas ; avec le mauvais rôle on ne modifie rien."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.entities import AuditLog, User, UserSession
from backend.services import passwords
from tests.conftest import OWNER, VIEWER, login, reading

BAC = {"bac_id": "bac01", "nom": "Bac pilote"}


# ---------- Sans connexion ----------

@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/bacs"),
        ("POST", "/api/bacs"),
        ("PATCH", "/api/bacs/bac01"),
        ("POST", "/api/bacs/bac01/mqtt-credentials"),
        ("POST", "/api/bacs/bac01/commands"),
        ("GET", "/api/bacs/bac01/commands"),
        ("POST", "/api/readings"),
        ("GET", "/api/readings/bac01"),
        ("GET", "/api/alerts/bac01"),
        ("GET", "/api/events/bac01"),
        ("GET", "/api/audit"),
        ("GET", "/api/auth/me"),
    ],
)
def test_sans_connexion_toute_l_api_est_fermee(anonymous, method, path):
    assert anonymous.request(method, path, json={}).status_code == 401


def test_toutes_les_routes_de_l_api_sont_protegees(anonymous):
    """Filet de sécurité : une route ajoutée plus tard sans protection fait échouer ce test."""
    public = {"/api/auth/login", "/api/auth/logout"}
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/") or path in public:
            continue
        for method in methods:
            url = path.replace("{bac_id}", "bac01")
            assert anonymous.request(method.upper(), url, json={}).status_code == 401, (method, path)


def test_un_inconnu_ne_peut_pas_savoir_si_un_bac_existe(client, bac):
    stranger = TestClient(app)
    assert stranger.get("/api/readings/bac01").status_code == 401
    assert stranger.get("/api/readings/bac-inexistant").status_code == 401


def test_la_page_de_sante_reste_publique(anonymous):
    assert anonymous.get("/health").status_code == 200


# ---------- Connexion ----------

def test_connexion_puis_deconnexion(anonymous):
    r = anonymous.post("/api/auth/login", json=OWNER)
    assert r.status_code == 200
    assert r.json() == {"email": OWNER["email"], "nom": "Propriétaire", "role": "owner"}
    assert anonymous.get("/api/auth/me").json()["role"] == "owner"

    assert anonymous.post("/api/auth/logout").status_code == 204
    assert anonymous.get("/api/auth/me").status_code == 401


def test_le_cookie_de_session_est_protege(anonymous):
    cookie = anonymous.post("/api/auth/login", json=OWNER).headers["set-cookie"].lower()
    assert "httponly" in cookie  # illisible par JavaScript
    assert "samesite=strict" in cookie  # pas envoyé depuis un autre site


def test_en_production_le_cookie_ne_voyage_qu_en_https(anonymous, monkeypatch):
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    cookie = anonymous.post("/api/auth/login", json=OWNER).headers["set-cookie"].lower()
    assert "secure" in cookie


def test_mauvais_mot_de_passe_et_compte_inconnu_donnent_la_meme_reponse(anonymous):
    wrong = anonymous.post("/api/auth/login", json={**OWNER, "password": "pas-le-bon-mot"})
    unknown = anonymous.post(
        "/api/auth/login", json={"email": "personne@greengrow.test", "password": "pas-le-bon-mot"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_l_email_ne_tient_pas_compte_des_majuscules(anonymous):
    r = anonymous.post("/api/auth/login", json={**OWNER, "email": "  Proprio@GreenGrow.test "})
    assert r.status_code == 200


def test_un_faux_cookie_ne_donne_aucun_acces(anonymous):
    anonymous.cookies.set("greengrow_session", "jeton-invente")
    assert anonymous.get("/api/bacs").status_code == 401


def test_apres_deconnexion_l_ancien_jeton_ne_vaut_plus_rien(anonymous):
    login(anonymous)
    stolen = anonymous.cookies.get("greengrow_session")
    anonymous.post("/api/auth/logout")

    thief = TestClient(app)
    thief.cookies.set("greengrow_session", stolen)
    assert thief.get("/api/bacs").status_code == 401


def test_une_session_perimee_est_refusee(client, db):
    from datetime import timedelta

    from backend.models.entities import utcnow

    db.query(UserSession).update({"expires_at": utcnow() - timedelta(seconds=1)})
    db.commit()
    assert client.get("/api/bacs").status_code == 401


def test_un_compte_desactive_perd_l_acces_immediatement(client, db):
    db.query(User).filter(User.email == OWNER["email"]).update({"active": False})
    db.commit()
    assert client.get("/api/bacs").status_code == 401
    assert TestClient(app).post("/api/auth/login", json=OWNER).status_code == 401


def test_la_base_ne_contient_ni_mot_de_passe_ni_jeton(client, db):
    user = db.query(User).filter(User.email == OWNER["email"]).one()
    assert OWNER["password"] not in user.password_hash
    assert user.password_hash.startswith("scrypt$")
    assert passwords.verify_password(OWNER["password"], user.password_hash)
    assert not passwords.verify_password("autre-chose-42", user.password_hash)

    token = client.cookies.get("greengrow_session")
    assert db.query(UserSession).filter(UserSession.token_hash == token).count() == 0


def test_un_mot_de_passe_trop_court_est_refuse_a_la_creation(db_session_factory):
    from backend.services import auth

    with pytest.raises(ValueError):
        auth.create_user(db_session_factory(), "a@b.test", "A", "court", "owner")


# ---------- Anti-devinette ----------

def test_cinq_mots_de_passe_faux_bloquent_le_compte(anonymous):
    for _ in range(5):
        r = anonymous.post("/api/auth/login", json={**OWNER, "password": "essai-au-hasard"})
        assert r.status_code == 401
    # Même le BON mot de passe est maintenant refusé, le temps de la fenêtre.
    r = anonymous.post("/api/auth/login", json=OWNER)
    assert r.status_code == 429
    assert "retry-after" in r.headers
    # Les autres comptes ne sont pas touchés.
    assert anonymous.post("/api/auth/login", json=VIEWER).status_code == 200


def test_le_blocage_se_leve_apres_la_fenetre(anonymous, db):
    from datetime import timedelta

    from backend.models.entities import utcnow

    for _ in range(5):
        anonymous.post("/api/auth/login", json={**OWNER, "password": "essai-au-hasard"})
    db.query(AuditLog).update({"at": utcnow() - timedelta(minutes=16)})
    db.commit()
    assert anonymous.post("/api/auth/login", json=OWNER).status_code == 200


# ---------- Rôles ----------

def test_le_lecteur_peut_regarder(viewer, bac):
    assert viewer.get("/api/bacs").status_code == 200
    assert viewer.get("/api/readings/bac01").status_code == 200
    assert viewer.get("/api/alerts/bac01").status_code == 200
    assert viewer.get("/api/bacs/bac01/commands").status_code == 200


def test_le_lecteur_ne_peut_rien_modifier(viewer, bac):
    assert viewer.post("/api/bacs", json={"bac_id": "bac02", "nom": "Intrus"}).status_code == 403
    assert viewer.patch("/api/bacs/bac01", json={"nom": "Renommé"}).status_code == 403
    assert viewer.post("/api/bacs/bac01/mqtt-credentials").status_code == 403
    assert viewer.post("/api/bacs/bac01/commands", json={"type": "pump_on"}).status_code == 403
    assert viewer.post("/api/readings", json=reading()).status_code == 403
    assert viewer.get("/api/audit").status_code == 403


# ---------- Requêtes venues d'un autre site (CSRF) ----------

def test_une_modification_venue_d_un_autre_site_est_refusee(client):
    r = client.post("/api/bacs", json=BAC, headers={"Origin": "https://site-malveillant.example"})
    assert r.status_code == 403
    assert client.get("/api/bacs").json() == []


def test_une_modification_venue_de_notre_site_est_acceptee(client):
    r = client.post("/api/bacs", json=BAC, headers={"Origin": "http://testserver"})
    assert r.status_code == 201


# ---------- Journal d'audit ----------

def test_le_journal_d_audit_garde_la_trace_des_actions(client, bac):
    client.patch("/api/bacs/bac01", json={"moisture_low": 40})
    TestClient(app).post("/api/auth/login", json={**OWNER, "password": "essai-au-hasard"})

    entries = client.get("/api/audit").json()
    actions = [e["action"] for e in entries]
    assert actions[:4] == ["login_failed", "bac_updated", "bac_created", "login_ok"]
    updated = entries[1]
    assert updated["actor"] == OWNER["email"]
    assert updated["target"] == "bac01"
    assert updated["details"] == {"moisture_low": 40.0}
    # Jamais de mot de passe dans le journal.
    assert "essai-au-hasard" not in str(entries)


def test_les_noms_des_comptes_du_systeme_sont_reserves(client):
    r = client.post("/api/bacs", json={"bac_id": "greengrow-backend", "nom": "Usurpateur"})
    assert r.status_code == 422
