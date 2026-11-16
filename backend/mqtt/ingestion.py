"""
GreenGrow — Ingestion MQTT
===========================
Le backend s'abonne aux topics de tous les bacs et range ce qu'il reçoit.

RÈGLE DE SÉCURITÉ CENTRALE : l'identité du bac vient du TOPIC, jamais du
contenu du message. Le broker ne laisse le compte "bac01" publier que sous
greengrow/{site}/bac01/... ; un message arrivé sur ce topic vient donc
forcément de bac01. Si le message contient un champ "bac_id", on l'ignore.

Tout ce qui arrive de l'extérieur est suspect : un message mal formé est
journalisé et ignoré, il ne doit jamais faire planter l'ingestion.
"""

import json
import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.database import SessionLocal
from backend.models.entities import Bac, Site, utcnow
from backend.models.schemas import Measurement
from backend.mqtt import topics
from backend.mqtt.client import new_client
from backend.services.readings import record_reading

log = logging.getLogger("greengrow.mqtt")

MAX_PAYLOAD_BYTES = 2048  # une mesure fait ~200 octets ; au-delà, ce n'est pas une mesure


def handle_message(db: Session, raw_topic: str, payload: bytes) -> str:
    """
    Traite UN message. Retourne ce qui a été fait ("stored", "status", ou
    "ignored: raison"). Fonction pure côté réseau : on peut la tester sans broker.
    """
    parsed = topics.parse(raw_topic)
    if parsed is None:
        return "ignored: topic hors convention"
    if len(payload) > MAX_PAYLOAD_BYTES:
        return "ignored: message trop gros"

    bac = db.scalar(
        select(Bac).join(Site).where(Bac.slug == parsed.bac, Site.slug == parsed.site)
    )
    if bac is None:
        return "ignored: bac inconnu sur ce site"

    if parsed.channel == "status":
        state = payload.decode("utf-8", errors="replace").strip()
        if state not in ("online", "offline"):
            return "ignored: statut invalide"
        bac.online = state == "online"
        if bac.online:
            bac.last_seen_at = utcnow()
        db.commit()
        return "status"

    if parsed.channel == "telemetry":
        try:
            data = Measurement.model_validate(json.loads(payload))
        except (ValueError, ValidationError):  # JSON cassé ou valeurs hors limites
            return "ignored: mesure invalide"
        bac.online = True
        bac.last_seen_at = utcnow()
        record_reading(db, bac, data)  # le même service que la route HTTP
        return "stored"

    return "ignored: canal non géré"


class MqttIngestion:
    """Garde une connexion ouverte au broker, dans un thread en arrière-plan."""

    def __init__(self) -> None:
        settings = get_settings()
        # clean_session=False + identifiant fixe : si le backend redémarre, le
        # broker lui garde les messages QoS 1 arrivés entre-temps.
        self._client = new_client(
            "greengrow-backend",
            settings.mqtt_backend_user,
            settings.mqtt_backend_password,
            clean_session=False,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Connexion MQTT refusée : %s", reason_code)
            return
        log.info("Connecté au broker MQTT")
        # "+" remplace un niveau : tous les sites, tous les bacs.
        client.subscribe(
            [(topics.topic("+", "+", "telemetry"), 1), (topics.topic("+", "+", "status"), 1)]
        )

    def _on_message(self, client, userdata, message):
        db = SessionLocal()
        try:
            outcome = handle_message(db, message.topic, message.payload)
            if outcome.startswith("ignored"):
                log.warning("%s -> %s", message.topic, outcome)
        except Exception:  # une erreur sur un message ne doit pas arrêter les suivants
            db.rollback()
            log.exception("Erreur en traitant %s", message.topic)
        finally:
            db.close()

    def start(self) -> None:
        settings = get_settings()
        # connect_async + loop_start : si le broker est éteint au démarrage,
        # le client réessaie tout seul jusqu'à ce qu'il revienne.
        self._client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
