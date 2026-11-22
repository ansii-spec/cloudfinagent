"""Real-AWS code paths against moto: AssumeRole verify, analyze_region, remediation with AwsOps."""
import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.config import get_settings
from app.db import SessionLocal
from app.models import AwsConnection, Finding, RemediationAction, Scan, User
from app.pipeline import catalog
from app.pipeline import detector as d
from app.pipeline.adapter import PipelineConfig, analyze_region
from app.pipeline.synthetic import FakeCloudWatch, Profile
from app.services import aws_session, remediation_service

ARN = "arn:aws:iam::123456789012:role/EC2OptimizerAccessRole"


@pytest.fixture
def real_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "demo_mode", False)
    with mock_aws():
        yield s


def _user_conn(db, enable_actions=True):
    u = User(email="x@example.com", name="X", password_hash="x")
    db.add(u)
    db.flush()
    c = AwsConnection(user_id=u.id, external_id="ext-id-0123456789abcdef", enable_actions=enable_actions)
    db.add(c)
    db.commit()
    return u, c


def test_verify_success(real_mode):
    with SessionLocal() as db:
        _, c = _user_conn(db)
        res = aws_session.verify(db, c, ARN)
        assert res["status"] == "connected", res
        assert {x["name"] for x in res["checks"]} >= {"AssumeRole", "EC2 read", "CloudWatch read", "Actions"}
        assert c.aws_account_id == "123456789012"


def test_verify_access_denied(real_mode, monkeypatch):
    def deny(*a, **k):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "AssumeRole")
    monkeypatch.setattr(aws_session, "assume_role", deny)
    with SessionLocal() as db:
        _, c = _user_conn(db)
        res = aws_session.verify(db, c, ARN)
        assert res["status"] == "pending" and not res["checks"][0]["ok"]
        assert "External ID" in res["checks"][0]["message"]


def test_get_session_marks_broken(real_mode, monkeypatch):
    with SessionLocal() as db:
        _, c = _user_conn(db)
        aws_session.verify(db, c, ARN)
        aws_session.forget(c)
        monkeypatch.setattr(aws_session, "assume_role", lambda *a, **k: (_ for _ in ()).throw(
            ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "AssumeRole")))
        with pytest.raises(aws_session.ConnectionBroken):
            aws_session.get_session(db, c)
        db.refresh(c)
        assert c.status == "broken"


def _launch(itype="m5.2xlarge", tags=None):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    tags = [{"Key": "Name", "Value": "moto-box"}] + [{"Key": k, "Value": v} for k, v in (tags or {}).items()]
    r = ec2.run_instances(ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1,
                          TagSpecifications=[{"ResourceType": "instance", "Tags": tags}])
    return r["Instances"][0]["InstanceId"]


def test_fetch_metadata_and_analyze_region(real_mode, monkeypatch):
    iid = _launch()
    meta = d.fetch_instance_metadata(boto3.client("ec2", region_name="us-east-1"))
    assert iid in meta and meta[iid]["instance_type"] == "m5.2xlarge"
    # moto returns no realistic CloudWatch data -> inject the fake cw client
    fake_cw = FakeCloudWatch({iid: Profile(cpu_mean=4.5, cpu_amp=0.5, cpu_max_factor=1.6, net_mb_h=310,
                                           ebs_mb_h=95, mem_pct=13, seed=2)})
    real_get_clients = d.get_clients
    monkeypatch.setattr(d, "get_clients", lambda s, r, p: (real_get_clients(s, r, p)[0], fake_cw, None))
    monkeypatch.setattr(d, "fetch_instance_metadata", lambda ec2: {
        k: {**v, "launch_time": v["launch_time"].replace(year=2020)} for k, v in meta.items()})
    sess = boto3.Session(region_name="us-east-1")
    progress = []
    res = analyze_region(sess, sess, "us-east-1", PipelineConfig(), on_progress=progress.append,
                         price_fn=lambda t: catalog.price(t))
    assert len(res) == 1 and res[0]["status"] == "OVER_PROVISIONED" and progress == [1]


def test_analyze_region_error_isolated(real_mode, monkeypatch):
    _launch()
    monkeypatch.setattr(d, "fetch_cloudwatch_metrics", lambda *a, **k: (_ for _ in ()).throw(
        ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetMetricData")))
    sess = boto3.Session(region_name="us-east-1")
    res = analyze_region(sess, sess, "us-east-1", PipelineConfig(), price_fn=lambda t: 0.1)
    assert res[0]["status"] == "ERROR" and "permission" in res[0]["reason"]


def _finding(db, c, iid, status="OVER_PROVISIONED", action="RESIZE", itype="m5.2xlarge", to="m5.large"):
    s = Scan(connection_id=c.id, status="completed")
    db.add(s)
    db.flush()
    f = Finding(scan_id=s.id, connection_id=c.id, instance_id=iid, region="us-east-1", name="moto-box",
                instance_type=itype, state="running", status=status, memory_checked=True,
                suggestion={"action": action, "alternative_actions": ["TERMINATE_INSTANCE"] if action ==
                            "STOP_INSTANCE" else [], "to_type": to})
    db.add(f)
    db.commit()
    return f


def _connected(db):
    u, c = _user_conn(db)
    aws_session.verify(db, c, ARN)
    return u, c


def test_resize_and_undo_with_moto(real_mode):
    iid = _launch()
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid)
        a = remediation_service.request_action(db, u, f, "RESIZE", {"create_backup_ami": True}, None)
        db.expire_all()
        a = db.get(RemediationAction, a.id)
        assert a.status == "succeeded", (a.error, a.steps_log)
        live = boto3.client("ec2", region_name="us-east-1").describe_instances(InstanceIds=[iid])
        assert live["Reservations"][0]["Instances"][0]["InstanceType"] == "m5.large"
        assert a.after["backup_ami"].startswith("ami-")
        undo = remediation_service.request_undo(db, u, a)
        db.expire_all()
        assert db.get(RemediationAction, undo.id).status == "succeeded"
        live = boto3.client("ec2", region_name="us-east-1").describe_instances(InstanceIds=[iid])
        assert live["Reservations"][0]["Instances"][0]["InstanceType"] == "m5.2xlarge"


def test_stop_with_moto(real_mode):
    iid = _launch("t3.large")
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid, status="IDLE", action="STOP_INSTANCE", itype="t3.large", to=None)
        a = remediation_service.request_action(db, u, f, "STOP_INSTANCE", {}, None)
        db.expire_all()
        assert db.get(RemediationAction, a.id).status == "succeeded"
        st = boto3.client("ec2", region_name="us-east-1").describe_instances(InstanceIds=[iid])
        assert st["Reservations"][0]["Instances"][0]["State"]["Name"] == "stopped"


@pytest.mark.parametrize("tags,needle", [({"aws:autoscaling:groupName": "web-asg"}, "Auto Scaling"),
                                         ({"eks:cluster-name": "k"}, "EKS")])
def test_blockers(real_mode, tags, needle):
    iid = _launch(tags=tags)
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid)
        with pytest.raises(Exception) as e:
            remediation_service.request_action(db, u, f, "RESIZE", {}, None)
        assert any(needle in b for b in e.value.details["blockers"])


def test_wrong_state_blocked(real_mode):
    iid = _launch()
    boto3.client("ec2", region_name="us-east-1").stop_instances(InstanceIds=[iid])
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid)
        with pytest.raises(Exception) as e:
            remediation_service.request_action(db, u, f, "RESIZE", {}, None)
        assert e.value.code == "ACTION_BLOCKED"


def test_modify_failure_rolls_back(real_mode, monkeypatch):
    from app.services.ec2_ops import AwsOps, OpError
    iid = _launch()

    def boom(self, i, t):
        if t == "m5.large":
            raise OpError("InvalidParameterCombination: nope", "InvalidParameterCombination")
        return orig_modify(self, i, t)
    orig_modify = AwsOps.modify_type
    monkeypatch.setattr(AwsOps, "modify_type", boom)
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid)
        a = remediation_service.request_action(db, u, f, "RESIZE", {}, None)
        db.expire_all()
        a = db.get(RemediationAction, a.id)
        assert a.status == "rolled_back"
        st = boto3.client("ec2", region_name="us-east-1").describe_instances(InstanceIds=[iid])
        assert st["Reservations"][0]["Instances"][0]["State"]["Name"] == "running"


def test_concurrent_action_rejected(real_mode):
    iid = _launch()
    with SessionLocal() as db:
        u, c = _connected(db)
        f = _finding(db, c, iid)
        db.add(RemediationAction(user_id=u.id, connection_id=c.id, instance_id=iid, region="us-east-1",
                                 action="RESIZE", status="running"))
        db.commit()
        with pytest.raises(Exception) as e:
            remediation_service.request_action(db, u, f, "RESIZE", {}, None)
        assert e.value.code == "ACTION_IN_PROGRESS"
