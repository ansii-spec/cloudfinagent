import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, current_user, owned_connection
from app.core.errors import not_found
from app.db import get_db
from app.models import AwsConnection, RemediationAction, User
from app.schemas import action_out, page
from app.services import remediation_service

router = APIRouter(prefix="/actions", tags=["actions"])


def owned_action(db: Session, user: User, action_id: str) -> RemediationAction:
    try:
        aid = uuid.UUID(action_id)
    except ValueError:
        raise not_found("Action")
    a = db.scalar(select(RemediationAction).join(AwsConnection, AwsConnection.id == RemediationAction.connection_id)
                  .where(RemediationAction.id == aid, AwsConnection.user_id == user.id))
    if not a:
        raise not_found("Action")
    return a


@router.get("")
def list_actions(connection_id: str, status: list[str] = Query(default=[]),
                 page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(25, ge=1, le=100),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    q = select(RemediationAction).where(RemediationAction.connection_id == conn.id)
    if status:
        q = q.where(RemediationAction.status.in_(status))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(RemediationAction.requested_at.desc())
                      .offset((page_no - 1) * page_size).limit(page_size))
    return page([action_out(a) for a in rows], total, page_no, page_size)


@router.get("/{action_id}")
def get_action(action_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return action_out(owned_action(db, user, action_id))


@router.post("/{action_id}/undo", status_code=202)
def undo(action_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned_action(db, user, action_id)
    child = remediation_service.request_undo(db, user, a, client_ip(request))
    return {"action_id": str(child.id)}
