"""AWS connection lifecycle: pending -> connected (verify) -> broken / disconnected (specs/03)."""
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import audit
from app.core.errors import AppError
from app.models import AwsConnection, User
from app.services import aws_session, iam_policies

DEMO_REGIONS = ["us-east-1", "ap-south-1"]


def new_external_id() -> str:
    return secrets.token_urlsafe(24)


def quick_create_url(conn: AwsConnection, enable_actions: bool | None = None) -> str:
    s = get_settings()
    ea = conn.enable_actions if enable_actions is None else enable_actions
    params = {
        "templateURL": s.cfn_template_url, "stackName": "EC2OptimizerAccess",
        "param_PlatformPrincipalArn": s.platform_principal_arn, "param_ExternalId": conn.external_id,
        "param_EnableActions": "true" if ea else "false", "param_RoleName": s.role_name,
    }
    q = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return f"https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?{q}"


def wizard_payload(conn: AwsConnection) -> dict:
    s = get_settings()
    return {
        "id": str(conn.id), "label": conn.label, "status": conn.status, "external_id": conn.external_id,
        "platform_account_id": s.platform_aws_account_id, "platform_principal_arn": s.platform_principal_arn,
        "role_name": s.role_name, "enable_actions": conn.enable_actions,
        "cloudformation_quick_create_url": quick_create_url(conn),
        "cloudformation_template_url": s.cfn_template_url,
        "manual_trust_policy_json": iam_policies.trust_policy(s.platform_principal_arn, conn.external_id),
        "manual_permissions_policy_json": iam_policies.permissions_policy(conn.enable_actions),
        "permissions": {"read_only": iam_policies.READ_ONLY_ACTIONS, "actions": iam_policies.REMEDIATION_ACTIONS},
    }


def create(db: Session, user: User, label: str, enable_actions: bool) -> AwsConnection:
    conn = AwsConnection(user_id=user.id, label=label or "AWS account", external_id=new_external_id(),
                         enable_actions=enable_actions, status="pending", regions=[])
    db.add(conn)
    db.commit()
    return conn


def verify(db: Session, conn: AwsConnection, role_arn: str) -> dict:
    account = aws_session.parse_role_arn(role_arn)
    if db.query(AwsConnection).filter(AwsConnection.user_id == conn.user_id, AwsConnection.id != conn.id,
                                      AwsConnection.aws_account_id == account).first():
        raise AppError(409, "ACCOUNT_ALREADY_CONNECTED", "This AWS account is already connected")
    if get_settings().demo_mode:
        # No AWS calls in DEMO_MODE: simulate a successful verification, backed by demo fixtures.
        from app.services import demo_service
        conn.role_arn, conn.aws_account_id = role_arn, account
        conn.status, conn.is_demo, conn.last_error = "connected", True, None
        conn.actions_verified = conn.enable_actions
        conn.last_verified_at = datetime.now(timezone.utc)
        demo_service.ensure_demo_instances(db, conn)
        db.commit()
        checks = [{"name": "AssumeRole", "ok": True, "message": "Simulated (demo mode)"},
                  {"name": "EC2 read", "ok": True, "message": ""},
                  {"name": "CloudWatch read", "ok": True, "message": ""}]
        if conn.enable_actions:
            checks.append({"name": "Actions", "ok": True, "message": ""})
        return {"status": conn.status, "checks": checks}
    return aws_session.verify(db, conn, role_arn)


def list_regions(db: Session, conn: AwsConnection, session=None) -> list[dict]:
    if conn.is_demo:
        from app.services import demo_service
        return demo_service.region_counts()
    session = session or aws_session.get_session(db, conn)
    ec2 = session.client("ec2", region_name=get_settings().platform_aws_region, config=aws_session.BOTO_CFG)
    names = sorted(r["RegionName"] for r in ec2.describe_regions()["Regions"])
    out = []
    for name in names:
        try:
            c = session.client("ec2", region_name=name, config=aws_session.BOTO_CFG)
            pages = c.get_paginator("describe_instances").paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
            n = sum(len(r["Instances"]) for p in pages for r in p["Reservations"])
        except Exception:  # noqa: BLE001 - opt-in regions etc.
            n = 0
        out.append({"region": name, "instance_count": n})
    return out


def update(db: Session, conn: AwsConnection, data: dict) -> dict:
    out = {}
    if data.get("label") is not None:
        conn.label = data["label"]
    if data.get("regions") is not None:
        conn.regions = data["regions"]
    if data.get("scan_schedule") is not None:
        conn.scan_schedule = data["scan_schedule"]
    if data.get("enable_actions") is not None and data["enable_actions"] != conn.enable_actions:
        conn.enable_actions = data["enable_actions"]
        if conn.is_demo:
            conn.actions_verified = conn.enable_actions
        else:
            conn.actions_verified = False  # must re-verify after updating the stack
        out["cloudformation_quick_create_url"] = quick_create_url(conn)
        out["manual_permissions_policy_json"] = iam_policies.permissions_policy(conn.enable_actions)
    db.commit()
    return out


def delete(db: Session, conn: AwsConnection, ip: str | None = None) -> None:
    aws_session.forget(conn)
    audit(db, "CONNECTION_DELETED", conn.user_id, None, {"aws_account_id": conn.aws_account_id}, ip)
    db.delete(conn)  # FK cascades remove scans, findings, actions, ledger, demo state
    db.commit()
