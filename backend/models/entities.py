"""
GreenGrow — Tables de la base de données
=========================================
Les tables, pensées dès le départ pour plusieurs bacs et plusieurs sites :

    Site  1 ── n  Bac  1 ── n  Reading   (les mesures)
                       1 ── n  Alert     (les alertes)
                       1 ── n  BacEvent  (ce que le bac a fait)
                       1 ── n  Command   (ce qu'on lui a demandé)

    User  1 ── n  UserSession  (les connexions ouvertes)
    AuditLog                   (qui a fait quoi, et quand)

Un site = un lieu (un toit, une cour, une école). Un bac = un bac de culture
avec SES seuils. Ajouter un bac ou une nouvelle culture ne demande donc
aucune modification du code.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.database import Base


def utcnow() -> datetime:
    """Heure actuelle en UTC. On stocke TOUT en UTC, on convertit à l'affichage."""
    return datetime.now(timezone.utc)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bacs: Mapped[list["Bac"]] = relationship(back_populates="site")


class Bac(Base):
    __tablename__ = "bacs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifiant public du bac ("bac01"). C'est lui qu'on retrouvera dans les
    # topics MQTT : greengrow/{site.slug}/{bac.slug}/telemetry
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    nom: Mapped[str] = mapped_column(String(100))
    culture: Mapped[str] = mapped_column(String(50), default="tomate")

    # Seuils propres à ce bac.
    moisture_low: Mapped[float] = mapped_column(Float)
    moisture_high: Mapped[float] = mapped_column(Float)
    temp_max: Mapped[float] = mapped_column(Float)

    # État de connexion, tenu à jour par l'ingestion MQTT (topic .../status).
    online: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    site: Mapped[Site] = relationship(back_populates="bacs")


class Reading(Base):
    __tablename__ = "readings"
    # La requête la plus fréquente sera "les dernières mesures de tel bac" :
    # cet index la garde rapide même avec des millions de lignes.
    __table_args__ = (Index("ix_readings_bac_measured", "bac_id", "measured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bac_id: Mapped[int] = mapped_column(ForeignKey("bacs.id"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # heure du capteur
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # heure du serveur
    moisture_percent: Mapped[float] = mapped_column(Float)
    temperature_celsius: Mapped[float] = mapped_column(Float)
    humidity_air_percent: Mapped[float] = mapped_column(Float)
    pump_active: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(20), default="hardware")


class Alert(Base):
    """
    Une alerte représente un PROBLÈME qui dure, pas une mesure.
    Elle s'ouvre quand le seuil est franchi (resolved_at vide) et se ferme
    quand la valeur redevient normale. Tant qu'elle est ouverte, on n'en crée
    pas d'autre du même type pour le même bac.
    """

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_bac_type_open", "bac_id", "type", "resolved_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bac_id: Mapped[int] = mapped_column(ForeignKey("bacs.id"))
    type: Mapped[str] = mapped_column(String(30))  # "moisture_low" | "temperature_high"
    message: Mapped[str] = mapped_column(String(255))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_value: Mapped[float] = mapped_column(Float)


class BacEvent(Base):
    """
    Le journal de bord d'un bac : ce qu'il a FAIT (pompe démarrée, arrêtée,
    mode sécurité, commande exécutée ou refusée...). Les mesures disent
    comment va la plante ; les événements disent ce que le bac a décidé.
    """

    __tablename__ = "bac_events"
    __table_args__ = (Index("ix_bac_events_bac_occurred", "bac_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bac_id: Mapped[int] = mapped_column(ForeignKey("bacs.id"))
    type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    """
    Une personne qui peut se connecter au tableau de bord.

    Le mot de passe n'est JAMAIS stocké : on ne garde que son empreinte
    (password_hash, voir backend/services/passwords.py).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    # "owner"  : peut tout faire (bacs, seuils, commandes, journal d'audit)
    # "viewer" : peut seulement regarder
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    """
    Une connexion ouverte. Le navigateur détient un jeton secret (dans un
    cookie) ; la base ne garde que l'EMPREINTE de ce jeton. Si la base fuit,
    les empreintes ne permettent pas de se connecter.
    """

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class Command(Base):
    """
    Une commande envoyée à un bac ("arrose 10 secondes").

    status : "sent"     envoyée, on attend la réponse du bac
             "executed" le bac l'a exécutée
             "rejected" le bac l'a refusée (reason dit pourquoi)
             "expired"  aucune réponse avant l'heure limite
    """

    __tablename__ = "commands"
    __table_args__ = (Index("ix_commands_bac_created", "bac_id", "created_at"),)

    # L'identifiant est un UUID tiré au hasard : c'est lui que le bac renvoie
    # dans son accusé de réception.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bac_id: Mapped[int] = mapped_column(ForeignKey("bacs.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """
    Le journal d'audit : chaque action sensible y laisse une ligne (qui, quoi,
    sur quoi, depuis quelle adresse). On n'y écrit qu'en ajout : aucune route
    ne modifie ni ne supprime une ligne.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_action_at", "action", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # user_id est vide pour une connexion ratée : il n'y a pas (encore) d'utilisateur.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(254))  # l'e-mail utilisé, même s'il n'existe pas
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
