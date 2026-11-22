import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.security import decode_token
from app.db import get_db
from app.models import AuditLog, AwsConnection, User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().cookie_name)
    user_id = decode_token(token) if token else None
    user = db.get(User, uuid.UUID(user_id)) if user_id else None
    if not user or not user.is_active:
        raise AppError(401, "UNAUTHORIZED", "Please log in")
    return user


def owned_connection(db: Session, user: User, connection_id) -> AwsConnection:
    try:
        cid = uuid.UUID(str(connection_id))
    except ValueError:
        raise not_found("Connection")
    conn = db.scalar(select(AwsConnection).where(AwsConnection.id == cid, AwsConnection.user_id == user.id))
    if not conn:
        raise not_found("Connection")
    return conn


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def audit(db: Session, event: str, user_id=None, connection_id=None, detail: dict | None = None,
          ip: str | None = None) -> None:
    """Append an audit row (caller commits). Never put credentials / passwords in `detail`."""
    db.add(AuditLog(event=event, user_id=user_id, connection_id=connection_id, detail=detail or {}, ip=ip))
