import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_role
from ..models import SageToken, User
from ..security import create_token, decode_token
from ..services import catalog, sage_client

router = APIRouter(prefix="/api/sage", tags=["sage"])


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    row = db.get(SageToken, 1)
    return {"connected": bool(row), "connected_by": row.connected_by if row else None,
            "catalog_source": "sage" if row else "sample"}


@router.get("/connect-url")
def connect_url(user: User = Depends(require_role("reviewer"))):

    state = create_token(user.id, user.role, minutes=10, purpose="sage_oauth")
    try:
        return {"url": sage_client.authorize_url(state)}
    except sage_client.SageError as e:
        raise HTTPException(500, str(e))


@router.get("/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)):
    back = f"{settings.FRONTEND_URL}/reviewer"
    if error or not code or not state:
        return RedirectResponse(f"{back}?sage=error&reason={error or 'missing_code'}")
    try:
        payload = decode_token(state, purpose="sage_oauth")
        user = db.get(User, int(payload["sub"]))
        if not user or user.role != "reviewer":
            raise jwt.InvalidTokenError("not a reviewer")
        sage_client.exchange_code(db, code, connected_by=user.name)
        catalog.clear_cache()
    except (jwt.PyJWTError, sage_client.SageError):
        return RedirectResponse(f"{back}?sage=error&reason=exchange_failed")
    return RedirectResponse(f"{back}?sage=connected")
