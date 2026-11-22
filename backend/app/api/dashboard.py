from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import current_user, owned_connection
from app.db import get_db
from app.models import User
from app.services import savings_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(connection_id: str, range: Literal["30d", "90d", "12m", "all"] = "90d",  # noqa: A002
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    return savings_service.summary(db, conn, range)


@router.get("/spend-estimate")
def spend(connection_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    return savings_service.spend_estimate(db, conn)
