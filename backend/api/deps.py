"""Dépendances partagées par les routes."""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.database import get_db
from backend.models.entities import Bac


def get_bac_or_404(bac_id: str, db: Session = Depends(get_db)) -> Bac:
    return find_bac(db, bac_id)


def find_bac(db: Session, bac_id: str) -> Bac:
    bac = db.scalar(select(Bac).where(Bac.slug == bac_id))
    if bac is None:
        # Un bac inconnu n'est PLUS créé automatiquement : seul un bac
        # enregistré peut envoyer des données.
        raise HTTPException(status_code=404, detail=f"Bac inconnu : {bac_id}")
    return bac
