"""
GreenGrow — Empreintes de mots de passe
========================================
Règle absolue : on ne stocke JAMAIS un mot de passe. On stocke son empreinte
("hash"), calculée par une fonction à sens unique : facile de vérifier qu'un
mot de passe correspond, impossible de retrouver le mot de passe à partir de
l'empreinte.

Pourquoi pas un simple SHA-256 ? Parce qu'il est trop RAPIDE : un attaquant
qui vole la base peut essayer des milliards de mots de passe par seconde.
scrypt est volontairement lent et gourmand en mémoire (environ 16 Mo par
essai), ce qui rend ces essais en masse très coûteux. Il fait partie de
Python (hashlib) : aucune dépendance à installer.

Le "sel" est une valeur aléatoire propre à chaque compte : deux personnes
avec le même mot de passe ont des empreintes différentes, et un attaquant ne
peut pas préparer une table d'empreintes à l'avance.

Format stocké :  scrypt$n$r$p$sel$empreinte
Les paramètres sont rangés AVEC l'empreinte : on pourra les durcir plus tard
sans casser les comptes existants.
"""

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
KEY_LEN = 32
MIN_LENGTH = 10
MAX_LENGTH = 200  # borne haute : pas de mot de passe de 10 Mo pour saturer le serveur


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_LEN)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt" or len(password) > MAX_LENGTH:
            return False
        candidate = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        # compare_digest compare en temps constant (voir docs/etape-2-mqtt.md).
        return hmac.compare_digest(candidate, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# Empreinte d'un mot de passe que personne ne connaît. Quand l'e-mail saisi
# n'existe pas, on vérifie quand même le mot de passe contre celle-ci : la
# réponse prend le même temps, et ne révèle donc pas si le compte existe.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_strength(password: str) -> str | None:
    """Retourne la raison du refus, ou None si le mot de passe est acceptable."""
    if len(password) < MIN_LENGTH:
        return f"Le mot de passe doit faire au moins {MIN_LENGTH} caractères"
    if len(password) > MAX_LENGTH:
        return f"Le mot de passe doit faire au plus {MAX_LENGTH} caractères"
    return None
