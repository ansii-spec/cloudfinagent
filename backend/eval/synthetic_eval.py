"""
Synthetic evaluation of the cfa/detector.py pipeline.

1. Generates 50 labelled EC2 instances (5-min CloudWatch-style series, 35 h) from scenario
   templates. The LABEL is the scenario's design intent, not the pipeline's thresholds.
2. Serves them through fake EC2 / CloudWatch / Pricing clients, so the REAL pipeline code runs
   unchanged: fetch_cloudwatch_metrics -> classify_and_score -> check_overprovisioned -> run_cascade.
3. Reports accuracy, per-class precision / recall / F1, the confusion matrix and every miss.

Run:  cfa/bin/python eval/synthetic_eval.py [--seed 7]
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cfa"))
import detector as d  # noqa: E402

LABELS = ["IDLE", "NEEDS_REVIEW", "OVER_PROVISIONED", "UNDER_PROVISIONED", "ACTIVE"]

# ---------------------------------------------------------------- instance catalogue (AWS specs)
# (name, vCPU, GiB, burstable, network baseline Gbps, EBS baseline MB/s, approx USD/h)
CATALOGUE = [
    ("t3.nano", 2, 0.5, True, 0.032, 4, 0.0052), ("t3.micro", 2, 1, True, 0.064, 11, 0.0104),
    ("t3.small", 2, 2, True, 0.128, 22, 0.0208), ("t3.medium", 2, 4, True, 0.256, 43, 0.0416),
    ("t3.large", 2, 8, True, 0.512, 87, 0.0832), ("t3.xlarge", 4, 16, True, 1.024, 87, 0.1664),
    ("t3.2xlarge", 8, 32, True, 2.048, 87, 0.3328),
    ("m5.large", 2, 8, False, 0.75, 81, 0.096), ("m5.xlarge", 4, 16, False, 1.25, 143, 0.192),
    ("m5.2xlarge", 8, 32, False, 2.5, 287, 0.384), ("m5.4xlarge", 16, 64, False, 5, 593, 0.768),
    ("c5.large", 2, 4, False, 0.75, 81, 0.085), ("c5.xlarge", 4, 8, False, 1.25, 143, 0.17),
    ("c5.2xlarge", 8, 16, False, 2.5, 287, 0.34), ("c5.4xlarge", 16, 32, False, 5, 593, 0.68),
    ("r5.large", 2, 16, False, 0.75, 81, 0.126), ("r5.xlarge", 4, 32, False, 1.25, 143, 0.252),
    ("r5.2xlarge", 8, 64, False, 2.5, 287, 0.504),
]
SPEC = {c[0]: c for c in CATALOGUE}
PRICE = {c[0]: c[6] for c in CATALOGUE}


# ---------------------------------------------------------------- scenario generators
# Each returns a dict of 5-min series for n samples. Units: CPU %, bytes per 5 min, credits, mem %.
def _diurnal(ts):
    h = (ts.hour + ts.minute / 60 + 5.5) % 24                       # IST local time
    return np.asarray(0.5 * (1 - np.cos(2 * np.pi * (h - 4) / 24)))   # 0 at night, 1 mid-afternoon


def _mb_h(rng, lo, hi, n):
    """Network / EBS in MB per HOUR -> bytes per 5 min, log-uniform level with noise."""
    level = np.exp(rng.uniform(np.log(lo), np.log(hi)))
    return level * 1e6 / 12 * rng.lognormal(0, 0.35, n)


def _cpu_from_vcpu(work_vcpu, vcpu, rng):
    avg = np.clip(work_vcpu / vcpu * 100, 0.05, 100)
    mx = np.clip(avg * rng.uniform(1.1, 1.5, len(avg)), 0, 100)
    return avg, mx


def gen_idle(rng, ts, itype, **kw):
    n = len(ts)
    avg = rng.uniform(0.2, 1.5) + rng.normal(0, 0.15, n).clip(-0.1, None)
    mx = avg * rng.uniform(1.2, 2.5, n)
    cron = rng.choice(n, 2, replace=False)                           # cron / package-timer blips
    mx[cron] = rng.uniform(4, 8, 2)
    return dict(cpu_avg=avg.clip(0.05), cpu_max=mx.clip(0.1, 100),
                net_in=_mb_h(rng, 0.05, 2, n), net_out=_mb_h(rng, 0.02, 1, n),
                ebs=_mb_h(rng, 1, kw.get("ebs_hi", 40), n))


def gen_replica(rng, ts, itype, **kw):                               # idle CPU, steady replication
    s = gen_idle(rng, ts, itype)
    n = len(ts)
    s["net_in"] = rng.uniform(30, 80) * 1e6 / 12 * rng.normal(1, 0.08, n).clip(0.7)
    s["ebs"] = _mb_h(rng, 20, 50, n)
    return s


def gen_steady_work(rng, ts, itype, peak_frac, net=(50, 500), ebs=(20, 200), **kw):
    """Diurnal workload whose PEAK uses `peak_frac` of the instance's vCPUs."""
    vcpu, n = SPEC[itype][1], len(ts)
    work = vcpu * peak_frac * (0.35 + 0.65 * _diurnal(ts)) * rng.normal(1, 0.08, n).clip(0.6)
    avg, mx = _cpu_from_vcpu(work, vcpu, rng)
    return dict(cpu_avg=avg, cpu_max=mx, net_in=_mb_h(rng, *net, n), net_out=_mb_h(rng, *net, n),
                ebs=_mb_h(rng, *ebs, n))


def gen_saturated(rng, ts, itype, **kw):
    n = len(ts)
    avg = np.clip(rng.uniform(86, 97) + rng.normal(0, 3, n), 60, 100)
    return dict(cpu_avg=avg, cpu_max=np.clip(avg + rng.uniform(2, 10, n), 0, 100),
                net_in=_mb_h(rng, 100, 1000, n), net_out=_mb_h(rng, 100, 1000, n), ebs=_mb_h(rng, 50, 400, n))


def gen_credit_starved(rng, ts, itype, **kw):
    """T instance pinned at its 20 % baseline because credits ran out for part of the day."""
    n = len(ts)
    starved = _diurnal(ts) > rng.uniform(0.35, 0.6)                  # busy part of the day
    avg = np.where(starved, rng.uniform(19, 20.5, n), rng.uniform(8, 15, n))
    credits = np.where(starved, rng.uniform(0, 2, n), rng.uniform(20, 120, n))
    s = dict(cpu_avg=avg, cpu_max=np.clip(avg * 1.15, 0, 100), net_in=_mb_h(rng, 50, 300, n),
             net_out=_mb_h(rng, 50, 300, n), ebs=_mb_h(rng, 20, 100, n))
    s["credit_bal"] = credits
    return s


def gen_gateway(rng, ts, itype, **kw):                               # low CPU, heavy jumpy network
    n = len(ts)
    avg = rng.uniform(2, 4) * (0.5 + _diurnal(ts)) + rng.normal(0, 0.3, n)
    return dict(cpu_avg=avg.clip(0.3), cpu_max=(avg * 1.6).clip(0.5, 100),
                net_in=_mb_h(rng, 500, 3000, n) * (0.2 + 1.6 * _diurnal(ts)),
                net_out=_mb_h(rng, 500, 3000, n) * (0.2 + 1.6 * _diurnal(ts)), ebs=_mb_h(rng, 20, 100, n))


def gen_bursty(rng, ts, itype, **kw):                                # quiet + a few short big spikes
    s = gen_steady_work(rng, ts, itype, peak_frac=0.06, net=(20, 80))
    k = rng.choice(len(ts), 8, replace=False)
    s["cpu_avg"][k] = rng.uniform(85, 98, 8)
    s["cpu_max"][k] = 100
    return s


def gen_diskbound(rng, ts, itype, **kw):
    s = gen_steady_work(rng, ts, itype, peak_frac=0.2, net=(1, 5))
    s["ebs"] = _mb_h(rng, 3000, 10000, len(ts))
    return s


# (count, label, generator, instance types, tags, extra kwargs, has memory agent?, note)
SCENARIOS = [
    (6, "IDLE", gen_idle, ["t3.micro", "t3.small", "t3.medium", "m5.large"], {}, {}, False, "idle"),
    (4, "IDLE", gen_idle, ["t3.micro", "c5.large"], {}, {"ebs_hi": 250}, False, "idle + log noise"),
    (3, "NEEDS_REVIEW", gen_idle, ["t3.small", "m5.large", "r5.large"],
     "sensitive", {}, False, "idle CPU, sensitive tag"),
    (2, "NEEDS_REVIEW", gen_replica, ["r5.large", "m5.large"], {}, {}, False, "untagged replica"),
    (6, "OVER_PROVISIONED", gen_steady_work, ["m5.xlarge", "m5.2xlarge", "c5.xlarge", "c5.2xlarge", "r5.xlarge"],
     {}, {"peak_frac": "over"}, False, "big box, low load"),
    (2, "OVER_PROVISIONED", gen_steady_work, ["m5.2xlarge", "c5.4xlarge"],
     {}, {"peak_frac": "over"}, True, "big box, low load + mem"),
    (4, "OVER_PROVISIONED", gen_steady_work, ["t3.xlarge", "t3.2xlarge"],
     {}, {"peak_frac": "over_t"}, False, "big T, low load"),
    (7, "UNDER_PROVISIONED", gen_saturated, ["c5.large", "m5.large", "c5.xlarge", "t3.medium"],
     {}, {}, False, "saturated CPU"),
    (3, "UNDER_PROVISIONED", gen_credit_starved, ["t3.small", "t3.medium"], {}, {}, False, "T out of credits"),
    (5, "ACTIVE", gen_steady_work, ["m5.large", "c5.large", "c5.xlarge"],
     {}, {"peak_frac": "right"}, False, "right-sized"),
    (3, "ACTIVE", gen_gateway, ["t3.micro", "t3.small"], {}, {}, False, "network gateway"),
    (3, "ACTIVE", gen_bursty, ["t3.medium", "t3.large"], {}, {}, False, "bursty"),
    (2, "ACTIVE", gen_diskbound, ["t3.small", "m5.large"], {}, {}, False, "disk-bound"),
]
SENSITIVE_TAGS = [{"Role": "replica"}, {"Service": "postgres"}, {"Purpose": "standby-db"}]


def build_fleet(seed: int, now: datetime):
    rng = np.random.default_rng(seed)
    launch = now - timedelta(hours=45)
    start = pd.Timestamp(launch + timedelta(hours=d.BOOT_WARMUP_HOURS)).floor("300s")
    ts = pd.date_range(start, pd.Timestamp(now).ceil("300s"), freq="300s")
    fleet, k = [], 0
    for count, label, gen, types, tags, kw, has_mem, note in SCENARIOS:
        for i in range(count):
            k += 1
            itype = types[i % len(types)]
            kw2 = dict(kw)
            if kw2.get("peak_frac") == "over":        # needed vCPU well under half the box
                kw2["peak_frac"] = rng.uniform(0.06, 0.22)
            elif kw2.get("peak_frac") == "over_t":    # avg well under the next size's baseline
                kw2["peak_frac"] = rng.uniform(0.04, 0.09)
            elif kw2.get("peak_frac") == "right":     # busy but healthy: peak 55-75 %
                kw2["peak_frac"] = rng.uniform(0.55, 0.75)
            series = gen(rng, ts, itype, **kw2)
            if SPEC[itype][3] and "credit_bal" not in series:
                series["credit_bal"] = rng.uniform(150, 500, len(ts))
            if has_mem:
                series["mem"] = np.clip(rng.uniform(15, 35) + rng.normal(0, 2, len(ts)), 5, 95)
            # realism: short gaps in ~1 of 5 instances
            if rng.random() < 0.2:
                g = rng.integers(20, len(ts) - 40)
                for key in series:
                    series[key] = series[key].astype(float)
                    series[key][g:g + rng.integers(6, 30)] = np.nan
            t = dict(SENSITIVE_TAGS[i % len(SENSITIVE_TAGS)]) if tags == "sensitive" else dict(tags)
            t["Name"] = f"syn-{k:02d}-{note.replace(' ', '-').replace(',', '')}"
            fleet.append({"id": f"i-syn{k:04d}", "type": itype, "label": label, "note": note,
                          "tags": t, "launch": launch, "ts": ts, "series": series})
    return fleet


# ---------------------------------------------------------------- fake AWS clients
class FakeCloudWatch:
    MAP = {"cpu_avg": "cpu_avg", "cpu_max": "cpu_max", "net_in": "net_in", "net_out": "net_out",
           "ec2_ebs_read": None, "ec2_ebs_write": "ebs", "mem_used": "mem", "credit_bal": "credit_bal"}

    def __init__(self, fleet):
        self.by_id = {f["id"]: f for f in fleet}

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **_):
        iid = MetricDataQueries[0]["MetricStat"]["Metric"]["Dimensions"][0]["Value"]
        f = self.by_id[iid]
        sel = (f["ts"] >= pd.Timestamp(StartTime)) & (f["ts"] <= pd.Timestamp(EndTime))
        out = []
        for q in MetricDataQueries:
            key = self.MAP.get(q["Id"])
            vals = f["series"].get(key) if key else None
            if vals is None:
                out.append({"Id": q["Id"], "Timestamps": [], "Values": []})
                continue
            v, t = vals[sel], f["ts"][sel]
            ok = ~np.isnan(v)
            out.append({"Id": q["Id"], "Timestamps": list(t[ok]), "Values": list(v[ok])})
        return {"MetricDataResults": out}


class FakeEC2:
    def get_paginator(self, name):
        return self

    def paginate(self, Filters, **_):
        fam = Filters[0]["Values"][0].split(".")[0]
        return [{"InstanceTypes": [{
            "InstanceType": n, "VCpuInfo": {"DefaultVCpus": v}, "MemoryInfo": {"SizeInMiB": int(m * 1024)},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}, "BurstablePerformanceSupported": b,
            "NetworkInfo": {"NetworkCards": [{"BaselineBandwidthInGbps": nb}]},
            "EbsInfo": {"EbsOptimizedInfo": {"BaselineThroughputInMBps": eb}},
        } for n, v, m, b, nb, eb, _ in CATALOGUE if n.startswith(fam + ".")]}]


# ---------------------------------------------------------------- run + score
def run_pipeline(fleet):
    cw, ec2 = FakeCloudWatch(fleet), FakeEC2()
    d._ladder_cache.clear()
    rows = []
    for f in fleet:
        meta = {"instance_id": f["id"], "name": f["tags"]["Name"], "tags": f["tags"],
                "instance_type": f["type"], "launch_time": f["launch"], "volume_ids": [],
                "age_days": 45 / 24}
        metrics = d.fetch_cloudwatch_metrics(cw, f["id"], [], launch_time=f["launch"], lookback_hours=35)
        r = d.classify_and_score(meta, metrics, min_history_hours=20)
        if r["status"] != "INSUFFICIENT_DATA":                      # same cascade as __main__
            idle_wins = r["idle"]["score"] >= d.IDLE_THRESHOLD and not r["idle"]["blocked_by"]
            over = None if idle_wins else d.check_overprovisioned(
                meta, metrics, d.family_ladder(ec2, f["type"]), PRICE.get)
            r = d.run_cascade(r, over)
        rows.append({"id": f["id"], "type": f["type"], "scenario": f["note"], "label": f["label"],
                     "predicted": r["status"], "confidence": r["confidence"]["score"],
                     "idle": r.get("idle", {}).get("score"),
                     "over": (r.get("overprovisioned") or {}).get("confidence", {}).get("score", 0.0),
                     "under": r.get("underprovisioned", {}).get("score"), "reason": r["reason"]})
    return rows


def report(rows):
    n = len(rows)
    correct = sum(r["label"] == r["predicted"] for r in rows)
    preds = sorted({r["predicted"] for r in rows} | set(LABELS), key=lambda x: (x not in LABELS, x))
    print(f"\nAccuracy: {correct}/{n} = {correct / n:.1%}\n")

    print(f"{'class':<18} {'precision':>9} {'recall':>7} {'F1':>6} {'support':>8}")
    f1s = []
    for c in LABELS:
        tp = sum(r["label"] == c and r["predicted"] == c for r in rows)
        fp = sum(r["label"] != c and r["predicted"] == c for r in rows)
        fn = sum(r["label"] == c and r["predicted"] != c for r in rows)
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        f1s.append(f1)
        print(f"{c:<18} {p:>9.2f} {rc:>7.2f} {f1:>6.2f} {tp + fn:>8}")
    print(f"{'macro F1':<18} {'':>9} {'':>7} {np.mean(f1s):>6.2f}")

    short = {"IDLE": "IDLE", "NEEDS_REVIEW": "REVIEW", "OVER_PROVISIONED": "OVER",
             "UNDER_PROVISIONED": "UNDER", "ACTIVE": "ACTIVE", "INSUFFICIENT_DATA": "NODATA"}
    print("\nConfusion matrix (rows = true label, cols = predicted)")
    print(f"{'':<8}" + "".join(f"{short.get(p, p[:6]):>8}" for p in preds))
    for c in LABELS:
        print(f"{short[c]:<8}" + "".join(f"{sum(r['label'] == c and r['predicted'] == p for r in rows):>8}"
                                         for p in preds))

    miss = [r for r in rows if r["label"] != r["predicted"]]
    print(f"\nMisclassified ({len(miss)}):")
    for r in miss:
        print(f"  {r['id']} {r['type']:<11} {r['scenario']:<22} true={r['label']:<17} "
              f"pred={r['predicted']:<17} [idle {r['idle']} | over {r['over']} | under {r['under']}]")
        print(f"      {r['reason'][:150]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    fleet = build_fleet(a.seed, datetime.now(timezone.utc))
    print(f"Generated {len(fleet)} instances: "
          + ", ".join(f"{c}={sum(f['label'] == c for f in fleet)}" for c in LABELS))
    rows = run_pipeline(fleet)
    out = os.path.join(os.path.dirname(__file__), f"synthetic_results_seed{a.seed}.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    report(rows)
    print(f"\nPer-instance results: {out}")
