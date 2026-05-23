import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.reading import SensorReading
from backend.models.database import get_db, Reading, Bac
from dotenv import load_dotenv

load_dotenv()

# Seuils d'alerte (à ajuster selon tes plantes)
MOISTURE_THRESHOLD_LOW = float(os.getenv("MOISTURE_THRESHOLD_LOW", 45))
TEMP_MAX_CELSIUS = float(os.getenv("TEMP_MAX_CELSIUS", 35))

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

    # Vérification seuils
    alerts = []

    # À toi : 
    # - Si moisture_percent < seuil bas → ajouter une alerte
    if reading.moisture_percent < MOISTURE_THRESHOLD_LOW:
        alerts.append("Humidité trop basse - arroser le bac !")
    # - Si temperature_celsius > seuil max → ajouter une alerte
    if reading.temperature_celsius > TEMP_MAX_CELSIUS:
        alerts.append("Température trop élevée - Ventiler le bac !")

    print(f"[Greengrow] Stocké - Bac: {reading.bac_id} | Humidité: {reading.moisture_percent}% | Alerts: {alerts}")
    return {"status": "stored", "bac_id": reading.bac_id, "alerts": alerts}

@router.get("/readings/{bac_id}")
def get_readings(bac_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """Récupère les dernières lectures d'un bac."""
    readings = db.query(Reading).filter(Reading.bac_id == bac_id).order_by(Reading.timestamp.desc()).limit(limit).all()
    return readings
