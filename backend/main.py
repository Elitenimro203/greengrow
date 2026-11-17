"""
GreenGrow — Point d'entrée de l'API
Lancement : uvicorn backend.main:app --reload
(la base doit être à jour : alembic upgrade head)
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.alerts import router as alerts_router
from backend.api.auth import router as auth_router
from backend.api.bacs import router as bacs_router
from backend.api.commands import router as commands_router
from backend.api.readings import router as readings_router
from backend.api.security import check_origin, current_user
from backend.config import get_settings
from backend.mqtt import dynsec
from backend.mqtt.ingestion import MqttIngestion

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("greengrow")
# httpx journalise chaque adresse appelée. Celle de Telegram contient le jeton
# du bot : on ne garde donc que ses avertissements.
logging.getLogger("httpx").setLevel(logging.WARNING)

WEB_DIR = Path(__file__).parent / "web"


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
    version="0.6.0",
    # La documentation interactive est un outil de développement : elle
    # décrit toute l'API. En production, on ne l'expose pas.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Ce que le navigateur a le droit de faire avec nos pages. "default-src 'self'"
# = ne charge et n'exécute que ce qui vient de NOTRE serveur : même si un
# texte malveillant arrivait à s'afficher dans la page, il ne pourrait ni
# exécuter un script, ni envoyer des données vers un autre site.
CSP = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"  # pas de devinette sur le type des fichiers
    response.headers["X-Frame-Options"] = "DENY"  # la page ne peut pas être piégée dans un cadre
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.url.path.startswith(("/docs", "/openapi.json")):
        # /docs charge ses scripts depuis un autre site : il est exclu de la
        # règle (et désactivé en production).
        response.headers["Content-Security-Policy"] = CSP
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"  # HTTPS obligatoire
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"  # pas de données privées dans un cache
    return response


# CORS : quels sites web ont le droit d'appeler l'API depuis un navigateur.
# Avant c'était "*" (tout le monde). Maintenant c'est une liste précise,
# réglable dans .env (CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

# La connexion elle-même est la seule route d'API ouverte sans session.
app.include_router(auth_router, prefix="/api", dependencies=[Depends(check_origin)])

# TOUT le reste exige d'être connecté. La règle est posée ici, une fois, pour
# tous les routeurs : une nouvelle route est protégée sans qu'on ait à y
# penser ("fermé par défaut"). Ces vérifications passent AVANT le reste : un
# inconnu reçoit 401 et n'apprend même pas si un bac existe.
protected = [Depends(check_origin), Depends(current_user)]
for router in (bacs_router, readings_router, alerts_router, commands_router):
    app.include_router(router, prefix="/api", dependencies=protected)


# Le tableau de bord : une page et ses fichiers (style, script). La page ne
# contient aucune donnée : elle les demande à l'API, qui exige la connexion.
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    """Utilisée par les outils de monitoring pour vérifier que le serveur répond."""
    return {"status": "healthy"}
