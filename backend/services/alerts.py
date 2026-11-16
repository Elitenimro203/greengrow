"""
GreenGrow — Service d'alertes
==============================
Règle : UNE alerte par problème, pas une alerte par mesure.

Avant, chaque mesure sous le seuil créait une nouvelle ligne : avec une
mesure par minute, un bac sec pendant une nuit produisait 500 alertes
identiques. Maintenant :
  - le seuil est franchi et aucune alerte n'est ouverte  -> on OUVRE une alerte
  - le seuil est franchi et une alerte est déjà ouverte  -> on met juste à jour sa valeur
  - la valeur est redevenue normale                      -> on FERME l'alerte
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.entities import Alert, Bac


def _open_alert(db: Session, bac: Bac, alert_type: str) -> Alert | None:
    return db.scalar(
        select(Alert).where(
            Alert.bac_id == bac.id,
            Alert.type == alert_type,
            Alert.resolved_at.is_(None),
        )
    )


def _update(db, bac, alert_type, in_alarm, value, message, when) -> Alert | None:
    """Applique la règle ci-dessus. Retourne l'alerte seulement si elle vient d'être ouverte."""
    current = _open_alert(db, bac, alert_type)
    if in_alarm:
        if current is None:
            alert = Alert(
                bac_id=bac.id, type=alert_type, message=message,
                opened_at=when, last_value=value,
            )
            db.add(alert)
            return alert
        current.last_value = value
    elif current is not None:
        current.resolved_at = when
    return None


def evaluate(
    db: Session, bac: Bac, moisture: float, temperature: float, when: datetime
) -> list[Alert]:
    """Compare une mesure aux seuils DU BAC. Retourne les alertes nouvellement ouvertes."""
    checks = [
        (
            "moisture_low",
            moisture < bac.moisture_low,
            moisture,
            f"Humidité du sol trop basse ({moisture} %) sur {bac.nom}",
        ),
        (
            "temperature_high",
            temperature > bac.temp_max,
            temperature,
            f"Température élevée ({temperature} °C) sur {bac.nom}",
        ),
    ]
    opened = []
    for alert_type, in_alarm, value, message in checks:
        alert = _update(db, bac, alert_type, in_alarm, value, message, when)
        if alert is not None:
            opened.append(alert)
    return opened
