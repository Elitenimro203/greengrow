"""
GreenGrow — Point d'entrée de l'API
Lancement : uvicorn backend.main:app --reload
(la base doit être à jour : alembic upgrade head)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.alerts import router as alerts_router
from backend.api.bacs import router as bacs_router
from backend.api.readings import router as readings_router
from backend.config import get_settings
from backend.mqtt import dynsec
from backend.mqtt.ingestion import MqttIngestion

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("greengrow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ce qui se passe au démarrage (avant yield) et à l'arrêt (après yield)."""
    ingestion = None
    if settings.mqtt_enabled:
        try:
            dynsec.ensure_backend_account()
        except dynsec.BrokerError as exc:
            # L'API démarre quand même ; l'ingestion réessaiera de se connecter.
            log.warning("Compte MQTT du backend non vérifié : %s", exc)
        ingestion = MqttIngestion()
        ingestion.start()
    yield
    if ingestion is not None:
        ingestion.stop()


app = FastAPI(
    lifespan=lifespan,
    title="GreenGrow API",
    description="API de gestion des bacs de culture intelligents",
    version="0.4.0",
)

# CORS : quels sites web ont le droit d'appeler l'API depuis un navigateur.
# Avant c'était "*" (tout le monde). Maintenant c'est une liste précise,
# réglable dans .env (CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

app.include_router(bacs_router, prefix="/api")
app.include_router(readings_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")


@app.get("/")
def root():
    """Route de santé — vérifie que l'API tourne."""
    return {"status": "ok", "project": "GreenGrow", "version": app.version}


@app.get("/health")
def health():
    """Utilisée par les outils de monitoring pour vérifier que le serveur répond."""
    return {"status": "healthy"}
