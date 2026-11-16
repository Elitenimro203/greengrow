"""
GreenGrow — Tables de la base de données
=========================================
Quatre tables, pensées dès le départ pour plusieurs bacs et plusieurs sites :

    Site  1 ── n  Bac  1 ── n  Reading   (les mesures)
                       1 ── n  Alert     (les alertes)

Un site = un lieu (un toit, une cour, une école). Un bac = un bac de culture
avec SES seuils. Ajouter un bac ou une nouvelle culture ne demande donc
aucune modification du code.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String
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
