from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.reading import SensorReading
from backend.models.database import get_db, Reading, Bac

router = APIRouter()

@router.post("/readings")
def create_reading(reading: SensorReading, db: Session = Depends(get_db)):
    #Crée le bac s'il n'existe pas encore
    bac = db.query(Bac).filter(Bac.bac_id == reading.bac_id).first()
    if not bac:
        bac = Bac(bac_id=reading.bac_id, nom="Prototype", localisation="Abidjan")
        db.add(bac)
        db.commit()

    #Stocke la lecture
    db_reading = Reading(
        bac_id=reading.bac_id,
        timestamp = reading.timestamp,
        moisture_percent=reading.moisture_percent,
        temperature_celsius=reading.temperature_celsius,
        humidity_air_percent=reading.humidity_air_percent,
        pump_active=reading.pump_active,
        source=reading.source,
    )
    db.add(db_reading)
    db.commit()

    print(f"[Greengrow] Stocké - Bac: {reading.bac_id} | Humidité: {reading.moisture_percent}%")
    return {"status": "stored", "bac_id": reading.bac_id}