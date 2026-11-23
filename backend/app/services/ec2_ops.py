"""EC2 operations used by remediation. AwsOps = real boto3 (customer role)."""

from botocore.exceptions import ClientError

from app.config import get_settings
from app.services.aws_session import BOTO_CFG


class OpError(Exception):
    """A failed EC2 operation with a human-readable message and the AWS error code (if any)."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def _family(t: str) -> str:
    return t.split(".")[0]


class AwsOps:
    def __init__(self, session, region: str):
        s = get_settings()
        self.region = region
        self.ec2 = session.client("ec2", region_name=region, config=BOTO_CFG)
        self.asg = session.client("autoscaling", region_name=region, config=BOTO_CFG)
        self.waiter_cfg = {"Delay": s.waiter_delay_s, "MaxAttempts": s.waiter_max_attempts}

    # ---- reads
    def describe(self, iid: str) -> dict | None:
        try:
            res = self.ec2.describe_instances(InstanceIds=[iid])["Reservations"]
        except ClientError as e:
            if e.response["Error"]["Code"].startswith("InvalidInstanceID"):
                return None
            raise
        if not res or not res[0]["Instances"]:
            return None
        i = res[0]["Instances"][0]
        live = {
            "state": i["State"]["Name"], "instance_type": i["InstanceType"],
            "lifecycle": i.get("InstanceLifecycle", "normal"), "root_device_type": i.get("RootDeviceType", "ebs"),
            "tags": {t["Key"]: t["Value"] for t in i.get("Tags", [])}, "public_ip": i.get("PublicIpAddress"),
            "hibernation": bool(i.get("HibernationOptions", {}).get("Configured")),
            "volume_ids": [b["Ebs"]["VolumeId"] for b in i.get("BlockDeviceMappings", []) if "Ebs" in b],
            "architecture": i.get("Architecture"), "cpu_credits": None,
        }
        if live["instance_type"].startswith("t"):
            try:
                spec = self.ec2.describe_instance_credit_specifications(InstanceIds=[iid])
                live["cpu_credits"] = spec["InstanceCreditSpecifications"][0]["CpuCredits"]
            except (ClientError, IndexError, KeyError):
                pass
        return live

    def protection(self, iid: str, attribute: str) -> bool:
        try:
            r = self.ec2.describe_instance_attribute(InstanceId=iid, Attribute=attribute)
            key = attribute[0].upper() + attribute[1:]
            return bool(r.get(key, {}).get("Value"))
        except ClientError:
            return False

    def asg_name(self, iid: str, tags: dict) -> str | None:
        if "aws:autoscaling:groupName" in tags:
            return tags["aws:autoscaling:groupName"]
        try:
            items = self.asg.describe_auto_scaling_instances(InstanceIds=[iid]).get("AutoScalingInstances", [])
            return items[0]["AutoScalingGroupName"] if items else None
        except ClientError:
            return None

    def has_eip(self, iid: str) -> bool:
        try:
            return bool(self.ec2.describe_addresses(Filters=[{"Name": "instance-id", "Values": [iid]}])["Addresses"])
        except ClientError:
            return False

    def type_info(self, t: str) -> dict | None:
        try:
            types = self.ec2.describe_instance_types(InstanceTypes=[t])["InstanceTypes"]
        except ClientError:
            return None
        if not types:
            return None
        return {"name": t, "arch": sorted(types[0]["ProcessorInfo"]["SupportedArchitectures"])}

    def dry_run(self, action: str, iid: str) -> str | None:
        """Returns None when the call would be allowed, else a blocker message."""
        call = {
            "STOP_INSTANCE": lambda: self.ec2.stop_instances(InstanceIds=[iid], DryRun=True),
            "RESIZE": lambda: self.ec2.stop_instances(InstanceIds=[iid], DryRun=True),
            "TERMINATE_INSTANCE": lambda: self.ec2.terminate_instances(InstanceIds=[iid], DryRun=True),
            "ENABLE_UNLIMITED_CREDITS": lambda: self.ec2.modify_instance_credit_specification(
                DryRun=True, InstanceCreditSpecifications=[{"InstanceId": iid, "CpuCredits": "unlimited"}]),
        }.get(action)
        if call is None:
            return None
        try:
            call()
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "DryRunOperation":
                return None
            if code in ("UnauthorizedOperation", "AccessDenied"):
                return "The role is not allowed to do this. Enable actions (update the stack) and re-verify."
            return None  # other errors surface during execution
        return None  # moto / services that ignore DryRun

    # ---- writes
    def _wrap(self, fn):
        try:
            return fn()
        except ClientError as e:
            from app.pipeline.detector import explain_aws_error
            raise OpError(explain_aws_error(e), e.response["Error"]["Code"]) from e
        except Exception as e:  # noqa: BLE001 - waiter errors etc.
            from app.pipeline.detector import explain_aws_error
            raise OpError(explain_aws_error(e), type(e).__name__) from e

    def _wait(self, name, iid):
        self.ec2.get_waiter(name).wait(InstanceIds=[iid], WaiterConfig=self.waiter_cfg)

    def stop(self, iid):
        self._wrap(lambda: (self.ec2.stop_instances(InstanceIds=[iid]), self._wait("instance_stopped", iid)))

    def start(self, iid, wait_status_ok=False):
        def go():
            self.ec2.start_instances(InstanceIds=[iid])
            self._wait("instance_running", iid)
            if wait_status_ok:
                self._wait("instance_status_ok", iid)
        self._wrap(go)

    def modify_type(self, iid, target):
        self._wrap(lambda: self.ec2.modify_instance_attribute(InstanceId=iid, InstanceType={"Value": target}))

    def set_credits(self, iid, mode):
        self._wrap(lambda: self.ec2.modify_instance_credit_specification(
            InstanceCreditSpecifications=[{"InstanceId": iid, "CpuCredits": mode}]))

    def terminate(self, iid):
        self._wrap(lambda: (self.ec2.terminate_instances(InstanceIds=[iid]), self._wait("instance_terminated", iid)))

    def create_image(self, iid, name) -> str:
        return self._wrap(lambda: self.ec2.create_image(InstanceId=iid, Name=name, NoReboot=True)["ImageId"])

    def snapshot(self, volume_id, description) -> str:
        return self._wrap(lambda: self.ec2.create_snapshot(VolumeId=volume_id, Description=description)["SnapshotId"])

    def tag(self, iid, tags: dict):
        self._wrap(lambda: self.ec2.create_tags(Resources=[iid],
                                                Tags=[{"Key": k, "Value": v} for k, v in tags.items()]))
