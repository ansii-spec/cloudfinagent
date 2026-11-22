"""Cross-account access: STS AssumeRole + External ID, encrypted temp-credential cache (specs/03 §4).

Temporary credentials live ONLY in Redis (Fernet-encrypted, TTL <= expiry). Never in Postgres or logs."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.cache import get_cache
from app.core.deps import audit
from app.core.errors import AppError
from app.core.security import fernet
from app.models import AwsConnection
from app.pipeline.detector import explain_aws_error

log = logging.getLogger("aws_session")
ARN_RE = re.compile(r"^arn:aws:iam::(\d{12}):role/[\w+=,.@/-]+$")
BOTO_CFG = Config(retries={"max_attempts": 10, "mode": "adaptive"}, connect_timeout=5, read_timeout=30)
REFRESH_MARGIN = timedelta(minutes=5)


class ConnectionBroken(AppError):
    def __init__(self, message: str):
        super().__init__(409, "CONNECTION_BROKEN", message)


def _no_aws_in_demo():
    if get_settings().demo_mode:
        raise RuntimeError("DEMO_MODE: AWS calls are disabled")


def platform_session() -> boto3.Session:
    """OUR identity: dev keys from env, otherwise the default chain (instance / task role)."""
    _no_aws_in_demo()
    s = get_settings()
    if s.platform_aws_access_key_id and s.platform_aws_secret_access_key:
        return boto3.Session(aws_access_key_id=s.platform_aws_access_key_id,
                             aws_secret_access_key=s.platform_aws_secret_access_key,
                             region_name=s.platform_aws_region)
    return boto3.Session(region_name=s.platform_aws_region)


def parse_role_arn(role_arn: str) -> str:
    m = ARN_RE.match(role_arn.strip())
    if not m:
        raise AppError(422, "INVALID_ROLE_ARN", "That is not a valid IAM role ARN "
                                                "(expected arn:aws:iam::<12 digits>:role/<name>)")
    return m.group(1)


def assume_role(conn: AwsConnection, role_arn: str) -> dict:
    sts = platform_session().client("sts", config=BOTO_CFG)
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=f"ec2opt-{str(conn.user_id)[:8]}-{str(conn.id)[:8]}",
                           ExternalId=conn.external_id, DurationSeconds=3600)
    c = resp["Credentials"]
    exp = c["Expiration"]
    exp = exp if isinstance(exp, datetime) else datetime.fromisoformat(str(exp))
    return {"aws_access_key_id": c["AccessKeyId"], "aws_secret_access_key": c["SecretAccessKey"],
            "aws_session_token": c["SessionToken"], "expiration": exp.astimezone(timezone.utc).isoformat()}


def _cache_key(conn: AwsConnection) -> str:
    return f"awscreds:{conn.id}"


def _store(conn: AwsConnection, creds: dict) -> None:
    exp = datetime.fromisoformat(creds["expiration"])
    ttl = int((exp - datetime.now(timezone.utc)).total_seconds())
    if ttl > 0:
        get_cache().set(_cache_key(conn), fernet().encrypt(json.dumps(creds).encode()).decode(), ex=ttl)


def _load(conn: AwsConnection) -> dict | None:
    raw = get_cache().get(_cache_key(conn))
    if not raw:
        return None
    try:
        creds = json.loads(fernet().decrypt(raw.encode()))
    except Exception:  # noqa: BLE001 - corrupt / key rotated
        return None
    if datetime.fromisoformat(creds["expiration"]) - datetime.now(timezone.utc) < REFRESH_MARGIN:
        return None
    return creds


def forget(conn: AwsConnection) -> None:
    get_cache().delete(_cache_key(conn))


def mark_broken(db: Session, conn: AwsConnection, message: str) -> None:
    conn.status, conn.last_error = "broken", message
    audit(db, "ASSUME_ROLE_FAIL", conn.user_id, conn.id, {"error": message})
    db.commit()


def get_session(db: Session, conn: AwsConnection) -> boto3.Session:
    """boto3 Session on cached temporary credentials; re-assumes when < 5 min remain."""
    _no_aws_in_demo()
    if conn.is_demo:
        raise RuntimeError("demo connections never call AWS")
    if not conn.role_arn or conn.status not in ("connected", "broken"):
        raise ConnectionBroken("This AWS connection is not verified yet")
    creds = _load(conn)
    if creds is None:
        try:
            creds = assume_role(conn, conn.role_arn)
        except ClientError as e:
            msg = explain_aws_error(e, "AssumeRole")
            if e.response.get("Error", {}).get("Code") == "AccessDenied":
                mark_broken(db, conn, msg)
            raise ConnectionBroken(msg) from e
        _store(conn, creds)
        if conn.status == "broken":
            conn.status, conn.last_error = "connected", None
        audit(db, "ASSUME_ROLE_OK", conn.user_id, conn.id, {})
        db.commit()
    return boto3.Session(aws_access_key_id=creds["aws_access_key_id"],
                         aws_secret_access_key=creds["aws_secret_access_key"],
                         aws_session_token=creds["aws_session_token"])


def verify(db: Session, conn: AwsConnection, role_arn: str) -> dict:
    """specs/03 §3 step 3: AssumeRole, identity check, cheap permission probes, DryRun probe for actions."""
    account = parse_role_arn(role_arn)
    checks = []

    def check(name, ok, message=""):
        checks.append({"name": name, "ok": ok, "message": message})

    try:
        creds = assume_role(conn, role_arn)
    except ClientError as e:
        msg = explain_aws_error(e, "AssumeRole")
        check("AssumeRole", False, msg)
        conn.last_error = msg
        if conn.status == "connected":
            conn.status = "broken"
        audit(db, "ASSUME_ROLE_FAIL", conn.user_id, conn.id, {"account": account})
        db.commit()
        return {"status": conn.status, "checks": checks}

    session = boto3.Session(aws_access_key_id=creds["aws_access_key_id"],
                            aws_secret_access_key=creds["aws_secret_access_key"],
                            aws_session_token=creds["aws_session_token"])
    ident = session.client("sts", config=BOTO_CFG).get_caller_identity()
    if ident.get("Account") != account:
        check("AssumeRole", False, "The role belongs to a different account than its ARN says")
        db.commit()
        return {"status": conn.status, "checks": checks}
    check("AssumeRole", True, f"Assumed role in account {account}")

    region = get_settings().platform_aws_region
    ec2 = session.client("ec2", region_name=region, config=BOTO_CFG)
    cw = session.client("cloudwatch", region_name=region, config=BOTO_CFG)
    ok_all = True
    for name, fn in (("EC2 read", lambda: (ec2.describe_regions(), ec2.describe_instance_types(MaxResults=5))),
                     ("CloudWatch read", lambda: cw.list_metrics(Namespace="AWS/EC2"))):
        try:
            fn()
            check(name, True)
        except ClientError as e:
            ok_all = False
            check(name, False, explain_aws_error(e))

    actions_ok = False
    if conn.enable_actions:
        try:
            ec2.stop_instances(InstanceIds=["i-00000000000000000"], DryRun=True)
            actions_ok = True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            actions_ok = code == "DryRunOperation" or code.startswith("InvalidInstanceID")
        check("Actions", actions_ok, "" if actions_ok else
              "Actions policy missing: update the stack with EnableActions=true, then re-verify")

    if ok_all:
        conn.role_arn, conn.aws_account_id = role_arn, account
        conn.status, conn.last_error = "connected", None
        conn.actions_verified = actions_ok
        conn.last_verified_at = datetime.now(timezone.utc)
        _store(conn, creds)
        audit(db, "ASSUME_ROLE_OK", conn.user_id, conn.id, {"account": account, "verify": True})
    db.commit()
    return {"status": conn.status, "checks": checks}
