"""DEMO_MODE: fixtures instead of AWS, fake live instance state, seeded savings history (specs/09 §3)."""
import copy
import json
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AwsConnection, DemoInstance, RemediationAction, User
from app.pipeline import catalog, recommend

FIXTURES = Path(__file__).resolve().parents[1] / "pipeline" / "demo_fixtures.json"
DEMO_ACCOUNT = "000000000000"
EIP_INSTANCES = {"reporting-worker", "api-gateway"}


@lru_cache
def load_fixtures() -> list[dict]:
    return json.loads(FIXTURES.read_text())


def _shift_ts(rows: list[dict], delta: timedelta) -> list[dict]:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return [{**r, "ts": (datetime.strptime(r["ts"], fmt) + delta).strftime(fmt)} for r in rows]


def _fresh(f: dict) -> dict:
    """Copy of a fixture whose chart timestamps end at the current hour."""
    f = copy.deepcopy(f)
    series = f.get("hourly_series") or []
    if series:
        last = datetime.strptime(series[-1]["ts"], "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        delta = now - last
        f["hourly_series"] = _shift_ts(series, delta)
        f["mem_hourly"] = _shift_ts(f.get("mem_hourly") or [], delta)
    f.pop("demo_fail_resize", None)
    f["launch_time"] = None
    return f


def region_counts() -> list[dict]:
    counts: dict[str, int] = {}
    for f in load_fixtures():
        counts[f["region"]] = counts.get(f["region"], 0) + 1
    return [{"region": r, "instance_count": counts.get(r, 0)} for r in
            sorted({"us-east-1", "us-west-2", "eu-west-1", "ap-south-1"} | set(counts))]


def ensure_demo_instances(db: Session, conn: AwsConnection) -> None:
    existing = {d.instance_id for d in db.scalars(select(DemoInstance).where(DemoInstance.connection_id == conn.id))}
    for i, f in enumerate(load_fixtures()):
        if f["instance_id"] in existing:
            continue
        running = f.get("state") == "running"
        db.add(DemoInstance(
            connection_id=conn.id, instance_id=f["instance_id"], region=f["region"],
            instance_type=f["instance_type"], state=f.get("state") or "running", tags=f.get("tags") or {},
            cpu_credits="standard" if f["instance_type"].startswith("t") else None,
            public_ip=f"13.233.{10 + i}.{40 + i}" if running else None,
            has_eip=f["name"] in EIP_INSTANCES, fail_resize=bool(f.get("demo_fail_resize"))))
    db.flush()


def _live_override(f: dict, live: DemoInstance | None) -> dict | None:
    """Re-scans reflect what the user changed through the app (stopped / resized instances)."""
    if live is None or live.state == "terminated":
        return None
    region = f["region"]
    price_fn = lambda t: catalog.price(t, region)  # noqa: E731
    base = {k: f[k] for k in ("instance_id", "name", "region", "tags")}
    if live.state != "running":
        r = {**base, "instance_type": live.instance_type, "state": live.state, "status": "STOPPED",
             "confidence": {"score": 0.0, "band": "NONE"},
             "reason": f"state={live.state}: no live metrics (stopped instances still pay for EBS)"}
    elif live.instance_type != f["instance_type"] or (live.cpu_credits == "unlimited"
                                                      and f["suggestion"]["action"] == "ENABLE_UNLIMITED_CREDITS"):
        r = {**f, "instance_type": live.instance_type, "state": "running", "status": "ACTIVE",
             "confidence": {"score": 50.0, "band": "LOW"}, "overprovisioned": None,
             "reason": "recently changed by EC2 Optimizer; it is re-evaluated once fresh metrics exist"}
    else:
        return f
    r["suggestion"] = recommend.build(r, None, price_fn, region)
    r.setdefault("hourly_series", [])
    return r


def scan_results(db: Session, conn: AwsConnection, progress) -> list[dict]:
    ensure_demo_instances(db, conn)
    db.commit()
    live = {d.instance_id: d for d in db.scalars(select(DemoInstance).where(DemoInstance.connection_id == conn.id))}
    fixtures = load_fixtures()
    progress.discovered(len(fixtures))
    delay = min(get_settings().demo_step_delay_s, 1.0) / 4
    out = []
    for f in fixtures:
        r = _live_override(_fresh(f), live.get(f["instance_id"]))
        if r is not None:
            out.append(r)
        if delay:
            time.sleep(delay)
        progress.step()
    return out


def _hist_action(db, conn, user_id, f, action, days_ago, status="succeeded", to_type=None, undone_after_days=None,
                 error=None):
    now = datetime.now(timezone.utc)
    done = now - timedelta(days=days_ago, hours=3)
    region = f["region"]
    from_type = f["instance_type"] if action != "RESIZE" else to_type[0]
    target = None if action != "RESIZE" else to_type[1]
    p_old, p_new = catalog.price(from_type, region), catalog.price(target, region) if target else None
    hourly = {"STOP_INSTANCE": p_old, "RESIZE": (p_old - p_new) if p_new else None}.get(action)
    a = RemediationAction(
        user_id=user_id, connection_id=conn.id, instance_id=f["instance_id"], instance_name=f["name"],
        region=region, action=action, status=status,
        before={"instance_type": from_type, "state": "running", "price_hourly": p_old},
        after=({"instance_type": target or from_type, "state": "stopped" if action == "STOP_INSTANCE" else "running",
                "price_hourly": p_new} if status == "succeeded" else {}),
        options={"target_type": target} if target else {},
        steps_log=[{"ts": done.isoformat(), "step": "Seeded demo history", "status": "ok",
                    "message": "historical action created by the demo seed"}],
        error=error, hourly_saving_usd=hourly if status == "succeeded" else None,
        savings_active=status == "succeeded" and undone_after_days is None,
        requested_at=done - timedelta(minutes=4), started_at=done - timedelta(minutes=4), completed_at=done)
    db.add(a)
    db.flush()
    if undone_after_days is not None:
        ended = done + timedelta(days=undone_after_days)
        a.savings_ended_at, a.savings_end_reason, a.undone = ended, "undone in the app", True
        db.add(RemediationAction(
            user_id=user_id, connection_id=conn.id, instance_id=f["instance_id"], instance_name=f["name"],
            region=region, action="UNDO_STOP", parent_action_id=a.id, status="succeeded",
            before={"state": "stopped"}, after={"state": "running"}, steps_log=[], requested_at=ended,
            started_at=ended, completed_at=ended))
    return a


def seed_history(db: Session, conn: AwsConnection, user_id) -> None:
    """~60 days of plausible applied actions so the savings dashboard is rich from the first login."""
    by_name = {f["name"]: f for f in load_fixtures()}
    _hist_action(db, conn, user_id, by_name["web-frontend-1"], "RESIZE", 58, to_type=("m5.xlarge", "m5.large"))
    _hist_action(db, conn, user_id, by_name["legacy-reporting"], "STOP_INSTANCE", 45)
    _hist_action(db, conn, user_id, by_name["etl-scheduler"], "RESIZE", 33, to_type=("c5.2xlarge", "c5.large"))
    _hist_action(db, conn, user_id, by_name["search-indexer"], "RESIZE", 20, to_type=("t3.medium", "t3.large"))
    _hist_action(db, conn, user_id, by_name["db-replica-1"], "STOP_INSTANCE", 50, undone_after_days=2)
    _hist_action(db, conn, user_id, by_name["api-gateway"], "RESIZE", 10, status="rolled_back",
                 to_type=("c5.large", "c5.xlarge"),
                 error="InsufficientInstanceCapacity: AWS had no capacity for c5.xlarge; rolled back to c5.large")
    db.commit()
    from app.services import savings_service
    savings_service.accrue(db, connection_id=conn.id)


def create_demo_connection(db: Session, user: User) -> AwsConnection:
    from app.services.connection_service import new_external_id
    existing = db.scalar(select(AwsConnection).where(AwsConnection.user_id == user.id,
                                                     AwsConnection.aws_account_id == DEMO_ACCOUNT))
    if existing:
        return existing
    conn = AwsConnection(user_id=user.id, label="Demo account", external_id=new_external_id(),
                         role_arn=f"arn:aws:iam::{DEMO_ACCOUNT}:role/EC2OptimizerAccessRole",
                         aws_account_id=DEMO_ACCOUNT, enable_actions=True, actions_verified=True,
                         status="connected", is_demo=True, regions=[],
                         last_verified_at=datetime.now(timezone.utc))
    db.add(conn)
    db.flush()
    ensure_demo_instances(db, conn)
    db.commit()
    seed_history(db, conn, user.id)
    return conn
