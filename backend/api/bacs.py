from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.database import get_db
from backend.models.entities import Bac, Site
from backend.models.schemas import BacCreate, BacOut

router = APIRouter(tags=["bacs"])


@router.post("/bacs", response_model=BacOut, status_code=201)
def create_bac(payload: BacCreate, db: Session = Depends(get_db)):
    """Enregistre un nouveau bac (et son site s'il n'existe pas encore)."""
    if db.scalar(select(Bac).where(Bac.slug == payload.bac_id)):
        raise HTTPException(status_code=409, detail="Ce bac existe déjà")

    settings = get_settings()
    low = payload.moisture_low if payload.moisture_low is not None else settings.moisture_threshold_low
    high = payload.moisture_high if payload.moisture_high is not None else settings.moisture_threshold_high
    if low >= high:
        raise HTTPException(status_code=422, detail="moisture_low doit être inférieur à moisture_high")

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
    db.commit()
    db.refresh(bac)
    return bac


@router.get("/bacs", response_model=list[BacOut])
def list_bacs(db: Session = Depends(get_db)):
    return db.scalars(select(Bac).order_by(Bac.slug)).all()
