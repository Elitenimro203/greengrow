"""
GreenGrow — Qui a le droit de faire quoi
=========================================
Trois "gardiens" que les routes déclarent avec Depends(...) :

  current_user   -> il faut être connecté (n'importe quel rôle)
  require_owner  -> il faut être connecté ET avoir le rôle "owner"
  check_origin   -> la requête doit venir de NOTRE site (voir plus bas)

Deux codes de refus à ne pas confondre :
  401  "je ne sais pas qui tu es"            -> connecte-toi
  403  "je sais qui tu es, et c'est non"     -> ton rôle ne le permet pas

Cette connexion remplace la clé X-Admin-Key des étapes 2 et 3.
"""

from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.database import get_db
from backend.models.entities import User
from backend.services import auth

SESSION_COOKIE = "greengrow_session"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def check_origin(request: Request) -> None:
    """
    Protection contre le CSRF : un site malveillant ouvert dans un autre
    onglet pourrait faire envoyer une requête par TON navigateur, qui
    joindrait ton cookie de session. Deux barrières :
      - le cookie est SameSite=Strict : le navigateur ne le joint pas aux
        requêtes lancées depuis un autre site ;
      - ici, on refuse toute requête de modification dont l'en-tête Origin
        (posé par le navigateur, impossible à falsifier depuis une page web)
        n'est ni l'adresse de l'API elle-même ni une origine autorisée.
    Un script (simulateur, tests) n'envoie pas d'Origin : il n'est pas concerné.
    """
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    same_host = urlsplit(origin).netloc == request.headers.get("host")
    if not same_host and origin not in get_settings().cors_origin_list:
        raise HTTPException(403, "Requête refusée : origine non autorisée")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = auth.user_for_token(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Connexion requise")
    return user


def require_owner(user: User = Depends(current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(403, "Action réservée au propriétaire")
    return user
