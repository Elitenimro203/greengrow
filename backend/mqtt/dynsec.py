"""
GreenGrow — Gestion des comptes du broker
==========================================
Le broker Mosquitto tient lui-même la liste des comptes et de leurs droits
(plugin "dynamic security"). On lui parle... en MQTT : on publie une commande
JSON sur un topic réservé à l'administrateur, et il répond sur un autre.

Deux notions à ne pas confondre :
  - AUTHENTIFICATION : qui es-tu ?            -> un compte (identifiant + mot de passe)
  - AUTORISATION     : qu'as-tu le droit de faire ? -> un rôle (liste de topics permis)

Chaque bac reçoit son compte ET son rôle. Par défaut tout est interdit ; le
rôle n'ouvre que les topics de CE bac.
"""

import json
import secrets
import threading

from backend.config import get_settings
from backend.mqtt import topics
from backend.mqtt.client import new_client

CONTROL = "$CONTROL/dynamic-security/v1"
RESPONSE = f"{CONTROL}/response"
TIMEOUT_S = 5


class BrokerError(RuntimeError):
    """Le broker est injoignable ou a refusé une commande d'administration."""


def run_commands(commands: list[dict], ignore_errors: tuple[str, ...] = ()) -> None:
    """Envoie des commandes d'administration au broker et vérifie ses réponses."""
    settings = get_settings()
    client = new_client(
        f"greengrow-admin-{secrets.token_hex(4)}",
        settings.mqtt_admin_user,
        settings.mqtt_admin_password,
    )
    done = threading.Event()
    result: dict = {}

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            result["error"] = f"connexion refusée : {reason_code}"
            done.set()
            return
        c.subscribe(RESPONSE, qos=1)

    def on_subscribe(c, userdata, mid, reason_codes, properties):
        c.publish(CONTROL, json.dumps({"commands": commands}), qos=1)

    def on_message(c, userdata, message):
        result["responses"] = json.loads(message.payload).get("responses", [])
        done.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=15)
    except (OSError, ValueError) as exc:  # broker éteint, certificat refusé...
        raise BrokerError(f"broker injoignable ({exc})") from exc

    client.loop_start()
    try:
        if not done.wait(TIMEOUT_S):
            raise BrokerError("le broker n'a pas répondu")
    finally:
        client.loop_stop()
        client.disconnect()

    if "error" in result:
        raise BrokerError(result["error"])
    for response in result["responses"]:
        error = response.get("error")
        if error and not any(text in error for text in ignore_errors):
            raise BrokerError(f"{response.get('command')} : {error}")


def _recreate(username: str, password: str, rolename: str, acls: list[dict]) -> None:
    """(Re)crée un compte et son rôle. Rejouable : on efface puis on recrée."""
    run_commands(
        [
            {"command": "deleteClient", "username": username},
            {"command": "deleteRole", "rolename": rolename},
        ],
        ignore_errors=("not found",),
    )
    run_commands(
        [
            {"command": "createRole", "rolename": rolename, "acls": acls},
            {
                "command": "createClient",
                "username": username,
                "password": password,
                "roles": [{"rolename": rolename}],
            },
        ]
    )


def _allow(acltype: str, topic: str) -> dict:
    return {"acltype": acltype, "topic": topic, "priority": 0, "allow": True}


def provision_bac(site: str, bac: str) -> str:
    """
    Crée (ou recrée) le compte MQTT d'un bac et retourne son mot de passe.

    Le mot de passe est généré ici, envoyé au broker qui n'en garde qu'un
    hachage, puis retourné une seule fois à l'appelant. Personne, pas même
    nous, ne peut le relire ensuite : en cas de perte, on en génère un nouveau.
    """
    password = secrets.token_urlsafe(24)
    acls = [_allow("publishClientSend", topics.topic(site, bac, ch)) for ch in topics.BAC_PUBLISH]
    acls += [_allow("subscribeLiteral", topics.topic(site, bac, ch)) for ch in topics.BAC_SUBSCRIBE]
    _recreate(bac, password, f"bac-{bac}", acls)
    return password


def ensure_backend_account() -> None:
    """Crée le compte du backend : lire tous les bacs, écrire cmd et config."""
    settings = get_settings()
    acls = [
        _allow("subscribePattern", f"{topics.ROOT}/#"),
        _allow("publishClientSend", f"{topics.ROOT}/+/+/cmd"),
        _allow("publishClientSend", f"{topics.ROOT}/+/+/config"),
    ]
    # Ici on ne supprime pas le compte s'il existe : le broker garde pour lui
    # les messages arrivés pendant que le backend était éteint, on veut les
    # retrouver. On s'assure seulement que rôle, compte et mot de passe sont bons.
    user, role = settings.mqtt_backend_user, "greengrow-backend"
    run_commands(
        [
            {"command": "createRole", "rolename": role, "acls": acls},
            {
                "command": "createClient",
                "username": user,
                "password": settings.mqtt_backend_password,
                "roles": [{"rolename": role}],
            },
            {"command": "setClientPassword", "username": user, "password": settings.mqtt_backend_password},
        ],
        ignore_errors=("already",),
    )
