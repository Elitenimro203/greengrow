"""
GreenGrow — Prépare le fichier secrets.h d'un bac
==================================================
Lancement (API et broker démarrés, compte propriétaire créé) :

    python scripts/make_firmware_secrets.py --bac bac01 --nom "Bac pilote"

Ce script :
  1. enregistre le bac auprès de l'API (ou renouvelle son mot de passe MQTT
     s'il existe déjà : l'ancien cesse alors de fonctionner) ;
  2. lit le certificat de l'autorité certs/ca.crt ;
  3. écrit firmware/greengrow_bac/secrets.h, prêt à compiler.

secrets.h contient le mot de passe MQTT du bac : il est ignoré par Git.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.api_session import open_session  # noqa: E402

OUTPUT = ROOT / "firmware" / "greengrow_bac" / "secrets.h"

TEMPLATE = """// Fichier généré par scripts/make_firmware_secrets.py — NE PAS envoyer sur GitHub.
#pragma once

#define WIFI_SSID "{wifi_ssid}"
#define WIFI_PASSWORD "{wifi_password}"

#define MQTT_HOST "{host}"
#define MQTT_PORT {port}

#define MQTT_USERNAME "{username}"
#define MQTT_PASSWORD "{password}"
#define TOPIC_PREFIX "{topic_prefix}"

static const char CA_CERT[] PROGMEM = R"PEM(
{ca}
)PEM";
"""


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Génère secrets.h pour le firmware d'un bac")
    parser.add_argument("--bac", required=True, help="identifiant du bac, ex. bac01")
    parser.add_argument("--nom", default=None, help="nom affiché du bac")
    parser.add_argument("--site", default="abidjan")
    parser.add_argument(
        "--host", default="host.wokwi.internal",
        help="adresse du broker vue par l'ESP32 (par défaut : ton PC vu depuis Wokwi)",
    )
    parser.add_argument("--wifi-ssid", default="Wokwi-GUEST")
    parser.add_argument("--wifi-password", default="")
    parser.add_argument("--api", default=os.getenv("GREENGROW_API_URL", "http://localhost:8000"))
    args = parser.parse_args()

    ca_file = ROOT / os.getenv("MQTT_CA_FILE", "certs/ca.crt")
    if not ca_file.exists():
        sys.exit("❌ certs/ca.crt introuvable. Lance d'abord : python scripts/make_dev_certs.py")

    api = open_session(args.api)  # te demande ton e-mail et ton mot de passe
    try:
        response = api.post(
            "/api/bacs", json={"bac_id": args.bac, "nom": args.nom or args.bac, "site": args.site}
        )
        if response.status_code == 409:
            print(f"Le bac {args.bac} existe déjà : nouveau mot de passe MQTT demandé.")
            response = api.post(f"/api/bacs/{args.bac}/mqtt-credentials")
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        sys.exit(f"❌ Refusé par l'API : {exc.response.status_code} {exc.response.text}")

    body = response.json()
    creds = body.get("mqtt", body)  # création : dans "mqtt" ; renouvellement : directement
    if not creds or "password" not in creds:
        sys.exit("❌ L'API n'a pas créé de compte MQTT : vérifie MQTT_ENABLED=true dans .env")

    OUTPUT.write_text(
        TEMPLATE.format(
            wifi_ssid=args.wifi_ssid,
            wifi_password=args.wifi_password,
            host=args.host,
            port=creds["port"],
            username=creds["username"],
            password=creds["password"],
            topic_prefix=creds["topic_prefix"],
            ca=ca_file.read_text().strip(),
        ),
        encoding="utf-8",
    )
    print(f"✅ {OUTPUT.relative_to(ROOT)} écrit pour le bac {creds['username']}")
    print(f"   Broker vu par l'ESP32 : {args.host}:{creds['port']}")


if __name__ == "__main__":
    main()
