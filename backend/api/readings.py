from fastapi import APIRouter
from backend.models.reading import SensorReading

router = APIRouter()

@router.post("/readings")
def create_reading(reading: SensorReading):
    """
    Reçoit une lecture de capteurs depuis l'ESP32 ou le simulateur.
    """
    print(f"[Greengrow] Lecture reçue - Bac: {reading.bac_id} | Humidité: {reading.moisture_percent}%")
    return {"status": "received", "bac_id": reading.bac_id}