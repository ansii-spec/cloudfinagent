"""AWS connection lifecycle: pending -> connected (verify) -> broken / disconnected (specs/03)."""
import secrets
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import audit
from app.core.errors import AppError
from app.models import AwsConnection, User
from app.services import aws_session, iam_policies

def new_external_id() -> str:
    return secrets.token_urlsafe(24)


def _suffix(conn: AwsConnection) -> str:
    return str(conn.id).replace("-", "")[:8]


def role_name_for(conn: AwsConnection) -> str:
    """Unique per connection, so a role left behind by an earlier connection never blocks a reconnect."""
    return f"{get_settings().role_name}-{_suffix(conn)}"


def stack_name_for(conn: AwsConnection) -> str:
    if conn.role_arn:  # connections made before per-connection names used the plain stack name
        rn = conn.role_arn.rsplit("/", 1)[-1]
        if rn.startswith(get_settings().role_name + "-"):
            return f"EC2OptimizerAccess-{rn.rsplit('-', 1)[-1]}"
        return "EC2OptimizerAccess"
    return f"EC2OptimizerAccess-{_suffix(conn)}"


def aws_cleanup(conn: AwsConnection) -> dict:
    """What the user must delete in their own AWS account (the app has no permission to do it)."""
    stack = stack_name_for(conn)
    return {"stack_name": stack, "role_name": conn.role_arn.rsplit("/", 1)[-1] if conn.role_arn else role_name_for(conn),
            "console_url": "https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks?"
                           f"filteringText={quote(stack, safe='')}&filteringStatus=active&viewNested=true"}


def quick_create_url(conn: AwsConnection, enable_actions: bool | None = None) -> str:
    s = get_settings()
    ea = conn.enable_actions if enable_actions is None else enable_actions
    params = {
        "templateURL": s.cfn_template_url, "stackName": stack_name_for(conn),
        "param_PlatformPrincipalArn": s.platform_principal_arn, "param_ExternalId": conn.external_id,
        "param_EnableActions": "true" if ea else "false", "param_RoleName": role_name_for(conn),
    }
    q = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return f"https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?{q}"


def wizard_payload(conn: AwsConnection) -> dict:
    s = get_settings()
    return {
        "id": str(conn.id), "label": conn.label, "status": conn.status, "external_id": conn.external_id,
        "platform_account_id": s.platform_aws_account_id, "platform_principal_arn": s.platform_principal_arn,
        "role_name": role_name_for(conn), "stack_name": stack_name_for(conn), "enable_actions": conn.enable_actions,
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
    return aws_session.verify(db, conn, role_arn)


def list_regions(db: Session, conn: AwsConnection, session=None) -> list[dict]:
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
        conn.actions_verified = False  # must re-verify after updating the stack
        out["cloudformation_quick_create_url"] = quick_create_url(conn)
        out["manual_permissions_policy_json"] = iam_policies.permissions_policy(conn.enable_actions)
    db.commit()
    return out


def delete(db: Session, conn: AwsConnection, ip: str | None = None) -> dict | None:
    cleanup = aws_cleanup(conn)
    aws_session.forget(conn)
    audit(db, "CONNECTION_DELETED", conn.user_id, None, {"aws_account_id": conn.aws_account_id}, ip)
    db.delete(conn)  # FK cascades remove scans, findings, actions, ledger
    db.commit()
    return cleanup
