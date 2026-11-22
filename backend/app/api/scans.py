import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import current_user, owned_connection
from app.core.errors import not_found
from app.db import get_db
from app.models import AwsConnection, Scan, User
from app.schemas import ScanIn, page, scan_out
from app.services import scan_service

router = APIRouter(tags=["scans"])


@router.post("/connections/{connection_id}/scans", status_code=202)
def start(connection_id: str, body: ScanIn | None = None, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    scan = scan_service.start_scan(db, conn, (body.regions if body else None), trigger="manual")
    return {"scan_id": str(scan.id)}


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        sid = uuid.UUID(scan_id)
    except ValueError:
        raise not_found("Scan")
    scan = db.scalar(select(Scan).join(AwsConnection, AwsConnection.id == Scan.connection_id)
                     .where(Scan.id == sid, AwsConnection.user_id == user.id))
    if not scan:
        raise not_found("Scan")
    return scan_out(scan)


@router.get("/connections/{connection_id}/scans")
def history(connection_id: str, page_no: int = Query(1, alias="page", ge=1),
            page_size: int = Query(20, ge=1, le=100), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    conn = owned_connection(db, user, connection_id)
    q = select(Scan).where(Scan.connection_id == conn.id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    scans = db.scalars(q.order_by(Scan.created_at.desc()).offset((page_no - 1) * page_size).limit(page_size))
    return page([scan_out(s) for s in scans], total, page_no, page_size)
