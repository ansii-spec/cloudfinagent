"""Generates app/pipeline/demo_fixtures.json by running the REAL detector on synthetic workloads.

    python -m app.scripts.build_demo_fixtures

Every number in the fixtures (scores, evidence steps, savings) therefore comes from the pipeline itself.
Production settings are used: 336 h lookback, 168 h minimum history, data quality applied."""
import json
from pathlib import Path

from app.pipeline import catalog
from app.pipeline import detector as d
from app.pipeline.adapter import PipelineConfig, analyze_instance
from app.pipeline.synthetic import FakeCloudWatch, Profile, make_meta

OUT = Path(__file__).resolve().parents[1] / "pipeline" / "demo_fixtures.json"

# (instance_id, name, type, region, tags, profile, extra)
SPECS = [
    ("i-0a1b2c3d4e5f60001", "dev-sandbox", "t3.large", "ap-south-1", {"Env": "dev", "Team": "platform"},
     Profile(cpu_mean=0.4, cpu_max_factor=2.5, net_mb_h=0.25, ebs_mb_h=1.0, mem_pct=18, credits="healthy", seed=11),
     {}),
    ("i-0a1b2c3d4e5f60002", "old-poc", "m5.xlarge", "us-east-1", {"Env": "test", "Owner": "ml-team"},
     Profile(cpu_mean=0.35, cpu_max_factor=2.2, net_mb_h=0.4, ebs_mb_h=0.8, seed=12), {}),
    ("i-0a1b2c3d4e5f60003", "db-replica-1", "m5.large", "ap-south-1", {"Role": "db-replica", "Env": "staging"},
     Profile(cpu_mean=0.6, cpu_max_factor=2.0, net_mb_h=0.6, ebs_mb_h=3.0, mem_pct=35, seed=13), {}),
    ("i-0a1b2c3d4e5f60004", "reporting-worker", "m5.2xlarge", "ap-south-1", {"App": "reporting", "Env": "live"},
     Profile(cpu_mean=4.5, cpu_amp=0.5, cpu_max_factor=1.6, net_mb_h=310, ebs_mb_h=95, mem_pct=13, seed=14), {}),
    ("i-0a1b2c3d4e5f60005", "api-backend", "c5.4xlarge", "us-east-1", {"App": "api", "Env": "live"},
     Profile(cpu_mean=5.5, cpu_amp=0.4, cpu_max_factor=1.6, net_mb_h=900, ebs_mb_h=40, mem_pct=9, seed=15),
     {"demo_fail_resize": True}),
    ("i-0a1b2c3d4e5f60006", "queue-consumer", "m5.xlarge", "us-east-1", {"App": "queue", "Env": "live"},
     Profile(cpu_mean=7.5, cpu_amp=0.2, cpu_max_factor=1.5, net_mb_h=120, ebs_mb_h=20, seed=16), {}),
    ("i-0a1b2c3d4e5f60007", "web-frontend-2", "t3.xlarge", "ap-south-1", {"App": "web", "Env": "live"},
     Profile(cpu_mean=3.5, cpu_amp=0.4, cpu_max_factor=2.0, net_mb_h=200, ebs_mb_h=15, mem_pct=10,
             credits="healthy", seed=17), {}),
    ("i-0a1b2c3d4e5f60008", "api-gateway", "c5.large", "us-east-1", {"App": "gateway", "Env": "live"},
     Profile(cpu_mean=90, cpu_amp=0.06, cpu_noise=0.04, cpu_max_factor=1.08, net_mb_h=2500, ebs_mb_h=30,
             mem_pct=55, seed=18), {}),
    ("i-0a1b2c3d4e5f60009", "batch-runner", "t3.micro", "ap-south-1", {"App": "batch", "Env": "live"},
     Profile(cpu_mean=14, cpu_amp=0.6, cpu_cap=22, cpu_max_factor=1.3, net_mb_h=60, ebs_mb_h=40, mem_pct=45,
             credits="starved", seed=19), {}),
    ("i-0a1b2c3d4e5f60010", "web-frontend-1", "m5.large", "ap-south-1", {"App": "web", "Env": "live"},
     Profile(cpu_mean=38, cpu_amp=0.3, cpu_max_factor=1.6, net_mb_h=800, ebs_mb_h=60, mem_pct=52, seed=20), {}),
    ("i-0a1b2c3d4e5f60011", "etl-scheduler", "c5.large", "us-east-1", {"App": "etl", "Env": "live"},
     Profile(cpu_mean=42, cpu_amp=0.4, cpu_max_factor=1.5, net_mb_h=400, ebs_mb_h=200, mem_pct=48, seed=21), {}),
    ("i-0a1b2c3d4e5f60012", "search-indexer", "t3.large", "ap-south-1", {"App": "search", "Env": "live"},
     Profile(cpu_mean=28, cpu_amp=0.3, cpu_max_factor=1.6, net_mb_h=150, ebs_mb_h=80, mem_pct=60,
             credits="healthy", seed=22), {}),
    ("i-0a1b2c3d4e5f60013", "legacy-reporting", "m5.large", "us-east-1", {"App": "reporting-v1"},
     None, {"state": "stopped"}),
    ("i-0a1b2c3d4e5f60014", "new-feature-test", "t3.medium", "ap-south-1", {"Env": "test"},
     Profile(cpu_mean=12, net_mb_h=40, ebs_mb_h=10, mem_pct=30, credits="healthy", seed=24), {"age_hours": 30}),
]


def _round(obj, key=""):
    """Shrinks chart series only; prices / scores keep full precision."""
    if isinstance(obj, float) and key in SERIES_KEYS:
        return round(obj, 2)
    if isinstance(obj, list):
        return [_round(x, key) for x in obj]
    if isinstance(obj, dict):
        return {k: _round(v, k if key not in ("hourly_series", "mem_hourly") else k) for k, v in obj.items()}
    return obj


SERIES_KEYS = {"cpu_avg", "cpu_max", "net_mb", "ebs_mb", "mem_pct"}


def build() -> list[dict]:
    d.APPLY_DATA_QUALITY = True
    cfg = PipelineConfig(lookback_hours=336, min_history_hours=168)
    profiles = {iid: p for iid, _, _, _, _, p, _ in SPECS if p}
    cw = FakeCloudWatch(profiles)
    out = []
    for iid, name, itype, region, tags, _, extra in SPECS:
        meta = make_meta(iid, name, itype, tags, state=extra.get("state", "running"),
                         age_hours=extra.get("age_hours", 24 * 60))
        f = analyze_instance(meta, cw, None, lambda t, r=region: catalog.price(t, r), cfg, region=region,
                             ladder_fn=catalog.ladder)
        f["demo_fail_resize"] = bool(extra.get("demo_fail_resize"))
        out.append(_round(f))
    return out


if __name__ == "__main__":
    findings = build()
    OUT.write_text(json.dumps(findings, separators=(",", ":")))
    for f in findings:
        s = f["suggestion"]
        print(f"{f['name']:<18} {f['instance_type']:<11} {f['status']:<18} {f['confidence']['score']:>5} "
              f"{f['confidence']['band']:<6} {s['action']:<24} {s.get('to_type') or '':<11} "
              f"save={s.get('monthly_saving_usd')} delta={s.get('monthly_delta_usd')}")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
