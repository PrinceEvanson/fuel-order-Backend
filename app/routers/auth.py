import hmac
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class LoginIn(BaseModel):
    email: str
    password: str

class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    role: str = "client"
    invite_code: str = ""

def _user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role}

@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == body.email.strip().lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token(user.id, user.role), "user": _user_out(user)}

@router.post("/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    name = body.name.strip()
    email = body.email.strip().lower()
    if len(name) < 2 or len(name) > 100:
        raise HTTPException(422, "Enter your name (2 to 100 characters).")
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters.")
    if body.role not in ("client", "reviewer"):
        raise HTTPException(422, "Unknown account type.")
    if body.role == "reviewer":
        code = settings.REVIEWER_INVITE_CODE
        if not code:
            raise HTTPException(403, "Reviewer sign-up is switched off on this server.")
        if not hmac.compare_digest(body.invite_code.strip().encode(), code.strip().encode()):
            raise HTTPException(403, "Wrong reviewer invite code.")
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, name=name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id, user.role), "user": _user_out(user)}

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
