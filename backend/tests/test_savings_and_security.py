import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import SessionLocal
from app.models import AwsConnection, RemediationAction, SavingsLedger, User
from app.services import iam_policies, savings_service

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc


def _action(db, completed, hourly=0.1, action="STOP_INSTANCE", ended=None):
    u = User(email=f"{completed.timestamp()}@x.io", name="x", password_hash="x")
    db.add(u)
    db.flush()
    c = AwsConnection(user_id=u.id, external_id=f"e{completed.timestamp()}", status="connected")
    db.add(c)
    db.flush()
    a = RemediationAction(user_id=u.id, connection_id=c.id, instance_id="i-0123456789abcdef0", region="us-east-1",
                          action=action, status="succeeded", hourly_saving_usd=hourly, savings_active=ended is None,
                          savings_ended_at=ended, completed_at=completed, before={}, after={})
    db.add(a)
    db.commit()
    return c, a


def _rows(db, a):
    return sorted(db.query(SavingsLedger).filter_by(action_id=a.id), key=lambda r: r.date)


def test_partial_first_day_and_catch_up():
    now = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    with SessionLocal() as db:
        _, a = _action(db, datetime(2026, 11, 7, 18, 0, tzinfo=UTC))
        savings_service.accrue(db, now=now)
        rows = _rows(db, a)
        assert [float(r.hours_in_effect) for r in rows] == [6, 24, 24]      # 7th partial, 8th, 9th
        assert abs(sum(float(r.amount_usd) for r in rows) - 54 * 0.1) < 1e-6
        savings_service.accrue(db, now=now)                                    # idempotent
        assert len(_rows(db, a)) == 3


def test_undo_mid_day_stops_accrual():
    with SessionLocal() as db:
        _, a = _action(db, datetime(2026, 11, 7, 0, 0, tzinfo=UTC), ended=datetime(2026, 11, 8, 12, 0, tzinfo=UTC))
        savings_service.accrue(db, now=datetime(2026, 11, 12, tzinfo=UTC))
        assert [float(r.hours_in_effect) for r in _rows(db, a)] == [24, 12]


def test_upsize_never_reduces_headline():
    with SessionLocal() as db:
        c, down = _action(db, datetime.now(UTC) - timedelta(days=5), hourly=0.2, action="RESIZE")
        up = RemediationAction(user_id=down.user_id, connection_id=c.id, instance_id="i-0123456789abcdef1",
                               region="us-east-1", action="RESIZE", status="succeeded", hourly_saving_usd=-0.05,
                               savings_active=True, completed_at=datetime.now(UTC) - timedelta(days=5))
        db.add(up)
        db.commit()
        savings_service.accrue(db)
        s = savings_service.summary(db, c, "all")
        down_total = sum(float(r.amount_usd) for r in _rows(db, down))
        assert abs(s["realized"]["cumulative"] - down_total) < 0.01
        assert s["invested"]["monthly"] == round(0.05 * 730, 2)
        assert s["realized"]["monthly_run_rate"] == round(0.2 * 730, 2)


def test_iam_policies_match_cloudformation():
    tpl = (ROOT / "aws" / "cloudformation-role.yaml").read_text()
    in_tpl = set(re.findall(r"-\s+((?:ec2|autoscaling|cloudwatch):\w+)", tpl))
    assert in_tpl == set(iam_policies.READ_ONLY_ACTIONS) | set(iam_policies.REMEDIATION_ACTIONS)


def test_no_access_keys_in_code():
    pattern = re.compile(r"AKIA[0-9A-Z]{16}")
    for p in list((ROOT / "backend" / "app").rglob("*.py")) + list((ROOT / "frontend" / "src").rglob("*.ts*")):
        assert not pattern.search(p.read_text(errors="ignore")), p
