"""
GreenGrow — Service d'enregistrement des mesures
=================================================
Cette fonction est le point d'entrée UNIQUE d'une mesure dans le système.
Aujourd'hui elle est appelée par la route HTTP. À l'étape 2, l'abonné MQTT
appellera exactement la même fonction : la logique (stocker + vérifier les
alertes) n'existe qu'à un seul endroit, quel que soit le canal d'arrivée.
"""

from sqlalchemy.orm import Session

from backend.models.entities import Alert, Bac, Reading
from backend.models.schemas import SensorReading
from backend.services import alerts


def record_reading(db: Session, bac: Bac, data: SensorReading) -> list[Alert]:
    """Stocke la mesure et met à jour les alertes, dans UNE seule transaction."""
    db.add(
        Reading(
            bac_id=bac.id,
            measured_at=data.timestamp,
            moisture_percent=data.moisture_percent,
            temperature_celsius=data.temperature_celsius,
            humidity_air_percent=data.humidity_air_percent,
            pump_active=data.pump_active,
            source=data.source or "hardware",
        )
    )
    opened = alerts.evaluate(
        db, bac, data.moisture_percent, data.temperature_celsius, data.timestamp
    )
    # Un seul commit : soit la mesure ET ses alertes sont enregistrées, soit rien.
    db.commit()
    return opened
