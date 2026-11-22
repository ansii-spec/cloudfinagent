"""Detector layer: regression vs the untouched original, scenario tests (specs/04 §7), JSON safety."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from app.pipeline import catalog, recommend
from app.pipeline import detector as d
from app.pipeline.adapter import PipelineConfig, analyze_instance
from app.pipeline.serialization import to_jsonable
from app.pipeline.synthetic import FakeCloudWatch, Profile, make_meta

ORIG_PATH = Path(__file__).resolve().parents[1] / "pipeline_source" / "detector_original.py"
spec = importlib.util.spec_from_file_location("detector_original", ORIG_PATH)
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)

CFG = PipelineConfig(lookback_hours=336, min_history_hours=168)
PROFILES = {
    "idle": ("t3.large", {}, Profile(cpu_mean=0.4, cpu_max_factor=2.5, net_mb_h=0.25, ebs_mb_h=1, mem_pct=18,
                                     credits="healthy", seed=1)),
    "over": ("m5.2xlarge", {}, Profile(cpu_mean=4.5, cpu_amp=0.5, cpu_max_factor=1.6, net_mb_h=310, ebs_mb_h=95,
                                       mem_pct=13, seed=2)),
    "under": ("c5.large", {}, Profile(cpu_mean=90, cpu_amp=0.06, cpu_noise=0.04, cpu_max_factor=1.08,
                                      net_mb_h=2500, ebs_mb_h=30, mem_pct=55, seed=3)),
    "credit": ("t3.micro", {}, Profile(cpu_mean=14, cpu_amp=0.6, cpu_cap=22, cpu_max_factor=1.3, net_mb_h=60,
                                       ebs_mb_h=40, mem_pct=45, credits="starved", seed=4)),
    "sensitive": ("m5.large", {"Role": "db-replica"}, Profile(cpu_mean=0.6, cpu_max_factor=2.0, net_mb_h=0.6,
                                                               ebs_mb_h=3, mem_pct=35, seed=5)),
    "active": ("m5.large", {}, Profile(cpu_mean=38, cpu_amp=0.3, cpu_max_factor=1.6, net_mb_h=800, ebs_mb_h=60,
                                       mem_pct=52, seed=6)),
    "no_mem_over": ("m5.xlarge", {}, Profile(cpu_mean=7.5, cpu_amp=0.2, cpu_max_factor=1.5, net_mb_h=120,
                                             ebs_mb_h=20, seed=7)),
}


@pytest.fixture(autouse=True)
def quality_on():
    d.APPLY_DATA_QUALITY = orig.APPLY_DATA_QUALITY = True
    yield


def _run(name, age_hours=24 * 60):
    itype, tags, prof = PROFILES[name]
    iid = f"i-{abs(hash(name)) % 10**12:012x}0000"
    meta = make_meta(iid, name, itype, tags, age_hours=age_hours)
    return meta, FakeCloudWatch({iid: prof})


def _price(t):
    return catalog.price(t, "us-east-1")


def _analyze(name, **kw):
    meta, cw = _run(name, **kw)
    return analyze_instance(meta, cw, None, _price, CFG, region="us-east-1", ladder_fn=catalog.ladder)


@pytest.mark.parametrize("name,expected", [
    ("idle", "IDLE"), ("over", "OVER_PROVISIONED"), ("under", "UNDER_PROVISIONED"), ("credit", "UNDER_PROVISIONED"),
    ("sensitive", "NEEDS_REVIEW"), ("active", "ACTIVE"), ("no_mem_over", "OVER_PROVISIONED"),
])
def test_scenarios(name, expected):
    assert _analyze(name)["status"] == expected


def test_insufficient_data():
    assert _analyze("active", age_hours=30)["status"] == "INSUFFICIENT_DATA"


def test_suggestions():
    assert _analyze("idle")["suggestion"]["action"] == "STOP_INSTANCE"
    over = _analyze("over")
    assert over["suggestion"]["action"] == "RESIZE" and over["suggestion"]["to_type"] == "m5.large"
    assert over["suggestion"]["monthly_saving_usd"] == over["overprovisioned"]["monthly_saving_usd"]
    under = _analyze("under")["suggestion"]
    assert under["to_type"] == "c5.xlarge" and under["monthly_delta_usd"] > 0 and under["monthly_saving_usd"] == 0
    assert _analyze("credit")["suggestion"]["action"] == "ENABLE_UNLIMITED_CREDITS"
    nm = _analyze("no_mem_over")
    assert nm["overprovisioned"]["memory_checked"] is False and nm["suggestion"]["risk"] == "HIGH"
    assert _analyze("sensitive")["suggestion"]["action"] == "NONE"


@pytest.mark.parametrize("name", list(PROFILES))
@pytest.mark.parametrize("apply_dq", [True, False])
def test_regression_matches_original(name, apply_dq):
    """Refactored detector == original detector on identical inputs (scores, statuses, steps)."""
    d.APPLY_DATA_QUALITY = orig.APPLY_DATA_QUALITY = apply_dq
    meta, cw = _run(name)
    m_new = d.fetch_cloudwatch_metrics(cw, meta["instance_id"], [], meta["launch_time"], 336)
    m_old = orig.fetch_cloudwatch_metrics(cw, meta["instance_id"], [], meta["launch_time"], 336)
    for k in ("cpu_avg", "cpu_max", "network_mb_hourly", "ebs_mb_hourly", "cpu_max_hourly", "mem_used_pct",
              "credit_balance"):
        np.testing.assert_array_equal(m_new[k], m_old[k])
    ladder = catalog.ladder(meta["instance_type"])

    def cascade(mod, m):
        r = mod.classify_and_score(meta, m, min_history_hours=168)
        if r["status"] == "INSUFFICIENT_DATA":
            return r
        idle_wins = r["idle"]["score"] >= mod.IDLE_THRESHOLD and not r["idle"]["blocked_by"]
        over = None if idle_wins else mod.check_overprovisioned(meta, m, ladder, _price)
        return mod.run_cascade(r, over)

    assert json.dumps(cascade(d, m_new), sort_keys=True, default=str) == \
        json.dumps(cascade(orig, m_old), sort_keys=True, default=str)


def test_hourly_series_present():
    meta, cw = _run("over")
    m = d.fetch_cloudwatch_metrics(cw, meta["instance_id"], [], meta["launch_time"], 336)
    assert len(m["hourly_series"]) == m["valid_hours"] and m["hourly_series"][0]["ts"].endswith("Z")
    assert m["mem_hourly"] and "mem_pct" in m["mem_hourly"][0]


def test_to_jsonable_round_trip():
    obj = {"a": np.float64(1.5), "b": np.int64(3), "c": np.array([1.0, np.nan]), "d": float("inf"),
           "steps": [("s", "c", "r")], "e": np.bool_(True)}
    out = to_jsonable(obj)
    assert json.loads(json.dumps(out)) == {"a": 1.5, "b": 3, "c": [1.0, None], "d": None,
                                           "steps": [{"step": "s", "calculation": "c", "result": "r"}], "e": True}
    json.dumps(_analyze("over"), allow_nan=False)


def test_upsize_target_none_at_top():
    assert recommend.upsize_target(catalog.ladder("m5.8xlarge"), "m5.8xlarge") is None


def test_explain_assume_role_error():
    from botocore.exceptions import ClientError
    e = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "AssumeRole")
    assert "External ID" in d.explain_aws_error(e)
    assert "AWS_ACCESS_KEY" not in d.explain_aws_error(Exception())
