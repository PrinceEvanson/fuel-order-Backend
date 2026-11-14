from sqlalchemy.orm import Session

from ..models import AuditLog, User

def log(db: Session, document_id: int, action: str, actor: User | None = None, detail: dict | None = None) -> None:
    db.add(AuditLog(
        document_id=document_id,
        actor_id=actor.id if actor else None,
        actor_name=actor.name if actor else "system",
        action=action,
        detail=detail or {},
    ))
