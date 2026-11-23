from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, current_user, owned_connection
from app.core.errors import AppError
from app.db import get_db
from app.models import AwsConnection, User
from app.schemas import ConnectionCreateIn, ConnectionPatchIn, VerifyIn, connection_out
from app.services import connection_service

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
def list_connections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    conns = db.scalars(select(AwsConnection).where(AwsConnection.user_id == user.id)
                       .order_by(AwsConnection.created_at))
    return [connection_out(c) for c in conns]


@router.post("", status_code=201)
def create_connection(body: ConnectionCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = connection_service.create(db, user, body.label, body.enable_actions)
    return connection_service.wizard_payload(conn)


@router.get("/{connection_id}")
def get_connection(connection_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    out = connection_out(conn)
    if conn.status in ("pending", "broken") or not conn.actions_verified:
        out["wizard"] = connection_service.wizard_payload(conn)
    return out


@router.post("/{connection_id}/verify")
def verify(connection_id: str, body: VerifyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    result = connection_service.verify(db, conn, body.role_arn)
    return {**result, "connection": connection_out(conn)}


@router.patch("/{connection_id}")
def patch(connection_id: str, body: ConnectionPatchIn, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    extra = connection_service.update(db, conn, body.model_dump(exclude_unset=True))
    return {**connection_out(conn), **extra}


@router.get("/{connection_id}/regions")
def regions(connection_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    if conn.status != "connected":
        raise AppError(409, "CONNECTION_NOT_READY", "Verify the connection first")
    return connection_service.list_regions(db, conn)


@router.delete("/{connection_id}")
def delete(connection_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    return {"aws_cleanup": connection_service.delete(db, conn, client_ip(request))}
