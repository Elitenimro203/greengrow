"""
GreenGrow — Convention des topics MQTT
=======================================
Tous les topics suivent le même schéma :

    greengrow/{site}/{bac}/{canal}

    telemetry  bac -> serveur   les mesures (JSON), QoS 1
    status     bac -> serveur   "online" / "offline", retenu, avec Last Will
    event      bac -> serveur   pompe démarrée, accusé de commande... (étape 3)
    cmd        serveur -> bac   commandes (étape 4)
    config     serveur -> bac   seuils et réglages, retenu (étape 3)
"""

import re
from dataclasses import dataclass

ROOT = "greengrow"
BAC_PUBLISH = ("telemetry", "status", "event")  # ce qu'un bac a le droit d'envoyer
BAC_SUBSCRIBE = ("cmd", "config")               # ce qu'un bac a le droit de recevoir

_SLUG = r"[a-z0-9][a-z0-9_-]{1,49}"
_TOPIC = re.compile(rf"^{ROOT}/({_SLUG})/({_SLUG})/([a-z]+)$")


@dataclass(frozen=True)
class BacTopic:
    site: str
    bac: str
    channel: str


def topic(site: str, bac: str, channel: str) -> str:
    return f"{ROOT}/{site}/{bac}/{channel}"


def parse(raw: str) -> BacTopic | None:
    """Découpe un topic reçu. None s'il ne respecte pas la convention."""
    match = _TOPIC.match(raw)
    return BacTopic(*match.groups()) if match else None
