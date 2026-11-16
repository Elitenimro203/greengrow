from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import find_bac, get_bac_or_404
from backend.api.security import require_admin
from backend.models.database import get_db
from backend.models.entities import Bac, Reading
from backend.models.schemas import ReadingOut, SensorReading
from backend.services.readings import record_reading

router = APIRouter(tags=["mesures"])


@router.post("/readings", dependencies=[Depends(require_admin)])
def create_reading(reading: SensorReading, db: Session = Depends(get_db)):
    """
    Injecte une mesure à la main (outil de test, clé d'administration exigée).
    Les bacs, eux, passent par MQTT : c'est là qu'ils sont authentifiés.
    """
    bac = find_bac(db, reading.bac_id)
    opened = record_reading(db, bac, reading)
    return {
        "status": "stored",
        "bac_id": bac.slug,
        "alerts": [a.message for a in opened],  # seulement les NOUVELLES alertes
    }


@router.get("/readings/{bac_id}", response_model=list[ReadingOut])
def get_readings(
    bac: Bac = Depends(get_bac_or_404),
    # Limite bornée : personne ne peut demander 10 millions de lignes d'un coup.
    limit: int = Query(default=50, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Dernières mesures d'un bac, de la plus récente à la plus ancienne."""
    return db.scalars(
        select(Reading)
        .where(Reading.bac_id == bac.id)
        .order_by(Reading.measured_at.desc())
        .limit(limit)
    ).all()
