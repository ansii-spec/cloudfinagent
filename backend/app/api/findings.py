import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, current_user, owned_connection
from app.core.errors import AppError, not_found
from app.db import get_db
from app.models import AwsConnection, Finding, RemediationAction, User
from app.pipeline.detector import STATUS_ORDER
from app.schemas import ActionIn, DismissIn, PreviewIn, action_out, finding_out, page
from app.services import remediation_service

router = APIRouter(tags=["findings"])
SAVING_STATUSES = ("IDLE", "OVER_PROVISIONED")


def owned_finding(db: Session, user: User, finding_id: str) -> Finding:
    try:
        fid = uuid.UUID(finding_id)
    except ValueError:
        raise not_found("Finding")
    f = db.scalar(select(Finding).join(AwsConnection, AwsConnection.id == Finding.connection_id)
                  .where(Finding.id == fid, AwsConnection.user_id == user.id))
    if not f:
        raise not_found("Finding")
    return f


@router.get("/findings")
def list_findings(
    connection_id: str,
    status: list[str] = Query(default=[]),
    region: list[str] = Query(default=[]),
    band: list[str] = Query(default=[]),
    q: str | None = None,
    sort: str = "severity",
    include_dismissed: bool = False,
    only_dismissed: bool = False,
    page_no: int = Query(1, alias="page", ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    conn = owned_connection(db, user, connection_id)
    now = datetime.now(timezone.utc)
    base = select(Finding).where(Finding.connection_id == conn.id, Finding.is_latest.is_(True))
    dismissed = or_(Finding.dismissed_forever.is_(True),
                    and_(Finding.dismissed_until.is_not(None), Finding.dismissed_until > now))
    visible = base.where(~dismissed) if not (include_dismissed or only_dismissed) else (
        base.where(dismissed) if only_dismissed else base)

    # summary over all visible (unfiltered) findings
    all_visible = list(db.scalars(base.where(~dismissed)))
    counts: dict[str, int] = {}
    for f in all_visible:
        counts[f.status] = counts.get(f.status, 0) + 1
    potential = sum(float(f.monthly_saving_usd or 0) for f in all_visible
                    if f.status in SAVING_STATUSES and f.action_state in ("none", "failed", "undone"))
    regions = sorted({f.region for f in all_visible})

    filt = visible
    if status:
        filt = filt.where(Finding.status.in_(status))
    if region:
        filt = filt.where(Finding.region.in_(region))
    if band:
        filt = filt.where(Finding.confidence_band.in_(band))
    if q:
        like = f"%{q.lower()}%"
        filt = filt.where(or_(func.lower(Finding.name).like(like), func.lower(Finding.instance_id).like(like),
                              func.lower(Finding.instance_type).like(like)))
    severity = case(*[(Finding.status == k, v) for k, v in STATUS_ORDER.items()], else_=9)
    order = {
        "severity": (severity, Finding.confidence_score.desc()),
        "saving": (Finding.monthly_saving_usd.desc().nulls_last(), severity),
        "confidence": (Finding.confidence_score.desc(), severity),
        "name": (Finding.name, Finding.instance_id),
    }.get(sort, (severity, Finding.confidence_score.desc()))
    total = db.scalar(select(func.count()).select_from(filt.subquery()))
    rows = db.scalars(filt.order_by(*order, Finding.instance_id).offset((page_no - 1) * page_size).limit(page_size))
    return page([finding_out(f) for f in rows], total, page_no, page_size,
                summary={"counts": counts, "potential_monthly_saving": round(potential, 2), "regions": regions,
                         "dismissed": sum(1 for _ in db.scalars(base.where(dismissed)))})


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_finding(db, user, finding_id)
    out = finding_out(f, full=True)
    history = db.scalars(select(RemediationAction).where(
        RemediationAction.connection_id == f.connection_id, RemediationAction.instance_id == f.instance_id)
        .order_by(RemediationAction.requested_at.desc()).limit(20))
    out["actions"] = [action_out(a) for a in history]
    return out


@router.post("/findings/{finding_id}/dismiss")
def dismiss(finding_id: str, body: DismissIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_finding(db, user, finding_id)
    if not body.forever and body.until is None:
        raise AppError(422, "VALIDATION_ERROR", "Choose a date or 'forever'")
    f.dismissed_forever = body.forever
    f.dismissed_until = None if body.forever else datetime.combine(body.until, time.max, tzinfo=timezone.utc)
    f.dismiss_reason = body.reason
    db.commit()
    return finding_out(f)


@router.post("/findings/{finding_id}/undismiss")
def undismiss(finding_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_finding(db, user, finding_id)
    f.dismissed_forever, f.dismissed_until, f.dismiss_reason = False, None, None
    db.commit()
    return finding_out(f)


@router.post("/findings/{finding_id}/actions/preview")
def preview(finding_id: str, body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_finding(db, user, finding_id)
    return remediation_service.preview(db, user, f, body.action)


@router.post("/findings/{finding_id}/actions", status_code=202)
def apply(finding_id: str, body: ActionIn, request: Request, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    f = owned_finding(db, user, finding_id)
    a = remediation_service.request_action(db, user, f, body.action, body.options, body.typed_confirmation,
                                           client_ip(request))
    return {"action_id": str(a.id)}
