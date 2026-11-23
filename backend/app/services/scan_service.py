"""Orchestrates a scan: regions -> pipeline adapter -> findings rows (specs/02 §3.2)."""
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import audit
from app.core.errors import AppError
from app.db import SessionLocal
from app.models import AwsConnection, Finding, Scan
from app.pipeline.adapter import PipelineConfig, analyze_region
from app.pipeline.detector import explain_aws_error
from app.services import aws_session, pricing_service

log = logging.getLogger("scan")
REPORTED = ("IDLE", "OVER_PROVISIONED", "UNDER_PROVISIONED", "NEEDS_REVIEW")


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def start_scan(db: Session, conn: AwsConnection, regions: list[str] | None, trigger: str = "manual") -> Scan:
    if conn.status != "connected":
        raise AppError(409, "CONNECTION_NOT_READY", "Connect and verify this AWS account before scanning")
    running = db.scalar(select(Scan).where(Scan.connection_id == conn.id, Scan.status.in_(("queued", "running"))))
    if running:
        raise AppError(409, "SCAN_RUNNING", "A scan is already running for this connection",
                       {"scan_id": str(running.id)})
    scan = Scan(connection_id=conn.id, trigger=trigger, regions=regions or conn.regions or [], status="queued")
    db.add(scan)
    audit(db, "SCAN_START", conn.user_id, conn.id, {"trigger": trigger, "regions": scan.regions})
    db.commit()
    from app.workers import tasks
    tasks.run_scan.delay(str(scan.id))
    return scan


def finding_from_result(r: dict, scan: Scan, conn: AwsConnection) -> Finding:
    s = r.get("suggestion") or {}
    over = r.get("overprovisioned")
    conf = r.get("confidence") or {}
    return Finding(
        scan_id=scan.id, connection_id=conn.id, is_latest=True, instance_id=r["instance_id"],
        region=r.get("region", ""), name=r.get("name") or "", instance_type=r.get("instance_type"),
        state=r.get("state"), tags=r.get("tags") or {}, status=r["status"],
        confidence_score=conf.get("score") or 0, confidence_band=conf.get("band") or "NONE",
        reason=r.get("reason", ""), suggestion=s, monthly_saving_usd=s.get("monthly_saving_usd"),
        monthly_delta_usd=s.get("monthly_delta_usd"), metrics=r.get("metrics"), idle=r.get("idle"),
        underprovisioned=r.get("underprovisioned"), overprovisioned=over,
        evidence_steps=(over or {}).get("steps") or [], hourly_series=r.get("hourly_series") or [],
        mem_hourly=r.get("mem_hourly") or [], data_quality=r.get("data_quality"),
        hours_analyzed=r.get("hours_analyzed") or 0,
        memory_checked=(over or {}).get("memory_checked") if over else None,
        has_memory_metric=bool(r.get("has_memory_metric")))


def save_findings(db: Session, scan: Scan, conn: AwsConnection, results: list[dict]) -> dict:
    now = _now()
    prev = {f.instance_id: f for f in db.scalars(select(Finding).where(
        Finding.connection_id == conn.id, Finding.is_latest.is_(True)))}
    scanned_regions = {r.get("region") for r in results} | set(scan.regions or [])
    # instances not seen again in a scanned region are no longer "latest"
    for iid, f in prev.items():
        if f.region in scanned_regions:
            f.is_latest = False
    for r in results:
        new = finding_from_result(r, scan, conn)
        old = prev.get(r["instance_id"])
        if old is not None:
            old.is_latest = False
            # user decisions survive re-scans
            new.dismissed_forever, new.dismissed_until, new.dismiss_reason = (
                old.dismissed_forever, old.dismissed_until, old.dismiss_reason)
            if _aware(old.cooldown_until) and _aware(old.cooldown_until) > now:
                new.cooldown_until, new.action_state = old.cooldown_until, old.action_state
            elif old.action_state == "in_progress":
                new.action_state = "in_progress"
        db.add(new)
    counts: dict[str, int] = {}
    potential = 0.0
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        potential += float((r.get("suggestion") or {}).get("monthly_saving_usd") or 0)
    summary = {"counts": counts, "potential_monthly_saving": round(potential, 2), "total": len(results)}
    return summary


class _Progress:
    """Thread-safe progress counter persisted on the scan row (UI polls it)."""

    def __init__(self, scan_id):
        self.scan_id, self.lock, self.total, self.done = scan_id, threading.Lock(), 0, 0

    def _flush(self):
        with SessionLocal() as s:
            s.execute(update(Scan).where(Scan.id == self.scan_id).values(
                total_instances=self.total, processed_instances=self.done))
            s.commit()

    def discovered(self, n):
        with self.lock:
            self.total += n
            self._flush()

    def step(self, n=1):
        with self.lock:
            self.done += n
            self._flush()


def _regions_to_scan(db, conn, scan, session) -> list[str]:
    if scan.regions:
        return scan.regions
    from app.services.connection_service import list_regions
    regions = list_regions(db, conn, session=session)
    with_instances = [r["region"] for r in regions if r["instance_count"] > 0]
    return with_instances or [get_settings().platform_aws_region]


def run_scan(scan_id) -> None:
    """Celery task body."""
    db = SessionLocal()
    try:
        scan = db.get(Scan, scan_id)
        conn = db.get(AwsConnection, scan.connection_id)
        scan.status, scan.started_at = "running", _now()
        db.commit()
        progress = _Progress(scan.id)
        s = get_settings()
        cfg = PipelineConfig(lookback_hours=s.lookback_hours, min_history_hours=s.min_history_hours,
                             max_workers=s.scan_max_workers)
        platform = aws_session.platform_session()
        session = aws_session.get_session(db, conn)
        regions = _regions_to_scan(db, conn, scan, session)
        scan.regions = regions
        db.commit()
        results, failed_regions = [], []
        for region in regions:
            try:
                session = aws_session.get_session(db, conn)   # refresh between regions (long scans)
                results += analyze_region(
                    session, platform, region, cfg, on_progress=progress.step,
                    on_discovered=progress.discovered,
                    price_fn_factory=lambda pricing, r=region: pricing_service.price_fn_for(r, pricing))
            except Exception as e:  # noqa: BLE001 - one region must not kill the scan
                log.error("region %s failed: %s", region, explain_aws_error(e))
                failed_regions.append({"region": region, "error": explain_aws_error(e)})
        db.refresh(scan)
        summary = save_findings(db, scan, conn, results)
        if failed_regions:
            summary["failed_regions"] = failed_regions
        scan.summary = summary
        scan.status = "completed" if not failed_regions else ("partial" if results else "failed")
        if failed_regions and not results:
            scan.error = "; ".join(f"{f['region']}: {f['error']}" for f in failed_regions)
        scan.processed_instances, scan.total_instances = len(results), max(scan.total_instances, len(results))
        scan.finished_at = _now()
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        scan = db.get(Scan, scan_id)
        if scan:
            scan.status, scan.error, scan.finished_at = "failed", explain_aws_error(e) if not isinstance(
                e, AppError) else e.message, _now()
            db.commit()
        log.exception("scan %s failed", scan_id)
    finally:
        db.close()


def scheduled_scans() -> int:
    """Beat: daily (and Monday for weekly) scans for every connected account."""
    started = 0
    db = SessionLocal()
    try:
        weekday = _now().weekday()
        conns = db.scalars(select(AwsConnection).where(AwsConnection.status == "connected"))
        for c in conns:
            if c.scan_schedule == "daily" or (c.scan_schedule == "weekly" and weekday == 0):
                try:
                    start_scan(db, c, None, trigger="scheduled")
                    started += 1
                except AppError:
                    db.rollback()
    finally:
        db.close()
    return started
