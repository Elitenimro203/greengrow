"""
GreenGrow — Alertes sur Telegram
=================================
Quand une alerte S'OUVRE (sol trop sec, mode sécurité, réservoir vide...), le
serveur t'envoie un message Telegram. Une alerte = un message : comme les
alertes sont dédupliquées (une par problème, voir alerts.py), ton téléphone
ne sonne pas à chaque mesure.

Trois précautions :
  - l'envoi part dans un fil d'exécution séparé : si Telegram est lent ou
    en panne, l'enregistrement des mesures n'attend pas ;
  - une erreur d'envoi est journalisée, jamais propagée : une notification
    ratée ne doit pas faire perdre une mesure ;
  - le jeton du bot est un SECRET (qui le possède peut parler à la place du
    bot). Il vit dans .env et n'est jamais écrit dans les journaux.

Sans TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env, ce module ne fait rien.
"""

import logging
import threading

import httpx

from backend.config import get_settings

log = logging.getLogger("greengrow.notify")

API = "https://api.telegram.org/bot{token}/sendMessage"


def enabled() -> bool:
    settings = get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_now(text: str) -> bool:
    """Envoie un message et attend la réponse. Retourne True si Telegram l'a accepté."""
    settings = get_settings()
    try:
        response = httpx.post(
            API.format(token=settings.telegram_bot_token),
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        # On journalise le TYPE d'erreur, pas son texte : il peut contenir
        # l'adresse appelée, donc le jeton.
        log.warning("Telegram injoignable (%s)", type(exc).__name__)
        return False
    if response.status_code != 200:
        log.warning("Telegram a refusé le message (code %s)", response.status_code)
        return False
    return True


def send(text: str) -> None:
    """Envoie un message sans attendre (ne fait rien si Telegram n'est pas configuré)."""
    if not enabled():
        return
    threading.Thread(target=send_now, args=(text,), daemon=True).start()


def alert_opened(message: str) -> None:
    send(f"⚠️ GreenGrow\n{message}")
