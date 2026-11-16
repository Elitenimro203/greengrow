from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_bac_or_404
from backend.models.database import get_db
from backend.models.entities import Alert, Bac, BacEvent
from backend.models.schemas import AlertOut, EventOut

router = APIRouter(tags=["alertes"])


@router.get("/alerts/{bac_id}", response_model=list[AlertOut])
def get_alerts(
    bac: Bac = Depends(get_bac_or_404),
    active: bool = Query(default=False, description="true = seulement les alertes en cours"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Alertes d'un bac, de la plus récente à la plus ancienne."""
    query = select(Alert).where(Alert.bac_id == bac.id)
    if active:
        query = query.where(Alert.resolved_at.is_(None))
    return db.scalars(query.order_by(Alert.opened_at.desc()).limit(limit)).all()


@router.get("/events/{bac_id}", response_model=list[EventOut], tags=["événements"])
def get_events(
    bac: Bac = Depends(get_bac_or_404),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Journal de bord d'un bac : arrosages, mode sécurité, commandes..."""
    return db.scalars(
        select(BacEvent)
        .where(BacEvent.bac_id == bac.id)
        .order_by(BacEvent.occurred_at.desc(), BacEvent.id.desc())
        .limit(limit)
    ).all()
