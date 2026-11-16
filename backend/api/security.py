"""
Protection des routes sensibles par une clé d'administration.

Depuis l'étape 2, enregistrer un bac fournit des identifiants MQTT : cette
action ne peut donc plus être ouverte à tout le monde. En attendant le vrai
login (étape 4), on exige un secret partagé dans l'en-tête X-Admin-Key.
"""

import secrets

from fastapi import Header, HTTPException

from backend.config import get_settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_api_key
    if not expected:
        # Fermé par défaut : pas de clé configurée = action désactivée,
        # plutôt qu'ouverte à tous par oubli.
        raise HTTPException(503, "ADMIN_API_KEY n'est pas configurée sur le serveur")
    # compare_digest compare en temps constant : le temps de réponse ne
    # révèle pas combien de caractères de la clé étaient corrects.
    if x_admin_key is None or not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(401, "Clé d'administration absente ou incorrecte")
