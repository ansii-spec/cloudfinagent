"""Pydantic request bodies + response serializers (shapes from specs/07)."""
import re
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import AwsConnection, Finding, RemediationAction, Scan, User

ActionCode = Literal["STOP_INSTANCE", "TERMINATE_INSTANCE", "RESIZE", "ENABLE_UNLIMITED_CREDITS"]
REGION_RE = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d$")


# ---------------------------------------------------------------- requests
class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class AccountUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=10, max_length=256)


class DeleteAccountIn(BaseModel):
    password: str


class ConnectionCreateIn(BaseModel):
    label: str = Field(default="AWS account", max_length=100)
    enable_actions: bool = False


class VerifyIn(BaseModel):
    role_arn: str = Field(max_length=2048)


class ConnectionPatchIn(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    regions: list[str] | None = None
    scan_schedule: Literal["off", "daily", "weekly"] | None = None
    enable_actions: bool | None = None

    @field_validator("regions")
    @classmethod
    def _regions(cls, v):
        if v is not None and any(not REGION_RE.match(r) for r in v):
            raise ValueError("invalid region name")
        return v


class ScanIn(BaseModel):
    regions: list[str] | None = None

    @field_validator("regions")
    @classmethod
    def _regions(cls, v):
        if v is not None and any(not REGION_RE.match(r) for r in v):
            raise ValueError("invalid region name")
        return v


class DismissIn(BaseModel):
    until: date | None = None
    forever: bool = False
    reason: str | None = Field(default=None, max_length=500)


class PreviewIn(BaseModel):
    action: ActionCode


class ActionIn(BaseModel):
    action: ActionCode
    options: dict[str, bool] = Field(default_factory=dict)
    typed_confirmation: str | None = Field(default=None, max_length=32)


# ---------------------------------------------------------------- responses
def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(v) -> float | None:
    return None if v is None else round(float(v), 2)


def user_out(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "created_at": iso(u.created_at)}


def connection_out(c: AwsConnection) -> dict:
    return {"id": str(c.id), "label": c.label, "status": c.status, "aws_account_id": c.aws_account_id,
            "role_arn": c.role_arn, "enable_actions": c.enable_actions, "actions_verified": c.actions_verified,
            "last_error": c.last_error, "last_verified_at": iso(c.last_verified_at), "regions": c.regions or [],
            "scan_schedule": c.scan_schedule, "is_demo": c.is_demo, "created_at": iso(c.created_at)}


def scan_out(s: Scan) -> dict:
    return {"id": str(s.id), "connection_id": str(s.connection_id), "status": s.status, "trigger": s.trigger,
            "regions": s.regions or [], "progress": {"processed": s.processed_instances, "total": s.total_instances},
            "started_at": iso(s.started_at), "finished_at": iso(s.finished_at), "error": s.error,
            "summary": s.summary or {}, "created_at": iso(s.created_at)}


def finding_out(f: Finding, full: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    dismissed_until = f.dismissed_until if f.dismissed_until is None or f.dismissed_until.tzinfo else \
        f.dismissed_until.replace(tzinfo=timezone.utc)
    cooldown = f.cooldown_until if f.cooldown_until is None or f.cooldown_until.tzinfo else \
        f.cooldown_until.replace(tzinfo=timezone.utc)
    out = {
        "id": str(f.id), "scan_id": str(f.scan_id), "connection_id": str(f.connection_id),
        "instance_id": f.instance_id, "region": f.region, "name": f.name, "instance_type": f.instance_type,
        "state": f.state, "tags": f.tags or {}, "status": f.status,
        "confidence": {"score": float(f.confidence_score or 0), "band": f.confidence_band},
        "reason": f.reason, "suggestion": f.suggestion, "monthly_saving_usd": money(f.monthly_saving_usd),
        "monthly_delta_usd": money(f.monthly_delta_usd), "memory_checked": f.memory_checked,
        "has_memory_metric": f.has_memory_metric, "data_quality": f.data_quality, "hours_analyzed": f.hours_analyzed,
        "action_state": f.action_state,
        "dismissed": bool(f.dismissed_forever or (dismissed_until and dismissed_until > now)),
        "dismissed_until": iso(f.dismissed_until), "dismissed_forever": f.dismissed_forever,
        "cooldown_until": iso(f.cooldown_until) if cooldown and cooldown > now else None,
        "created_at": iso(f.created_at),
    }
    if full:
        out.update({"metrics": f.metrics, "idle": f.idle, "underprovisioned": f.underprovisioned,
                    "overprovisioned": f.overprovisioned, "evidence_steps": f.evidence_steps or [],
                    "hourly_series": f.hourly_series or [], "mem_hourly": f.mem_hourly or [],
                    "dismiss_reason": f.dismiss_reason})
    return out


def action_out(a: RemediationAction) -> dict:
    from app.services.remediation_service import REVERSIBLE
    return {"id": str(a.id), "connection_id": str(a.connection_id),
            "finding_id": str(a.finding_id) if a.finding_id else None, "instance_id": a.instance_id,
            "instance_name": a.instance_name, "region": a.region, "action": a.action,
            "parent_action_id": str(a.parent_action_id) if a.parent_action_id else None, "status": a.status,
            "before": a.before or {}, "after": a.after or {}, "options": a.options or {},
            "steps_log": a.steps_log or [], "error": a.error,
            "monthly_saving_usd": money(float(a.hourly_saving_usd) * 730) if a.hourly_saving_usd is not None else None,
            "savings_active": a.savings_active, "savings_ended_at": iso(a.savings_ended_at),
            "savings_end_reason": a.savings_end_reason, "undone": a.undone,
            "can_undo": a.action in REVERSIBLE and a.status == "succeeded" and not a.undone,
            "performed_by": a.user.name if a.user else None,
            "requested_at": iso(a.requested_at), "started_at": iso(a.started_at),
            "completed_at": iso(a.completed_at)}


def page(items: list, total: int, page_no: int, page_size: int, **extra) -> dict:
    return {"items": items, "total": total, "page": page_no, "page_size": page_size, **extra}
