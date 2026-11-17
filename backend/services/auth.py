"""
GreenGrow — Connexion des utilisateurs
=======================================
Le principe d'une session :

  1. Tu envoies ton e-mail et ton mot de passe UNE fois (POST /api/auth/login).
  2. Le serveur tire un jeton au hasard, te le donne dans un cookie, et n'en
     garde que l'empreinte.
  3. À chaque requête suivante, ton navigateur renvoie le cookie tout seul ;
     le serveur retrouve la session à partir de l'empreinte du jeton.
  4. À la déconnexion, la session est supprimée : le jeton ne vaut plus rien.

Pourquoi une session en base plutôt qu'un jeton "autonome" (JWT) ? Parce
qu'on peut la révoquer immédiatement : supprimer la ligne suffit.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.entities import AuditLog, User, UserSession, utcnow
from backend.services import audit, passwords

ROLES = ("owner", "viewer")


class TooManyAttempts(Exception):
    """Trop de mots de passe faux : on ne vérifie même plus."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, email: str, nom: str, password: str, role: str = "viewer") -> User:
    if role not in ROLES:
        raise ValueError(f"Rôle inconnu : {role}")
    problem = passwords.check_strength(password)
    if problem:
        raise ValueError(problem)
    user = User(
        email=normalize_email(email),
        nom=nom,
        password_hash=passwords.hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    audit.record(db, "user_created", user=user, target=user.email, details={"role": role})
    db.commit()
    return user


def _token_hash(token: str) -> str:
    # Le jeton est déjà une longue valeur aléatoire : un SHA-256 simple suffit
    # (pas besoin de scrypt, il n'y a rien à "deviner").
    return hashlib.sha256(token.encode()).hexdigest()


def _recent_failures(db: Session, column, value: str) -> int:
    since = utcnow() - timedelta(minutes=get_settings().login_window_minutes)
    return db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "login_failed", AuditLog.at >= since, column == value)
    )


def login(db: Session, email: str, password: str, ip: str | None) -> tuple[User, str] | None:
    """
    Vérifie les identifiants. Retourne (utilisateur, jeton de session), ou
    None s'ils sont faux. Lève TooManyAttempts si la limite est atteinte.
    """
    settings = get_settings()
    email = normalize_email(email)

    # Le compteur d'échecs, c'est le journal d'audit lui-même : il survit à
    # un redémarrage du serveur, contrairement à un compteur en mémoire.
    if _recent_failures(db, AuditLog.actor, email[:254]) >= settings.login_max_failures or (
        ip and _recent_failures(db, AuditLog.ip, ip) >= settings.login_max_failures_per_ip
    ):
        raise TooManyAttempts

    user = db.scalar(select(User).where(User.email == email))
    stored = user.password_hash if user else passwords.DUMMY_HASH
    valid = passwords.verify_password(password, stored)

    if not (user and user.active and valid):
        audit.record(db, "login_failed", actor=email, ip=ip)
        db.commit()
        return None

    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=settings.session_hours),
        )
    )
    # Ménage : les sessions périmées ne servent plus à rien.
    db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
    audit.record(db, "login_ok", user=user, ip=ip)
    db.commit()
    return user, token


def user_for_token(db: Session, token: str | None) -> User | None:
    """L'utilisateur d'une session valide, ou None."""
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:  # SQLite oublie le fuseau : c'est de l'UTC
        expires_at = expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires_at <= utcnow() or not session.user.active:
        return None
    return session.user


def logout(db: Session, token: str | None, ip: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if session is not None:
        audit.record(db, "logout", user=session.user, ip=ip)
        db.delete(session)
        db.commit()
