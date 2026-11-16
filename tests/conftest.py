"""
Préparation commune des tests.

Chaque test reçoit une base SQLite neuve, en mémoire : les tests ne touchent
jamais ta vraie base et ne dépendent pas les uns des autres.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.models import entities  # noqa: F401  (déclare les tables)
from backend.models.database import Base, get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # une seule connexion : la base en mémoire est partagée
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # On remplace la vraie base par la base de test, le temps du test.
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
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
