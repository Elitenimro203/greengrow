from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_bac_or_404
from backend.api.security import client_ip, current_user, require_owner
from backend.models.database import get_db
from backend.models.entities import AuditLog, Bac, Command, User
from backend.models.schemas import AuditOut, CommandCreate, CommandOut
from backend.services import commands

router = APIRouter(tags=["commandes"])


@router.post("/bacs/{bac_id}/commands", response_model=CommandOut, status_code=202)
def send_command(
    payload: CommandCreate,
    request: Request,
    bac: Bac = Depends(get_bac_or_404),
    user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """
    Envoie une commande au bac. La réponse 202 veut dire "acceptée, en cours" :
    la commande est partie, mais c'est le bac qui dira s'il l'a exécutée
    (relis-la avec GET /api/bacs/{bac_id}/commands).
    """
    try:
        return commands.send(db, bac, user, payload.type, payload.duration_s, client_ip(request))
    except commands.CommandRefused as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get(
    "/bacs/{bac_id}/commands",
    response_model=list[CommandOut],
    dependencies=[Depends(current_user)],
)
def list_commands(
    bac: Bac = Depends(get_bac_or_404),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Dernières commandes d'un bac et ce qu'elles sont devenues."""
    commands.expire_stale(db)
    db.commit()
    return db.scalars(
        select(Command)
        .where(Command.bac_id == bac.id)
        .order_by(Command.created_at.desc())
        .limit(limit)
    ).all()


@router.get(
    "/audit", response_model=list[AuditOut], dependencies=[Depends(require_owner)], tags=["audit"]
)
def get_audit(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    """Journal d'audit, du plus récent au plus ancien (propriétaire uniquement)."""
    return db.scalars(select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)).all()
