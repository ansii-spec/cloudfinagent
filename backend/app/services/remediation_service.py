"""Apply / undo fixes in the user's AWS account (specs/05)."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import audit
from app.core.errors import AppError
from app.db import SessionLocal
from app.models import AwsConnection, Finding, RemediationAction, User
from app.services import pricing_service
from app.services.ec2_ops import AwsOps, OpError

log = logging.getLogger("remediation")
HOURS_PER_MONTH = 730
REVERSIBLE = {"STOP_INSTANCE": "UNDO_STOP", "RESIZE": "UNDO_RESIZE", "ENABLE_UNLIMITED_CREDITS": "UNDO_CREDITS"}
UNDO_TEXT = {
    "STOP_INSTANCE": "Start the instance again from the Actions page",
    "ENABLE_UNLIMITED_CREDITS": "Switch back to standard credits from the Actions page",
    "TERMINATE_INSTANCE": "Not reversible (only via the snapshots / AMI, which the app does not restore)",
}
MANAGED_TAG_PREFIXES = ("eks:", "aws:eks:", "elasticbeanstalk:", "aws:ecs:", "ecs:", "aws:elasticbeanstalk:")


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def make_ops(db: Session, conn: AwsConnection, region: str):
    from app.services import aws_session
    return AwsOps(aws_session.get_session(db, conn), region)


def _price(conn: AwsConnection, t: str | None, region: str) -> float | None:
    if not t:
        return None
    try:
        return pricing_service.get_price(t, region)
    except Exception:  # noqa: BLE001
        return None


def applicable_actions(f: Finding) -> list[str]:
    s = f.suggestion or {}
    acts = [s.get("action")] + list(s.get("alternative_actions") or [])
    return [a for a in acts if a and a != "NONE"]


def _target_type(f: Finding, action: str) -> str | None:
    return (f.suggestion or {}).get("to_type") if action == "RESIZE" else None


def _check_connection(conn: AwsConnection):
    if conn.status != "connected":
        raise AppError(409, "CONNECTION_NOT_READY", "The AWS connection is not connected")
    if not (conn.enable_actions and conn.actions_verified):
        raise AppError(403, "ACTIONS_DISABLED", "This connection is read-only. Enable actions and re-verify first.")


def _assess(ops, f: Finding | None, action: str, target: str | None, live: dict | None, undo: bool = False,
            iid: str | None = None):
    """Pre-checks (specs/05 §3). Returns (blockers, warnings)."""
    blockers, warnings = [], []
    iid = iid or (f.instance_id if f else None)
    if live is None:
        return ["The instance no longer exists (re-scan)"], warnings
    tags = live.get("tags") or {}
    base_action = {"UNDO_STOP": "START", "UNDO_RESIZE": "RESIZE", "UNDO_CREDITS": "CREDITS"}.get(action, action)
    expected = {"STOP_INSTANCE": ("running",), "RESIZE": ("running",), "START": ("stopped",),
                "TERMINATE_INSTANCE": ("running", "stopped"), "ENABLE_UNLIMITED_CREDITS": None, "CREDITS": None}
    exp = expected.get(base_action)
    if exp and live["state"] not in exp:
        blockers.append(f"Instance is {live['state']}; expected {' or '.join(exp)}")
    if not undo and f is not None and live["instance_type"] != f.instance_type:
        blockers.append(f"Instance type changed since the scan ({f.instance_type} → {live['instance_type']}); re-scan")
    if base_action in ("STOP_INSTANCE", "RESIZE") and ops.protection(iid, "disableApiStop"):
        blockers.append("Stop protection is enabled; disable it in AWS first")
    if base_action == "TERMINATE_INSTANCE":
        if ops.protection(iid, "disableApiTermination"):
            blockers.append("Termination protection is enabled; disable it in AWS first")
        if ops.protection(iid, "disableApiStop"):
            blockers.append("Stop protection is enabled; disable it in AWS first")
    if base_action in ("STOP_INSTANCE", "TERMINATE_INSTANCE", "RESIZE"):
        asg = ops.asg_name(iid, tags)
        if asg:
            blockers.append(f"Managed by Auto Scaling group {asg}; change the launch template instead")
        managed = [k for k in tags if k.lower().startswith(MANAGED_TAG_PREFIXES)]
        if managed:
            blockers.append(f"Managed by EKS / ECS / Elastic Beanstalk (tag {managed[0]}); change it there instead")
    if live.get("lifecycle") == "spot" and base_action in ("STOP_INSTANCE", "RESIZE"):
        blockers.append("Spot instances can't be stopped or resized")
    if base_action == "RESIZE":
        if live.get("root_device_type") != "ebs":
            blockers.append("Instance-store root volume: resizing would lose the root disk")
        if live.get("hibernation"):
            blockers.append("Hibernation is enabled; resizing is not supported")
        info = ops.type_info(target) if target else None
        if not target or info is None:
            blockers.append(f"Target type {target} is not available in {ops.region}")
        elif target.split(".")[0] != live["instance_type"].split(".")[0]:
            blockers.append("Target type is not in the same family")
        elif live.get("architecture") and live["architecture"] not in info["arch"]:
            blockers.append("Target type has a different CPU architecture")
        warnings.append("~2-5 minutes downtime (the instance is stopped and restarted)")
        if live.get("public_ip") and not ops.has_eip(iid):
            warnings.append("Public IP will change (no Elastic IP attached)")
        if f is not None and f.memory_checked is False and not undo:
            warnings.append("Memory was not monitored (lower confidence)")
    if base_action == "STOP_INSTANCE":
        warnings.append("Attached EBS volumes are still billed while the instance is stopped")
        if live.get("public_ip") and not ops.has_eip(iid):
            warnings.append("Public IP will change when the instance is started again (no Elastic IP)")
    if base_action == "TERMINATE_INSTANCE":
        warnings.append("Termination is permanent. The instance and its root volume are deleted.")
    if base_action in ("ENABLE_UNLIMITED_CREDITS", "CREDITS"):
        if not live["instance_type"].startswith("t"):
            blockers.append("Only burstable (T-family) instances have CPU credits")
        if action == "ENABLE_UNLIMITED_CREDITS":
            warnings.append("Unlimited mode can add surplus-credit charges when the average CPU exceeds the baseline")
    return blockers, warnings


def preview(db: Session, user: User, f: Finding, action: str) -> dict:
    conn = db.get(AwsConnection, f.connection_id)
    if action not in applicable_actions(f):
        raise AppError(422, "ACTION_NOT_APPLICABLE", f"{action} is not a suggested action for this finding")
    ops = make_ops(db, conn, f.region)
    target = _target_type(f, action)
    live = ops.describe(f.instance_id)
    blockers, warnings = _assess(ops, f, action, target, live)
    if not (conn.enable_actions and conn.actions_verified):
        blockers.insert(0, "This connection is read-only. Enable actions to apply fixes.")
    cur_type = live["instance_type"] if live else f.instance_type
    p_old = _price(conn, cur_type, f.region)
    p_new = {"STOP_INSTANCE": 0.0, "TERMINATE_INSTANCE": 0.0, "RESIZE": _price(conn, target, f.region),
             "ENABLE_UNLIMITED_CREDITS": p_old}.get(action)
    cur_m = round(p_old * HOURS_PER_MONTH, 2) if p_old is not None else None
    new_m = round(p_new * HOURS_PER_MONTH, 2) if p_new is not None else None
    downtime = {"STOP_INSTANCE": "The instance stays stopped until you start it again",
                "RESIZE": "~2-5 minutes (instance is stopped and restarted)",
                "TERMINATE_INSTANCE": "Permanent", "ENABLE_UNLIMITED_CREDITS": "None"}[action]
    options = {}
    if action == "RESIZE":
        options["create_backup_ami"] = {"default": True, "label": "Create a backup AMI first (no reboot)"}
    if action == "TERMINATE_INSTANCE":
        options["create_final_snapshot"] = {"default": True,
                                            "label": "Create a final snapshot of attached volumes first"}
    return {
        "action": action,
        "instance": {"id": f.instance_id, "name": f.name, "region": f.region},
        "change": {"from": cur_type, "to": target if action == "RESIZE" else
                   {"STOP_INSTANCE": "stopped", "TERMINATE_INSTANCE": "terminated",
                    "ENABLE_UNLIMITED_CREDITS": "unlimited credits"}[action]},
        "cost": {"current_monthly": cur_m, "new_monthly": new_m,
                 "monthly_delta": round(new_m - cur_m, 2) if (cur_m is not None and new_m is not None) else None},
        "downtime": downtime,
        "blockers": blockers,
        "warnings": warnings,
        "requires_typed_confirmation": action == "TERMINATE_INSTANCE",
        "options": options,
        "undo": f"Resize back to {cur_type} from the Actions page" if action == "RESIZE" else UNDO_TEXT[action],
        "estimate_note": "Estimates use Linux on-demand list prices (730 h/month).",
    }


def _rate_limited(db: Session, user: User) -> bool:
    since = _now() - timedelta(hours=1)
    n = db.scalar(select(func.count(RemediationAction.id)).where(
        RemediationAction.user_id == user.id, RemediationAction.requested_at >= since,
        RemediationAction.status != "failed")) or 0
    return n >= get_settings().action_rate_limit_per_hour


def _active_for_instance(db, conn_id, iid):
    return db.scalar(select(RemediationAction).where(
        RemediationAction.connection_id == conn_id, RemediationAction.instance_id == iid,
        RemediationAction.status.in_(("pending", "running"))))


def _enqueue(db: Session, a: RemediationAction):
    from app.workers import tasks
    res = tasks.execute_action.delay(str(a.id))
    try:
        a.celery_task_id = res.id
        db.commit()
    except Exception:  # noqa: BLE001 - eager mode / detached
        db.rollback()


def request_action(db: Session, user: User, f: Finding, action: str, options: dict | None,
                   typed_confirmation: str | None, ip: str | None = None) -> RemediationAction:
    conn = db.get(AwsConnection, f.connection_id)
    _check_connection(conn)
    if action not in applicable_actions(f):
        raise AppError(422, "ACTION_NOT_APPLICABLE", f"{action} is not a suggested action for this finding")
    if _rate_limited(db, user):
        raise AppError(429, "RATE_LIMITED", "Too many actions in the last hour (max 10). Try again later.")
    if _active_for_instance(db, conn.id, f.instance_id):
        raise AppError(409, "ACTION_IN_PROGRESS", "Another action is already running for this instance")
    if action == "TERMINATE_INSTANCE" and (typed_confirmation or "").strip() != f.instance_id:
        raise AppError(422, "CONFIRMATION_REQUIRED", "Type the instance ID to confirm termination")

    ops = make_ops(db, conn, f.region)
    target = _target_type(f, action)
    live = ops.describe(f.instance_id)
    blockers, _ = _assess(ops, f, action, target, live)
    if not blockers:
        denied = ops.dry_run(action, f.instance_id)
        if denied:
            blockers.append(denied)
    audit(db, "ACTION_REQUESTED", user.id, conn.id, {"instance_id": f.instance_id, "action": action}, ip)
    p_old = _price(conn, live["instance_type"] if live else f.instance_type, f.region)
    p_new = _price(conn, target, f.region) if target else None
    a = RemediationAction(
        user_id=user.id, connection_id=conn.id, finding_id=f.id, instance_id=f.instance_id, instance_name=f.name,
        region=f.region, action=action, status="pending",
        before={**({k: live.get(k) for k in ("state", "instance_type", "public_ip", "cpu_credits")} if live else {}),
                "eip": ops.has_eip(f.instance_id) if live else False, "price_hourly": p_old},
        options={**(options or {}), "target_type": target, "target_price_hourly": p_new})
    if blockers:
        a.status, a.error, a.completed_at = "failed", "Blocked: " + "; ".join(blockers), _now()
        db.add(a)
        audit(db, "ACTION_BLOCKED", user.id, conn.id, {"instance_id": f.instance_id, "blockers": blockers}, ip)
        db.commit()
        raise AppError(422, "ACTION_BLOCKED", "The action is blocked", {"blockers": blockers})
    db.add(a)
    f.action_state = "in_progress"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "ACTION_IN_PROGRESS", "Another action is already running for this instance")
    _enqueue(db, a)
    return a


def request_undo(db: Session, user: User, parent: RemediationAction, ip: str | None = None) -> RemediationAction:
    conn = db.get(AwsConnection, parent.connection_id)
    _check_connection(conn)
    if parent.action not in REVERSIBLE or parent.status != "succeeded" or parent.undone:
        raise AppError(409, "NOT_UNDOABLE", "This action can't be undone")
    if _active_for_instance(db, conn.id, parent.instance_id):
        raise AppError(409, "ACTION_IN_PROGRESS", "Another action is already running for this instance")
    if _rate_limited(db, user):
        raise AppError(429, "RATE_LIMITED", "Too many actions in the last hour (max 10). Try again later.")
    undo_action = REVERSIBLE[parent.action]
    ops = make_ops(db, conn, parent.region)
    live = ops.describe(parent.instance_id)
    target = (parent.before or {}).get("instance_type") if parent.action == "RESIZE" else None
    blockers, _ = _assess(ops, None, undo_action, target, live, undo=True, iid=parent.instance_id)
    if live and parent.action == "RESIZE" and live["instance_type"] != (parent.after or {}).get("instance_type"):
        blockers.append("The instance type was changed outside the app; undo is not safe")
    if blockers:
        audit(db, "ACTION_BLOCKED", user.id, conn.id, {"instance_id": parent.instance_id, "blockers": blockers}, ip)
        db.commit()
        raise AppError(422, "ACTION_BLOCKED", "The undo is blocked", {"blockers": blockers})
    a = RemediationAction(
        user_id=user.id, connection_id=conn.id, finding_id=parent.finding_id, instance_id=parent.instance_id,
        instance_name=parent.instance_name, region=parent.region, action=undo_action, parent_action_id=parent.id,
        status="pending", before={k: live.get(k) for k in ("state", "instance_type", "public_ip", "cpu_credits")},
        options={"target_type": target})
    db.add(a)
    audit(db, "ACTION_REQUESTED", user.id, conn.id, {"instance_id": parent.instance_id, "action": undo_action}, ip)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "ACTION_IN_PROGRESS", "Another action is already running for this instance")
    _enqueue(db, a)
    return a


# ------------------------------------------------------------------------------------------- execution
class _Log:
    def __init__(self, db: Session, a: RemediationAction):
        self.db, self.a = db, a

    def __call__(self, step: str, status: str = "ok", message: str = ""):
        self.a.steps_log = [*(self.a.steps_log or []),
                            {"ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "step": step, "status": status,
                             "message": message}]
        self.db.commit()


def _resize(ops, iid, original: str, target: str, log: _Log, backup: bool) -> dict:
    after = {}
    if backup:
        log("Create backup AMI", "running")
        ami = ops.create_image(iid, f"ec2opt-backup-{iid}-{int(_now().timestamp())}")
        after["backup_ami"] = ami
        log("Create backup AMI", "ok", ami)
    log("Stop instance", "running")
    ops.stop(iid)
    log("Stop instance", "ok")
    log(f"Change type {original} → {target}", "running")
    try:
        ops.modify_type(iid, target)
    except OpError as e:
        log(f"Change type {original} → {target}", "error", str(e))
        _rollback(ops, iid, original, log, modified=False)
        raise RolledBack(str(e))
    log(f"Change type {original} → {target}", "ok")
    log("Start instance", "running")
    try:
        ops.start(iid, wait_status_ok=True)
    except OpError as e:
        log("Start instance", "error", str(e))
        _rollback(ops, iid, original, log, modified=True)
        raise RolledBack(str(e))
    log("Start instance", "ok", "status checks passed")
    return after


def _rollback(ops, iid, original, log: _Log, modified: bool):
    log("Rollback", "running", f"restoring {original}")
    try:
        if modified:
            ops.modify_type(iid, original)
        ops.start(iid)
        log("Rollback", "ok", f"instance running again as {original}")
    except OpError as e:
        log("Rollback", "error", str(e))
        raise RollbackFailed(str(e))


class RolledBack(Exception):
    pass


class RollbackFailed(Exception):
    pass


def execute(action_id) -> None:
    """Celery task body: performs the steps, records before/after, savings and the finding state."""
    db = SessionLocal()
    try:
        a = db.get(RemediationAction, action_id)
        if a is None or a.status != "pending":
            return
        conn = db.get(AwsConnection, a.connection_id)
        a.status, a.started_at = "running", _now()
        db.commit()
        log = _Log(db, a)
        f = db.get(Finding, a.finding_id) if a.finding_id else None
        iid = a.instance_id
        try:
            ops = make_ops(db, conn, a.region)
            after: dict = {}
            target = (a.options or {}).get("target_type")
            if a.action == "STOP_INSTANCE":
                log("Stop instance", "running")
                ops.stop(iid)
                log("Stop instance", "ok", "instance stopped")
            elif a.action == "UNDO_STOP":
                log("Start instance", "running")
                ops.start(iid)
                log("Start instance", "ok", "instance running")
            elif a.action in ("RESIZE", "UNDO_RESIZE"):
                after = _resize(ops, iid, (a.before or {}).get("instance_type"), target, log,
                                backup=a.action == "RESIZE" and bool((a.options or {}).get("create_backup_ami")))
            elif a.action in ("ENABLE_UNLIMITED_CREDITS", "UNDO_CREDITS"):
                mode = "unlimited" if a.action == "ENABLE_UNLIMITED_CREDITS" else "standard"
                log(f"Set CPU credits to {mode}", "running")
                ops.set_credits(iid, mode)
                log(f"Set CPU credits to {mode}", "ok")
            elif a.action == "TERMINATE_INSTANCE":
                live = ops.describe(iid) or {}
                if (a.options or {}).get("create_final_snapshot", True):
                    snaps = []
                    for vol in live.get("volume_ids", []):
                        snaps.append(ops.snapshot(vol, f"ec2opt final snapshot of {iid}"))
                    after["snapshots"] = snaps
                    log("Create final snapshots", "ok", ", ".join(snaps) or "no volumes")
                log("Terminate instance", "running")
                ops.terminate(iid)
                log("Terminate instance", "ok")
            live = ops.describe(iid)
            after.update({"state": live["state"] if live else "terminated",
                          "instance_type": live["instance_type"] if live else (a.before or {}).get("instance_type"),
                          "public_ip": live.get("public_ip") if live else None,
                          "cpu_credits": live.get("cpu_credits") if live else None})
            if a.action == "RESIZE":
                after["price_hourly"] = (a.options or {}).get("target_price_hourly")
            a.after = after
            _on_success(db, a, f, ops, log)
        except RolledBack as e:
            a.status, a.error = "rolled_back", f"{e} - the instance was restored to its original type"
            if f:
                f.action_state = "failed"
        except (RollbackFailed, OpError) as e:
            a.status, a.error = "failed", str(e)
            log("Failed", "error", str(e))
            if f:
                f.action_state = "failed"
        except Exception as e:  # noqa: BLE001
            a.status, a.error = "failed", f"{type(e).__name__}: {e}"
            if f:
                f.action_state = "failed"
            logging.getLogger("remediation").exception("action %s failed", a.id)
        a.completed_at = _now()
        audit(db, "ACTION_DONE", a.user_id, a.connection_id,
              {"action_id": str(a.id), "action": a.action, "status": a.status, "instance_id": iid})
        db.commit()
    finally:
        db.close()


def _on_success(db: Session, a: RemediationAction, f: Finding | None, ops, log: _Log):
    from app.services.savings_service import end_savings
    a.status = "succeeded"
    p_old = (a.before or {}).get("price_hourly")
    p_new = (a.options or {}).get("target_price_hourly")
    if a.action in ("STOP_INSTANCE", "TERMINATE_INSTANCE") and p_old:
        a.hourly_saving_usd = p_old
    elif a.action == "RESIZE" and p_old and p_new:
        a.hourly_saving_usd = round(p_old - p_new, 6)
    elif a.action == "ENABLE_UNLIMITED_CREDITS":
        a.hourly_saving_usd = 0
    a.savings_active = bool(a.hourly_saving_usd)
    if a.parent_action_id:
        parent = db.get(RemediationAction, a.parent_action_id)
        parent.undone = True
        if parent.savings_active:
            end_savings(parent, "undone in the app")
        if f:
            f.action_state = "undone"
    elif f:
        f.action_state = "applied"
        f.cooldown_until = _now() + timedelta(days=get_settings().cooldown_days)
    if a.action != "TERMINATE_INSTANCE":
        try:
            prev = (a.before or {}).get("instance_type") or ""
            ops.tag(a.instance_id, {"ec2opt:last-action": a.action, "ec2opt:action-id": str(a.id),
                                    "ec2opt:previous-type": prev})
            log("Tag instance", "ok")
        except Exception as e:  # noqa: BLE001 - tagging is non-fatal
            log("Tag instance", "warning", f"could not tag: {e}")
    log("Done", "ok")
