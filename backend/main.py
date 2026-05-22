"""
GreenGrow — Point d'entrée de l'API
Lancement : uvicorn backend.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.readings import router as readings_router
from backend.models.database import init_db

# On importe les routes (on les ajoute au fur et à mesure)
# from backend.api import sensors, alerts

app = FastAPI(
    title="GreenGrow API",
    description="API de gestion des bacs de culture intelligents",
    version="0.1.0",
)

@app.on_event("startup")
def startup():
    init_db()
    print("[Greengrow] Base de données initialisée ✓")

# Middleware CORS — permet au dashboard HTML de parler à l'API
# En prod, remplace ["*"] par l'URL exacte de ton frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

#Enregistrement des routeurs
app.include_router(readings_router, prefix="/api")

@app.get("/")
def root():
    """Route de santé — vérifie que l'API tourne."""
    return {"status": "ok", "project": "GreenGrow", "version": "0.1.0"}


@app.get("/health")
def health():
    """Utilisée par les monitors de prod pour vérifier que le serveur répond."""
    return {"status": "healthy"}


# Pourquoi séparer root() et health() ?
# root() est la vitrine publique.
# health() est le check silencieux des outils de monitoring (uptime robots, k8s, etc.)
# Tu les distingues dès le départ pour prendre la bonne habitude.
