"""
GreenGrow — Point d'entrée de l'API
Lancement : uvicorn backend.main:app --reload
(la base doit être à jour : alembic upgrade head)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.alerts import router as alerts_router
from backend.api.bacs import router as bacs_router
from backend.api.readings import router as readings_router
from backend.config import get_settings

settings = get_settings()

app = FastAPI(
    title="GreenGrow API",
    description="API de gestion des bacs de culture intelligents",
    version="0.2.0",
)

# CORS : quels sites web ont le droit d'appeler l'API depuis un navigateur.
# Avant c'était "*" (tout le monde). Maintenant c'est une liste précise,
# réglable dans .env (CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
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
