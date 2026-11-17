from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.api.security import SESSION_COOKIE, client_ip, current_user
from backend.config import get_settings
from backend.models.database import get_db
from backend.models.entities import User
from backend.models.schemas import LoginRequest, UserOut
from backend.services import auth

router = APIRouter(prefix="/auth", tags=["connexion"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Ouvre une session. Le jeton part dans un cookie, jamais dans la réponse."""
    settings = get_settings()
    try:
        result = auth.login(db, payload.email, payload.password, client_ip(request))
    except auth.TooManyAttempts:
        raise HTTPException(
            429,
            f"Trop de tentatives. Réessaie dans {settings.login_window_minutes} minutes.",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )
    if result is None:
        # Même message que l'e-mail existe ou non : on ne dit pas à un
        # inconnu quels comptes existent.
        raise HTTPException(401, "E-mail ou mot de passe incorrect")

    user, token = result
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,  # invisible pour le JavaScript : un script injecté ne peut pas le voler
        samesite="strict",  # jamais joint aux requêtes venues d'un autre site
        secure=settings.is_production,  # en production : uniquement en HTTPS
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.logout(db, request.cookies.get(SESSION_COOKIE), client_ip(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    """Qui suis-je ? Sert au tableau de bord pour savoir quoi afficher."""
    return user
