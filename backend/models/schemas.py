"""
GreenGrow — Schémas Pydantic
=============================
Les schémas décrivent ce qui ENTRE et ce qui SORT de l'API. Ils sont séparés
des tables (entities.py) exprès : on ne veut ni accepter n'importe quel champ
de la base en entrée, ni exposer par accident une colonne interne en sortie.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

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


class Measurement(BaseModel):
    """
    Le contenu d'une mesure, SANS l'identité du bac.

    C'est exactement ce qu'un bac publie en MQTT. L'identité ne vient jamais
    du message : elle vient du topic, que le broker n'autorise qu'au compte
    de ce bac. Un bac ne peut donc pas se faire passer pour un autre.
    """

    # Nombre de secondes Unix ou date ISO. Absent = heure de réception par le
    # serveur (un ESP32 qui vient de démarrer ne connaît pas encore l'heure).
    timestamp: Optional[UtcDatetime] = None
    moisture_percent: float = Field(ge=0.0, le=100.0)
    temperature_celsius: float = Field(ge=-10.0, le=60.0)
    humidity_air_percent: float = Field(ge=0.0, le=100.0)
    pump_active: bool
    source: Optional[str] = Field(default="hardware", max_length=20)


class SensorReading(Measurement):
    """Une mesure envoyée par HTTP (outil de test) : là, le bac est dans le message."""

    bac_id: str = Field(pattern=SLUG)


class BacCreate(BaseModel):
    """Enregistrement d'un nouveau bac. Les seuils sont optionnels (profil par défaut)."""

    bac_id: str = Field(pattern=SLUG)
    nom: str = Field(min_length=1, max_length=100)
    site: str = Field(default="abidjan", pattern=SLUG)
    culture: str = Field(default="tomate", max_length=50)
    moisture_low: Optional[float] = Field(default=None, ge=0, le=100)
    moisture_high: Optional[float] = Field(default=None, ge=0, le=100)
    temp_max: Optional[float] = Field(default=None, ge=-10, le=60)


class BacUpdate(BaseModel):
    """Modification d'un bac : on n'envoie que ce qu'on veut changer."""

    nom: Optional[str] = Field(default=None, min_length=1, max_length=100)
    moisture_low: Optional[float] = None
    moisture_high: Optional[float] = None
    temp_max: Optional[float] = Field(default=None, ge=-10, le=60)


class DeviceEvent(BaseModel):
    """Un événement publié par un bac sur son topic .../event."""

    model_config = ConfigDict(extra="allow")  # les détails varient selon le type

    type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    timestamp: Optional[UtcDatetime] = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    occurred_at: UtcDatetime
    details: dict


class BacOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bac_id: str = Field(validation_alias="slug")
    nom: str
    culture: str
    moisture_low: float
    moisture_high: float
    temp_max: float
    online: bool
    last_seen_at: Optional[UtcDatetime]
    created_at: UtcDatetime


class MqttCredentials(BaseModel):
    host: str
    port: int
    username: str
    password: str
    topic_prefix: str


class BacCreated(BacOut):
    """Réponse à la création : le mot de passe MQTT n'est montré QUE cette fois."""

    mqtt: Optional[MqttCredentials] = None


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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    """Ce qu'on montre d'un utilisateur : jamais l'empreinte du mot de passe."""

    model_config = ConfigDict(from_attributes=True)

    email: str
    nom: str
    role: str


class CommandCreate(BaseModel):
    """Une commande à envoyer à un bac."""

    type: Literal["pump_on", "pump_off", "reset_fault"]
    # Durée d'arrosage pour pump_on. Le bac applique en plus SA propre limite
    # (max_watering_s) : le serveur ne peut pas la dépasser.
    duration_s: int = Field(default=10, ge=1, le=120)


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    params: dict
    status: str
    reason: Optional[str]
    created_at: UtcDatetime
    expires_at: UtcDatetime
    answered_at: Optional[UtcDatetime]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: UtcDatetime
    actor: str
    action: str
    target: Optional[str]
    ip: Optional[str]
    details: dict
