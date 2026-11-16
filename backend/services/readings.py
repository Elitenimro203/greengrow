"""
GreenGrow — Service d'enregistrement des mesures
=================================================
Cette fonction est le point d'entrée UNIQUE d'une mesure dans le système.
Elle est appelée par l'abonné MQTT (le chemin normal) et par la route HTTP
(outil de test) : la logique (stocker + vérifier les
alertes) n'existe qu'à un seul endroit, quel que soit le canal d'arrivée.
"""

from sqlalchemy.orm import Session

from backend.models.entities import Alert, Bac, Reading, utcnow
from backend.models.schemas import Measurement
from backend.services import alerts


def record_reading(db: Session, bac: Bac, data: Measurement) -> list[Alert]:
    """Stocke la mesure et met à jour les alertes, dans UNE seule transaction."""
    measured_at = data.timestamp or utcnow()
    db.add(
        Reading(
            bac_id=bac.id,
            measured_at=measured_at,
            moisture_percent=data.moisture_percent,
            temperature_celsius=data.temperature_celsius,
            humidity_air_percent=data.humidity_air_percent,
            pump_active=data.pump_active,
            source=data.source or "hardware",
        )
    )
    opened = alerts.evaluate(
        db, bac, data.moisture_percent, data.temperature_celsius, measured_at
    )
    # Un seul commit : soit la mesure ET ses alertes sont enregistrées, soit rien.
    db.commit()
    return opened
