"""Le tableau de bord, ses en-têtes de sécurité, et les alertes Telegram."""

import re
from pathlib import Path

import pytest

from backend.config import get_settings
from backend.mqtt.ingestion import handle_message
from backend.services import notify
from tests.conftest import reading

WEB = Path(__file__).parent.parent / "backend" / "web"


def test_la_page_s_affiche_sans_connexion_mais_ne_contient_aucune_donnee(anonymous, client, bac):
    # "client" a créé le bac ; un visiteur non connecté demande la page.
    from fastapi.testclient import TestClient

    from backend.main import app

    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Bac pilote" not in page.text and "bac01" not in page.text


def test_les_fichiers_du_tableau_de_bord_sont_servis(anonymous):
    for name in ("app.js", "style.css", "theme.js", "favicon.svg"):
        assert anonymous.get(f"/static/{name}").status_code == 200, name


def test_les_en_tetes_de_securite_sont_poses(anonymous):
    headers = anonymous.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


def test_les_reponses_de_l_api_ne_sont_pas_mises_en_cache(client):
    assert client.get("/api/bacs").headers["cache-control"] == "no-store"


def test_la_page_respecte_sa_propre_politique_de_securite():
    """
    La politique interdit les scripts et styles écrits DANS la page. Si
    quelqu'un en ajoute un, le navigateur le bloquerait en silence : ce test
    le signale avant.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "script en ligne"
    assert "<style" not in html and " style=" not in html, "style en ligne"
    assert not re.search(r"\son[a-z]+=", html), "gestionnaire d'événement en ligne"
    assert not re.search(r'(src|href)="https?://', html), "ressource venue d'un autre site"


def test_le_script_n_utilise_jamais_innerhtml():
    script = (WEB / "static" / "app.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.strip().startswith("//"))
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code


# ---------- Telegram ----------

@pytest.fixture
def telegram(monkeypatch):
    """Telegram configuré, mais les messages sont retenus au lieu de partir."""
    sent = []
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", "123:jeton-secret")
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(notify, "send", sent.append)
    return sent


def test_une_alerte_qui_s_ouvre_envoie_un_message(client, bac, telegram):
    client.post("/api/readings", json=reading(moisture_percent=30))
    assert len(telegram) == 1
    assert "Humidité du sol trop basse" in telegram[0]


def test_un_probleme_qui_dure_n_envoie_qu_un_seul_message(client, bac, telegram):
    for i in range(5):
        client.post("/api/readings", json=reading(timestamp=1_800_000_000 + i, moisture_percent=30))
    assert len(telegram) == 1


def test_une_mesure_normale_n_envoie_rien(client, bac, telegram):
    client.post("/api/readings", json=reading())
    assert telegram == []


def test_le_mode_securite_d_un_bac_envoie_un_message(client, bac, db, telegram):
    handle_message(db, "greengrow/abidjan/bac01/event", b'{"type": "fault_sensor"}')
    assert len(telegram) == 1 and "Mode sécurité" in telegram[0]


def test_sans_configuration_rien_n_est_envoye(monkeypatch):
    called = []
    monkeypatch.setattr(notify, "send_now", called.append)
    notify.send("bonjour")
    assert called == []


def test_une_panne_de_telegram_ne_fait_pas_d_erreur_et_ne_revele_pas_le_jeton(monkeypatch, caplog):
    import httpx

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", "123:jeton-secret")
    monkeypatch.setattr(settings, "telegram_chat_id", "42")

    def boom(url, **kwargs):
        raise httpx.ConnectError(f"impossible de joindre {url}")

    monkeypatch.setattr(httpx, "post", boom)
    with caplog.at_level("WARNING"):
        assert notify.send_now("bonjour") is False
    assert "jeton-secret" not in caplog.text
