from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.cache import hit_rate_limit
from app.core.deps import audit, client_ip, current_user
from app.core.errors import AppError
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.models import User
from app.schemas import AccountUpdateIn, DeleteAccountIn, LoginIn, RegisterIn, user_out
from app.services import aws_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(resp: Response, user: User) -> None:
    s = get_settings()
    resp.set_cookie(s.cookie_name, create_token(str(user.id)), max_age=s.jwt_expiry_hours * 3600, httponly=True,
                    secure=s.is_production, samesite="lax", path="/")


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit(db, "REGISTER", user.id, ip=client_ip(request))
    db.commit()
    _set_cookie(response, user)
    return user_out(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if hit_rate_limit(f"rl:login:{client_ip(request)}:{email}", get_settings().login_rate_limit_per_min, 60):
        raise AppError(429, "RATE_LIMITED", "Too many login attempts. Wait a minute and try again.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        audit(db, "LOGIN_FAILED", None, ip=client_ip(request))
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    audit(db, "LOGIN", user.id, ip=client_ip(request))
    db.commit()
    _set_cookie(response, user)
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(get_settings().cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: AccountUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name:
        user.name = body.name.strip()
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise AppError(422, "WRONG_PASSWORD", "Current password is incorrect")
        user.password_hash = hash_password(body.new_password)
    db.commit()
    return user_out(user)


@router.delete("/me", status_code=204)
def delete_me(body: DeleteAccountIn, response: Response, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    if not verify_password(body.password, user.password_hash):
        raise AppError(422, "WRONG_PASSWORD", "Password is incorrect")
    for c in user.connections:
        aws_session.forget(c)
    db.delete(user)  # cascades: connections -> scans, findings, actions, ledger, audit rows
    db.commit()
    response.delete_cookie(get_settings().cookie_name, path="/")
    response.status_code = 204
    return response
