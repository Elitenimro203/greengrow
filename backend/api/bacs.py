from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.database import get_db
from backend.models.entities import Bac, Site
from backend.api.deps import get_bac_or_404
from backend.api.security import require_admin
from backend.models.schemas import BacCreate, BacCreated, BacOut, BacUpdate, MqttCredentials
from backend.mqtt import dynsec, ingestion, topics

router = APIRouter(tags=["bacs"])


def _check_thresholds(low: float, high: float) -> None:
    """
    Les mêmes limites que celles du firmware (irrigation.h, isValidConfig) :
    inutile d'enregistrer des seuils que le bac refuserait d'appliquer.
    """
    if low < 5 or high > 95 or low + 5 > high:
        raise HTTPException(
            status_code=422,
            detail="Seuils invalides : il faut 5 <= moisture_low, moisture_high <= 95 "
            "et au moins 5 points d'écart entre les deux",
        )


def _provision(bac: Bac) -> MqttCredentials:
    """Crée le compte MQTT du bac sur le broker et prépare la réponse."""
    settings = get_settings()
    try:
        password = dynsec.provision_bac(bac.site.slug, bac.slug)
    except dynsec.BrokerError as exc:
        raise HTTPException(503, f"Compte MQTT non créé : {exc}") from exc
    return MqttCredentials(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        username=bac.slug,
        password=password,
        topic_prefix=topics.topic(bac.site.slug, bac.slug, "").rstrip("/"),
    )


@router.post(
    "/bacs", response_model=BacCreated, status_code=201, dependencies=[Depends(require_admin)]
)
def create_bac(payload: BacCreate, db: Session = Depends(get_db)):
    """
    Enregistre un nouveau bac (et son site s'il n'existe pas encore), puis
    crée son compte MQTT. Le mot de passe n'apparaît que dans CETTE réponse.
    """
    settings = get_settings()
    if payload.bac_id in (settings.mqtt_admin_user, settings.mqtt_backend_user):
        raise HTTPException(status_code=422, detail="Identifiant réservé")
    if db.scalar(select(Bac).where(Bac.slug == payload.bac_id)):
        raise HTTPException(status_code=409, detail="Ce bac existe déjà")

    low = payload.moisture_low if payload.moisture_low is not None else settings.moisture_threshold_low
    high = payload.moisture_high if payload.moisture_high is not None else settings.moisture_threshold_high
    _check_thresholds(low, high)

    site = db.scalar(select(Site).where(Site.slug == payload.site))
    if site is None:
        site = Site(slug=payload.site, nom=payload.site.capitalize())
        db.add(site)

    bac = Bac(
        slug=payload.bac_id,
        site=site,
        nom=payload.nom,
        culture=payload.culture,
        moisture_low=low,
        moisture_high=high,
        temp_max=payload.temp_max if payload.temp_max is not None else settings.temp_max_celsius,
    )
    db.add(bac)
    db.flush()  # le bac existe dans la transaction, mais rien n'est encore validé

    # Si le broker refuse, l'exception annule tout : pas de bac "à moitié créé"
    # en base sans compte MQTT.
    mqtt = _provision(bac) if settings.mqtt_enabled else None

    db.commit()
    db.refresh(bac)
    ingestion.publish_config(bac)  # ses seuils l'attendent déjà sur le broker
    return BacCreated.model_validate(bac).model_copy(update={"mqtt": mqtt})


@router.patch("/bacs/{bac_id}", response_model=BacOut, dependencies=[Depends(require_admin)])
def update_bac(
    payload: BacUpdate, bac: Bac = Depends(get_bac_or_404), db: Session = Depends(get_db)
):
    """Modifie le nom ou les seuils d'un bac, puis envoie les nouveaux seuils au bac."""
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    low = changes.get("moisture_low", bac.moisture_low)
    high = changes.get("moisture_high", bac.moisture_high)
    _check_thresholds(low, high)
    for field, value in changes.items():
        setattr(bac, field, value)
    db.commit()
    db.refresh(bac)
    ingestion.publish_config(bac)
    return bac


@router.post(
    "/bacs/{bac_id}/mqtt-credentials",
    response_model=MqttCredentials,
    dependencies=[Depends(require_admin)],
)
def rotate_mqtt_credentials(bac: Bac = Depends(get_bac_or_404)):
    """
    Génère un NOUVEAU mot de passe MQTT pour ce bac (l'ancien cesse de
    fonctionner). À utiliser si le mot de passe est perdu ou a fuité.
    """
    if not get_settings().mqtt_enabled:
        raise HTTPException(503, "MQTT est désactivé sur ce serveur (MQTT_ENABLED=false)")
    return _provision(bac)


@router.get("/bacs", response_model=list[BacOut])
def list_bacs(db: Session = Depends(get_db)):
    return db.scalars(select(Bac).order_by(Bac.slug)).all()
