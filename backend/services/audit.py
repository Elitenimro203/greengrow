"""
GreenGrow — Journal d'audit
============================
Une ligne par action sensible. Le jour où quelque chose d'anormal arrive
(la pompe a tourné à 3 h du matin, un seuil a changé), ce journal répond à
"qui a fait ça, et depuis où ?".

record() n'effectue pas le commit : la ligne est validée dans la MÊME
transaction que l'action qu'elle décrit. Soit les deux existent, soit aucune.
"""

from sqlalchemy.orm import Session

from backend.models.entities import AuditLog, User


def record(
    db: Session,
    action: str,
    *,
    user: User | None = None,
    actor: str | None = None,
    target: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        actor=(user.email if user else actor or "?")[:254],
        action=action,
        target=target,
        ip=ip,
        details=details or {},
    )
    db.add(entry)
    return entry
