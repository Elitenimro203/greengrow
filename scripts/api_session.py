"""
Connexion à l'API pour les scripts (simulateur, make_firmware_secrets).

Les scripts se connectent comme toi : avec un e-mail et un mot de passe de
propriétaire. Ils sont demandés au clavier, ou lus dans les variables
GREENGROW_EMAIL et GREENGROW_PASSWORD si tu préfères ne pas les retaper.
"""

import getpass
import os
import sys

import httpx


def open_session(api_url: str) -> httpx.Client:
    """Retourne un client HTTP connecté (il garde le cookie de session)."""
    email = os.getenv("GREENGROW_EMAIL") or input("E-mail du propriétaire : ")
    password = os.getenv("GREENGROW_PASSWORD") or getpass.getpass("Mot de passe : ")
    client = httpx.Client(base_url=api_url, timeout=10.0)
    try:
        response = client.post("/api/auth/login", json={"email": email, "password": password})
    except httpx.ConnectError:
        sys.exit("❌ API non joignable. Lance d'abord : uvicorn backend.main:app --reload")
    if response.status_code != 200:
        sys.exit(f"❌ Connexion refusée : {response.json().get('detail', response.status_code)}")
    return client
