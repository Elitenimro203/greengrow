"""
Préparation commune des tests.

Chaque test reçoit une base SQLite neuve, en mémoire : les tests ne touchent
jamais ta vraie base et ne dépendent pas les uns des autres.
"""

import os

# Réglages des tests, posés AVANT d'importer l'application : une clé admin
# connue et pas de broker (les tests ne dépendent d'aucun service extérieur).
os.environ["ADMIN_API_KEY"] = "cle-de-test"
os.environ["MQTT_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.main import app  # noqa: E402
from backend.models import entities  # noqa: E402,F401  (déclare les tables)
from backend.models.database import Base, get_db  # noqa: E402


ADMIN = {"X-Admin-Key": "cle-de-test"}


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # une seule connexion : la base en mémoire est partagée
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture
def db(db_session_factory):
    """Une session directe sur la base de test (pour tester l'ingestion MQTT)."""
    session = db_session_factory()
    yield session
    session.close()


@pytest.fixture
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    # On remplace la vraie base par la base de test, le temps du test.
    app.dependency_overrides[get_db] = override_get_db
    # Par défaut, le client de test envoie la clé d'administration.
    yield TestClient(app, headers=ADMIN)
    app.dependency_overrides.clear()


@pytest.fixture
def bac(client):
    """Un bac enregistré avec les seuils tomate par défaut (45 / 80 / 35)."""
    r = client.post("/api/bacs", json={"bac_id": "bac01", "nom": "Bac pilote"})
    assert r.status_code == 201
    return r.json()


def reading(**overrides):
    """Une mesure normale ; on ne précise que ce qu'on veut changer."""
    data = {
        "bac_id": "bac01",
        "timestamp": 1_800_000_000,
        "moisture_percent": 60.0,
        "temperature_celsius": 28.0,
        "humidity_air_percent": 70.0,
        "pump_active": False,
        "source": "test",
    }
    data.update(overrides)
    return data
