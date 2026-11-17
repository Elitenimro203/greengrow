"""
GreenGrow — Commandes envoyées aux bacs
========================================
Le trajet d'une commande :

  toi -> API -> (base : "sent") -> broker MQTT -> bac
  bac -> broker -> ingestion -> (base : "executed" ou "rejected")

Chaque commande porte un identifiant unique et une heure limite. Le bac
(firmware/greengrow_bac/commands.h) refuse une commande périmée ou déjà vue :
un message retardé ou livré deux fois ne fait donc jamais tourner la pompe à
un moment où personne ne l'a demandé.

L'API ne dit jamais "c'est fait" à la place du bac : elle dit "envoyée", et
c'est l'accusé de réception du bac qui fait passer la commande à "executed".
"""

import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.entities import Bac, Command, User, utcnow
from backend.mqtt import ingestion
from backend.services import audit

TYPES = ("pump_on", "pump_off", "reset_fault")


class CommandRefused(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def expire_stale(db: Session) -> None:
    """Les commandes restées sans réponse après leur heure limite deviennent "expired"."""
    db.execute(
        update(Command)
        .where(Command.status == "sent", Command.expires_at < utcnow())
        .values(status="expired")
    )


def send(
    db: Session, bac: Bac, user: User, type_: str, duration_s: int | None, ip: str | None
) -> Command:
    settings = get_settings()
    if not ingestion.is_running():
        raise CommandRefused(503, "MQTT est désactivé sur ce serveur (MQTT_ENABLED=false)")
    if not bac.online:
        # Le bac ignorerait de toute façon une commande reçue trop tard :
        # autant le dire tout de suite plutôt que de laisser croire qu'elle part.
        raise CommandRefused(409, "Ce bac est hors ligne : commande non envoyée")

    recent = db.scalar(
        select(func.count())
        .select_from(Command)
        .where(Command.bac_id == bac.id, Command.created_at >= utcnow() - timedelta(minutes=1))
    )
    if recent >= settings.command_max_per_minute:
        raise CommandRefused(429, "Trop de commandes pour ce bac, attends une minute")

    now = utcnow()
    command = Command(
        id=str(uuid.uuid4()),
        bac_id=bac.id,
        user_id=user.id,
        type=type_,
        params={"duration_s": duration_s} if type_ == "pump_on" else {},
        created_at=now,
        expires_at=now + timedelta(seconds=settings.command_lifetime_seconds),
    )
    db.add(command)
    audit.record(
        db, "command_sent", user=user, target=bac.slug, ip=ip,
        details={"id": command.id, "type": type_, **command.params},
    )
    # On enregistre AVANT de publier : si l'accusé de réception arrive très
    # vite, la commande existe déjà en base.
    db.commit()

    payload = {"id": command.id, "type": type_, "expires_at": int(command.expires_at.timestamp())}
    payload.update(command.params)
    ingestion.publish_command(bac, json.dumps(payload))
    return command


def on_ack(db: Session, bac: Bac, details: dict) -> bool:
    """
    Applique l'accusé de réception d'un bac. Retourne False s'il est ignoré.

    Sécurité : on cherche la commande par son identifiant ET par le bac qui
    répond (identifié par le topic). Un bac ne peut donc pas "valider" la
    commande d'un autre bac, même s'il devinait son identifiant.
    """
    result = details.get("result")
    command_id = details.get("id")
    if result not in ("executed", "rejected") or not isinstance(command_id, str):
        return False
    command = db.scalar(
        select(Command).where(Command.id == command_id, Command.bac_id == bac.id)
    )
    # Seule la PREMIÈRE réponse compte ; une commande expirée peut encore
    # recevoir sa réponse (l'accusé a pu traîner sur le réseau).
    if command is None or command.status not in ("sent", "expired"):
        return False
    command.status = result
    reason = details.get("reason")
    command.reason = reason[:40] if isinstance(reason, str) else None
    command.answered_at = utcnow()
    return True
