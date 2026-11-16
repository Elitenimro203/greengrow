"""
GreenGrow — Schémas Pydantic
=============================
Les schémas décrivent ce qui ENTRE et ce qui SORT de l'API. Ils sont séparés
des tables (entities.py) exprès : on ne veut ni accepter n'importe quel champ
de la base en entrée, ni exposer par accident une colonne interne en sortie.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field



def _to_utc(v: datetime) -> datetime:
    # Une date sans fuseau est considérée comme UTC, puis tout est ramené en UTC.
    # Utile en entrée (capteurs) ET en sortie : SQLite oublie le fuseau, on le
    # remet pour que le dashboard reçoive toujours une date non ambiguë ("...Z").
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_to_utc)]

SLUG = r"^[a-z0-9][a-z0-9_-]{1,49}$"  # minuscules, chiffres, - et _ (sûr dans un topic MQTT)


class SensorReading(BaseModel):
    """Une mesure envoyée par un bac (réel ou simulé)."""

    bac_id: str = Field(pattern=SLUG)
    # Accepte un nombre de secondes Unix (ce qu'envoie l'ESP32) ou une date ISO.
    timestamp: UtcDatetime
    moisture_percent: float = Field(ge=0.0, le=100.0)
    temperature_celsius: float = Field(ge=-10.0, le=60.0)
    humidity_air_percent: float = Field(ge=0.0, le=100.0)
    pump_active: bool
    source: Optional[str] = Field(default="hardware", max_length=20)


class BacCreate(BaseModel):
    """Enregistrement d'un nouveau bac. Les seuils sont optionnels (profil par défaut)."""

    bac_id: str = Field(pattern=SLUG)
    nom: str = Field(min_length=1, max_length=100)
    site: str = Field(default="abidjan", pattern=SLUG)
    culture: str = Field(default="tomate", max_length=50)
    moisture_low: Optional[float] = Field(default=None, ge=0, le=100)
    moisture_high: Optional[float] = Field(default=None, ge=0, le=100)
    temp_max: Optional[float] = Field(default=None, ge=-10, le=60)


class BacOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bac_id: str = Field(validation_alias="slug")
    nom: str
    culture: str
    moisture_low: float
    moisture_high: float
    temp_max: float
    created_at: UtcDatetime


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    measured_at: UtcDatetime
    moisture_percent: float
    temperature_celsius: float
    humidity_air_percent: float
    pump_active: bool
    source: str


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    message: str
    opened_at: UtcDatetime
    resolved_at: Optional[UtcDatetime]
    last_value: float
