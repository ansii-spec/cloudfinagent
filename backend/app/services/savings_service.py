"""Savings ledger, daily accrual, reconcile and dashboard aggregates (specs/06)."""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AwsConnection, Finding, RemediationAction, SavingsLedger, Scan

log = logging.getLogger("savings")
HOURS_PER_MONTH = 730
SAVING_ACTIONS = ("STOP_INSTANCE", "TERMINATE_INSTANCE", "RESIZE")
POSITIVE_KINDS = ("STOP", "TERMINATE", "RESIZE_DOWN")


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def kind_of(action: RemediationAction) -> str | None:
    h = float(action.hourly_saving_usd or 0)
    return {"STOP_INSTANCE": "STOP", "TERMINATE_INSTANCE": "TERMINATE"}.get(action.action) or (
        ("RESIZE_DOWN" if h > 0 else "RESIZE_UP") if action.action == "RESIZE" else None)


def accrue_action(db: Session, a: RemediationAction, now: datetime) -> int:
    """Idempotent: (re)computes one ledger row per UTC day from completed_at up to the start of today
    (or until savings ended). Partial first/last days get partial hours; missed days are caught up."""
    hourly = float(a.hourly_saving_usd or 0)
    kind = kind_of(a)
    if not hourly or not kind or a.completed_at is None:
        return 0
    start = _aware(a.completed_at)
    end = _day_start(now.date())
    if a.savings_ended_at:
        end = min(end, _aware(a.savings_ended_at))
    if end <= start:
        return 0
    existing = {r.date: r for r in db.scalars(select(SavingsLedger).where(SavingsLedger.action_id == a.id))}
    n = 0
    day = start.date()
    while _day_start(day) < end:
        lo, hi = max(start, _day_start(day)), min(end, _day_start(day + timedelta(days=1)))
        hours = round((hi - lo).total_seconds() / 3600, 4)
        if hours > 0:
            row = existing.get(day)
            if row is None:
                row = SavingsLedger(connection_id=a.connection_id, action_id=a.id, instance_id=a.instance_id,
                                    region=a.region, date=day, kind=kind)
                db.add(row)
                n += 1
            row.hours_in_effect, row.hourly_saving_usd = hours, hourly
            row.amount_usd = round(hours * hourly, 4)
        day += timedelta(days=1)
    return n


def accrue(db: Session, connection_id=None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    q = select(RemediationAction).where(
        RemediationAction.status == "succeeded", RemediationAction.action.in_(SAVING_ACTIONS),
        or_(RemediationAction.savings_active.is_(True), RemediationAction.savings_ended_at.is_not(None)))
    if connection_id:
        q = q.where(RemediationAction.connection_id == connection_id)
    n = sum(accrue_action(db, a, now) for a in db.scalars(q))
    db.commit()
    return n


def end_savings(a: RemediationAction, reason: str, when: datetime | None = None) -> None:
    a.savings_active = False
    a.savings_ended_at = when or datetime.now(timezone.utc)
    a.savings_end_reason = reason


def reconcile(db: Session) -> int:
    """Stops accrual when the instance was changed outside the app. DEMO connections: no-op."""
    from app.services import aws_session
    from app.services.ec2_ops import AwsOps
    if get_settings().demo_mode:
        return 0
    ended = 0
    actives = db.scalars(select(RemediationAction).where(RemediationAction.savings_active.is_(True)))
    for a in actives:
        conn = db.get(AwsConnection, a.connection_id)
        if conn is None or conn.is_demo or conn.status != "connected":
            continue
        try:
            live = AwsOps(aws_session.get_session(db, conn), a.region).describe(a.instance_id)
        except Exception as e:  # noqa: BLE001
            log.warning("reconcile %s: %s", a.id, e)
            continue
        if live is None or live["state"] in ("terminated", "shutting-down"):
            if a.action != "TERMINATE_INSTANCE":
                end_savings(a, "instance no longer exists")
                ended += 1
        elif a.action == "STOP_INSTANCE" and live["state"] in ("running", "pending"):
            end_savings(a, "restarted outside the app")
            ended += 1
        elif a.action == "RESIZE" and live["instance_type"] != (a.after or {}).get("instance_type"):
            end_savings(a, "instance type changed outside the app")
            ended += 1
    db.commit()
    return ended


# ------------------------------------------------------------------------------------------- dashboard
def _range_start(rng: str, today: date) -> date | None:
    return {"30d": today - timedelta(days=30), "90d": today - timedelta(days=90),
            "12m": today - timedelta(days=365)}.get(rng)


def open_findings_q(connection_id):
    now = datetime.now(timezone.utc)
    return select(Finding).where(
        Finding.connection_id == connection_id, Finding.is_latest.is_(True),
        Finding.dismissed_forever.is_(False),
        or_(Finding.dismissed_until.is_(None), Finding.dismissed_until < now),
        Finding.action_state.in_(("none", "failed", "undone")))


def summary(db: Session, conn: AwsConnection, rng: str = "90d") -> dict:
    today = datetime.now(timezone.utc).date()
    actions = list(db.scalars(select(RemediationAction).where(RemediationAction.connection_id == conn.id)))
    active = [a for a in actions if a.savings_active and a.status == "succeeded"]
    run_rate = sum(float(a.hourly_saving_usd) for a in active if (a.hourly_saving_usd or 0) > 0) * HOURS_PER_MONTH
    invested = -sum(float(a.hourly_saving_usd) for a in active if (a.hourly_saving_usd or 0) < 0) * HOURS_PER_MONTH

    ledger = list(db.scalars(select(SavingsLedger).where(SavingsLedger.connection_id == conn.id)
                             .order_by(SavingsLedger.date)))
    positive = [r for r in ledger if r.kind in POSITIVE_KINDS]
    cumulative = sum(float(r.amount_usd) for r in positive)
    this_month = sum(float(r.amount_usd) for r in positive if r.date.year == today.year and r.date.month == today.month)

    latest = list(db.scalars(select(Finding).where(Finding.connection_id == conn.id, Finding.is_latest.is_(True))))
    open_f = list(db.scalars(open_findings_q(conn.id)))
    potential = sum(float(f.monthly_saving_usd or 0) for f in open_f if f.status in ("IDLE", "OVER_PROVISIONED"))
    counts = {k: 0 for k in ("idle", "over_provisioned", "under_provisioned", "needs_review", "active", "stopped",
                             "insufficient_data", "error")}
    for f in latest:
        counts[f.status.lower()] = counts.get(f.status.lower(), 0) + 1

    # time series (daily + cumulative over the selected range, cumulative includes earlier savings)
    start = _range_start(rng, today)
    daily: dict[date, float] = {}
    for r in positive:
        daily[r.date] = daily.get(r.date, 0.0) + float(r.amount_usd)
    series, running = [], 0.0
    if daily:
        first = min(daily)
        d = first if start is None else min(start, first) if start < first else start
        running = sum(v for k, v in daily.items() if k < d)
        while d < today:
            running += daily.get(d, 0.0)
            series.append({"date": d.isoformat(), "daily": round(daily.get(d, 0.0), 2), "cumulative": round(running, 2)})
            d += timedelta(days=1)

    by_kind: dict[str, float] = {}
    for r in ledger:
        by_kind[r.kind] = by_kind.get(r.kind, 0.0) + float(r.amount_usd)
    by_action = [{"kind": k, "amount": round(v if k in POSITIVE_KINDS else -v, 2)} for k, v in sorted(
        by_kind.items(), key=lambda kv: -abs(kv[1]))]

    cum_by_action: dict = {}
    for r in ledger:
        cum_by_action[r.action_id] = cum_by_action.get(r.action_id, 0.0) + float(r.amount_usd)
    top = []
    for a in actions:
        if a.status != "succeeded" or a.action not in SAVING_ACTIONS or (a.hourly_saving_usd or 0) <= 0:
            continue
        top.append({"action_id": str(a.id), "instance_id": a.instance_id, "name": a.instance_name,
                    "kind": kind_of(a), "from": (a.before or {}).get("instance_type"),
                    "to": (a.after or {}).get("instance_type") if a.action == "RESIZE" else None,
                    "monthly_run_rate": round(float(a.hourly_saving_usd) * HOURS_PER_MONTH, 2) if a.savings_active
                    else 0.0, "cumulative": round(cum_by_action.get(a.id, 0.0), 2),
                    "since": _aware(a.completed_at).date().isoformat() if a.completed_at else None,
                    "active": a.savings_active})
    top.sort(key=lambda x: -x["cumulative"])

    last_scan = db.scalar(select(Scan).where(Scan.connection_id == conn.id, Scan.status.in_(("completed", "partial")))
                          .order_by(Scan.finished_at.desc()))
    spend = spend_estimate(db, conn)
    return {
        "currency": "USD",
        "realized": {"monthly_run_rate": round(run_rate, 2), "cumulative": round(cumulative, 2),
                     "this_month": round(this_month, 2)},
        "potential": {"monthly": round(potential, 2), "open_findings": sum(
            1 for f in open_f if f.status in ("IDLE", "OVER_PROVISIONED", "UNDER_PROVISIONED", "NEEDS_REVIEW"))},
        "invested": {"monthly": round(invested, 2)},
        "counts": counts,
        "actions": {"applied": sum(1 for a in actions if a.status == "succeeded" and not a.action.startswith("UNDO")),
                    "undone": sum(1 for a in actions if a.undone),
                    "failed": sum(1 for a in actions if a.status in ("failed", "rolled_back"))},
        "timeseries": series,
        "by_action": by_action,
        "top_instances": top[:10],
        "spend": {"current_monthly": spend["current_monthly"],
                  "before_monthly": round(spend["current_monthly"] + run_rate - invested, 2)},
        "last_scan_at": _aware(last_scan.finished_at).strftime("%Y-%m-%dT%H:%M:%SZ") if last_scan else None,
    }


def spend_estimate(db: Session, conn: AwsConnection) -> dict:
    """List-price estimate of current EC2 compute spend (latest scan, adjusted for applied actions). Not a bill."""
    latest = list(db.scalars(select(Finding).where(Finding.connection_id == conn.id, Finding.is_latest.is_(True))))
    active = {a.instance_id: a for a in db.scalars(select(RemediationAction).where(
        RemediationAction.connection_id == conn.id, RemediationAction.savings_active.is_(True)))}
    total, items = 0.0, []
    for f in latest:
        s = f.suggestion or {}
        hourly = s.get("current_hourly_usd")
        running = f.state == "running"
        a = active.get(f.instance_id)
        if a and a.action in ("STOP_INSTANCE", "TERMINATE_INSTANCE"):
            running = False
        elif a and a.action == "RESIZE" and (a.after or {}).get("instance_type") != f.instance_type:
            hourly = (a.after or {}).get("price_hourly", hourly)
        if running and hourly:
            total += hourly * HOURS_PER_MONTH
            items.append({"instance_id": f.instance_id, "monthly": round(hourly * HOURS_PER_MONTH, 2)})
    return {"current_monthly": round(total, 2), "instances": items,
            "note": "Linux on-demand list-price estimate (730 h/month); not your AWS bill."}
