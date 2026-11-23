"""Static instance-type catalog + Linux on-demand list prices (us-east-1 style, USD/hour).

Test-only fixed data so test results never depend on live AWS prices. The app itself uses
describe_instance_types (family_ladder) and the Pricing API (pricing_service)."""
from app.pipeline.detector import _type_info

# name: (vcpu, mem_gib, burstable, price_usd_per_hour)
_TYPES = {
    "t3.nano": (2, 0.5, True, 0.0052), "t3.micro": (2, 1, True, 0.0104), "t3.small": (2, 2, True, 0.0208),
    "t3.medium": (2, 4, True, 0.0416), "t3.large": (2, 8, True, 0.0832), "t3.xlarge": (4, 16, True, 0.1664),
    "t3.2xlarge": (8, 32, True, 0.3328),
    "m5.large": (2, 8, False, 0.096), "m5.xlarge": (4, 16, False, 0.192), "m5.2xlarge": (8, 32, False, 0.384),
    "m5.4xlarge": (16, 64, False, 0.768), "m5.8xlarge": (32, 128, False, 1.536),
    "c5.large": (2, 4, False, 0.085), "c5.xlarge": (4, 8, False, 0.17), "c5.2xlarge": (8, 16, False, 0.34),
    "c5.4xlarge": (16, 32, False, 0.68), "c5.9xlarge": (36, 72, False, 1.53),
    "r5.large": (2, 16, False, 0.126), "r5.xlarge": (4, 32, False, 0.252), "r5.2xlarge": (8, 64, False, 0.504),
}
# simple regional multipliers relative to us-east-1 (approximate list-price differences)
_REGION_FACTOR = {"us-east-1": 1.0, "us-east-2": 1.0, "us-west-2": 1.0, "eu-west-1": 1.11, "eu-central-1": 1.15,
                  "ap-south-1": 1.05, "ap-southeast-1": 1.2}


def describe_type(name: str) -> dict:
    """Same shape as an EC2 describe_instance_types entry (so detector._type_info can parse it)."""
    vcpu, mem, burst, _ = _TYPES[name]
    return {"InstanceType": name, "VCpuInfo": {"DefaultVCpus": vcpu}, "MemoryInfo": {"SizeInMiB": int(mem * 1024)},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}, "BurstablePerformanceSupported": burst}


def ladder(instance_type: str) -> list[dict]:
    family = instance_type.split(".")[0]
    sizes = [_type_info(describe_type(n)) for n in _TYPES if n.split(".")[0] == family]
    return sorted(sizes, key=lambda x: (x["vcpu"], x["mem_gib"]))


def price(instance_type: str, region: str = "us-east-1") -> float | None:
    t = _TYPES.get(instance_type)
    return round(t[3] * _REGION_FACTOR.get(region, 1.1), 4) if t else None


def known(instance_type: str) -> bool:
    return instance_type in _TYPES
