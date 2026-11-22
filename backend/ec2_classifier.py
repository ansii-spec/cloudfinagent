"""
EC2 idle + over-provisioned classifier (pipeline steps 1-6 of the guide).

Everything is fetched live from AWS with boto3:
  - instances, tags, launch time, ASG membership  -> ec2.describe_instances
  - vCPU / memory / EBS limits of every size      -> ec2.describe_instance_types
  - CPU, network, EBS, credits, memory (agent)    -> cloudwatch.get_metric_data
  - on-demand price per hour                      -> pricing.get_products

Auth: access key + secret key, read from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
(or passed in). Nothing is hardcoded.

Run (normal, 14+ days):      python ec2_classifier.py --region us-east-1
Run (test on 24h of data):   python ec2_classifier.py --region us-east-1 --min-days 1
Needs: pip install boto3 numpy pandas
"""
import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone

import boto3
import numpy as np
import pandas as pd

# ------------------------------------------------------------------ settings
IDLE_CPU_P95 = 5.0            # %
IDLE_CPU_MAX = 10.0           # % (applied to p99 of the per-period Maximum, not the single top sample)
IDLE_NET_P95_MB_PER_HOUR = 20.0  # PRIMARY: p95 of hourly in+out (idle OS + agents + updates)
IDLE_EBS_P95_MB_PER_HOUR = 60.0  # PRIMARY: p95 of hourly read+write (logs, journald, swap, AV scans)
IDLE_NET_MB_PER_DAY = 3000.0     # loose safety cap only: catches a big daily job p95 would skip
IDLE_EBS_MB_PER_DAY = 5000.0     # loose safety cap only
BOOT_WARMUP_HOURS = 2         # ignore this long after launch (cloud-init, updates, agent start)
STEADY_CV = 0.5               # below = steady background traffic (replica/standby)
STEADY_MIN_MB_PER_DAY = 50.0  # traffic must also be non-trivial to count as "steady"
PROTECT_TAG = re.compile(r"replica|standby|dr|failover|backup|bastion|proxy|vpn", re.I)
TARGET_UTIL = 0.70
MAX_STEPS_DOWN = 2
MIN_COVERAGE = 0.80           # fraction of expected datapoints that must exist
MAX_GAP_HOURS = 3
HOURS_PER_MONTH = 730


# ------------------------------------------------------------------ step 1: session + discovery
def make_session(region, access_key=None, secret_key=None, session_token=None):
    return boto3.Session(
        aws_access_key_id=access_key or os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=secret_key or os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=session_token or os.environ.get("AWS_SESSION_TOKEN"),
        region_name=region,
    )


def discover_instances(session):
    ec2 = session.client("ec2")
    out = []
    for page in ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    ):
        for r in page["Reservations"]:
            for i in r["Instances"]:
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                out.append({
                    "id": i["InstanceId"],
                    "type": i["InstanceType"],
                    "launch": i["LaunchTime"],
                    "tags": tags,
                    "in_asg": "aws:autoscaling:groupName" in tags,
                })
    return out


_type_cache = {}


def family_ladder(session, instance_type):
    """All sizes in the same family + architecture, sorted by vCPU (fetched, not hardcoded)."""
    family = instance_type.split(".")[0]
    if family in _type_cache:
        return _type_cache[family]
    ec2 = session.client("ec2")
    sizes = []
    for page in ec2.get_paginator("describe_instance_types").paginate(
        Filters=[{"Name": "instance-type", "Values": [f"{family}.*"]},
                 {"Name": "bare-metal", "Values": ["false"]}]
    ):
        for t in page["InstanceTypes"]:
            ebs = t.get("EbsInfo", {}).get("EbsOptimizedInfo", {})
            sizes.append({
                "name": t["InstanceType"],
                "vcpu": t["VCpuInfo"]["DefaultVCpus"],
                "mem_gib": t["MemoryInfo"]["SizeInMiB"] / 1024,
                "ebs_mbps": ebs.get("MaximumBandwidthInMbps"),
                "burstable": t.get("BurstablePerformanceSupported", False),
            })
    sizes.sort(key=lambda s: (s["vcpu"], s["mem_gib"]))
    _type_cache[family] = sizes
    return sizes


def hourly_price(session, instance_type, region):
    """Linux on-demand price via the Pricing API (endpoint lives in us-east-1). None if unavailable."""
    try:
        pricing = session.client("pricing", region_name="us-east-1")
        f = {"instanceType": instance_type, "regionCode": region, "operatingSystem": "Linux",
             "tenancy": "Shared", "preInstalledSw": "NA", "capacitystatus": "Used"}
        resp = pricing.get_products(
            ServiceCode="AmazonEC2",
            Filters=[{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in f.items()],
            MaxResults=1,
        )
        product = json.loads(resp["PriceList"][0])
        term = next(iter(product["terms"]["OnDemand"].values()))
        dim = next(iter(term["priceDimensions"].values()))
        return float(dim["pricePerUnit"]["USD"])
    except Exception:
        return None


# ------------------------------------------------------------------ step 2+3: fetch + prepare
def fetch_metrics(session, inst, lookback_days):
    """
    Pull metrics for one instance. Period adapts to the window:
    < 15 days -> 300 s (5-min) so 24h gives 288 points instead of 24, which makes p95/p99
    meaningful; otherwise 3600 s (CloudWatch only keeps 5-min data for 63 days).
    """
    cw = session.client("cloudwatch")
    end = datetime.now(timezone.utc)
    start = max(end - timedelta(days=lookback_days),
                inst["launch"] + timedelta(hours=BOOT_WARMUP_HOURS))
    period = 300 if (end - start).days < 15 else 3600
    dim = [{"Name": "InstanceId", "Value": inst["id"]}]

    def q(qid, ns, name, stat):
        return {"Id": qid, "ReturnData": True, "MetricStat": {
            "Metric": {"Namespace": ns, "MetricName": name, "Dimensions": dim},
            "Period": period, "Stat": stat}}

    queries = [
        q("cpu_avg", "AWS/EC2", "CPUUtilization", "Average"),
        q("cpu_max", "AWS/EC2", "CPUUtilization", "Maximum"),
        q("net_in", "AWS/EC2", "NetworkIn", "Sum"),
        q("net_out", "AWS/EC2", "NetworkOut", "Sum"),
        q("ebs_r", "AWS/EC2", "EBSReadBytes", "Sum"),
        q("ebs_w", "AWS/EC2", "EBSWriteBytes", "Sum"),
        q("credit_bal", "AWS/EC2", "CPUCreditBalance", "Minimum"),
        q("surplus", "AWS/EC2", "CPUSurplusCreditsCharged", "Sum"),
        # CloudWatch agent memory; empty if agent is not installed
        q("mem", "CWAgent", "mem_used_percent", "Maximum"),
    ]
    series = {}
    for page in cw.get_paginator("get_metric_data").paginate(
        MetricDataQueries=queries, StartTime=start, EndTime=end
    ):
        for r in page["MetricDataResults"]:
            s = pd.Series(r["Values"], index=pd.to_datetime(r["Timestamps"], utc=True), dtype=float)
            series[r["Id"]] = pd.concat([series.get(r["Id"], pd.Series(dtype=float)), s])

    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated()]
    if df.empty:
        return df, period, start, end
    # regular grid, fill only small gaps (<= 3 h), longer gaps stay NaN
    full = pd.date_range(df.index[0], df.index[-1], freq=f"{period}s")
    df = df.reindex(full).interpolate(limit=int(MAX_GAP_HOURS * 3600 / period), limit_area="inside")
    # BYTES are amounts per period, interpolation is fine for small gaps; CPU% same.
    return df, period, start, end


# ------------------------------------------------------------------ step 4: data gate
def data_gate(df, period, start, end, min_days):
    span_days = (end - start).total_seconds() / 86400
    expected = (end - start).total_seconds() / period
    coverage = df["cpu_max"].notna().sum() / expected if expected and "cpu_max" in df else 0
    # 10% tolerance: an instance launched "24h ago" usually has ~23h of datapoints
    ok = span_days >= 0.9 * min_days and coverage >= MIN_COVERAGE
    return ok, round(span_days, 2), round(float(coverage), 2)


# ------------------------------------------------------------------ step 5: idle
def classify_idle(df, period, span_days, tags):
    cpu_p95 = float(np.nanpercentile(df["cpu_avg"], 95))
    # p99 of the Maximum statistic: one stray 5-min sample (apt timer, agent update) can't flip the verdict
    cpu_max = float(np.nanpercentile(df["cpu_max"], 99))
    net = df.get("net_in", 0).fillna(0) + df.get("net_out", 0).fillna(0)
    ebs = df.get("ebs_r", 0).fillna(0) + df.get("ebs_w", 0).fillna(0)
    days = max(span_days, 1 / 24)
    net_mb_day = float(net.sum()) / 1e6 / days      # normalised per day, not a raw total
    ebs_mb_day = float(ebs.sum()) / 1e6 / days

    # Resample to HOURLY totals (MB per hour) so percentiles/CV are comparable for 5-min and 1-h data
    net_h = net.resample("1h").sum() / 1e6
    ebs_h = ebs.resample("1h").sum() / 1e6
    net_p95 = float(np.percentile(net_h, 95))     # typical busy hour, robust to one-off bursts
    ebs_p95 = float(np.percentile(ebs_h, 95))
    cv = float(net_h.std(ddof=0) / net_h.mean()) if net_h.mean() > 0 else None
    steady = cv is not None and cv < STEADY_CV and net_mb_day >= STEADY_MIN_MB_PER_DAY
    tagged = [f"{k}={v}" for k, v in tags.items() if PROTECT_TAG.search(f"{k} {v}")]

    ev = {"cpu_p95": round(cpu_p95, 2), "cpu_max": round(cpu_max, 2),
          "net_p95_mb_per_hour": round(net_p95, 3), "ebs_p95_mb_per_hour": round(ebs_p95, 3),
          "net_mb_per_day": round(net_mb_day, 2), "ebs_mb_per_day": round(ebs_mb_day, 2),
          "net_hourly_cv": None if cv is None else round(cv, 3), "protect_tags": tagged}

    if cpu_p95 >= IDLE_CPU_P95 or cpu_max >= IDLE_CPU_MAX:
        return "ACTIVE", ev
    if tagged or steady:
        ev["reason"] = "low CPU but " + ("protective tag" if tagged else "steady background traffic")
        return "NEEDS_REVIEW", ev
    # primary test: p95 of hourly I/O; safety cap: daily total catches a short daily job
    # (e.g. a 1-h backup is ~4% of hours, so p95 alone would hide it)
    if (net_p95 < IDLE_NET_P95_MB_PER_HOUR and ebs_p95 < IDLE_EBS_P95_MB_PER_HOUR
            and net_mb_day < IDLE_NET_MB_PER_DAY and ebs_mb_day < IDLE_EBS_MB_PER_DAY):
        return "IDLE", ev
    return "ACTIVE", ev


# ------------------------------------------------------------------ step 6: over-provisioned
def check_overprovisioned(session, region, inst, df, period, idle_status):
    ladder = family_ladder(session, inst["type"])
    names = [s["name"] for s in ladder]
    if inst["type"] not in names:
        return {"status": "none", "verdict": "UNSUPPORTED_INSTANCE_TYPE"}
    cur_i = names.index(inst["type"])
    cur = ladder[cur_i]

    p99 = float(np.nanpercentile(df["cpu_max"], 99))
    needed = cur["vcpu"] * p99 / 100 / TARGET_UTIL
    ev = {"p99_cpu_max": round(p99, 2), "needed_vcpu": round(needed, 2), "current_vcpu": cur["vcpu"]}

    # burstable guard: never downsize a starved T instance
    if cur["burstable"]:
        bal = df.get("credit_bal")
        if bal is not None and bal.notna().any() and float(np.nanmin(bal)) < 20:
            return {"status": "none", "verdict": "BLOCKED_BY_CREDITS", **ev}
        sur = df.get("surplus")
        if sur is not None and float(np.nansum(sur)) > 0:
            return {"status": "none", "verdict": "BLOCKED_BY_SURPLUS_CREDITS", **ev}

    has_mem = "mem" in df and df["mem"].notna().sum() > 0.5 * len(df)
    mem_need = cur["mem_gib"] * float(np.nanpercentile(df["mem"], 95)) / 100 / TARGET_UTIL if has_mem else 0
    ebs_peak_mbps = float(np.nanmax(df.get("ebs_r", 0).fillna(0) + df.get("ebs_w", 0).fillna(0))) * 8 / period / 1e6

    notes = []
    if not has_mem:
        notes.append("no memory data (install CloudWatch agent)")
    if idle_status == "NEEDS_REVIEW":
        notes.append("flagged needs-review")
    if inst["in_asg"]:
        notes.append("in Auto Scaling group: change launch template")

    first = max(cur_i - MAX_STEPS_DOWN, 0)
    for cand in ladder[first:cur_i]:   # smallest allowed first
        blocked = []
        if cand["vcpu"] < needed:
            blocked.append("cpu")
        if has_mem and mem_need > cand["mem_gib"]:
            blocked.append("memory")
        if not has_mem and cand["mem_gib"] < cur["mem_gib"] / 2:
            blocked.append("memory-unknown")   # without memory data allow only one step down
        if cand["ebs_mbps"] and ebs_peak_mbps > cand["ebs_mbps"] * TARGET_UTIL:
            blocked.append("ebs")
        if blocked:
            continue
        p_now, p_new = hourly_price(session, cur["name"], region), hourly_price(session, cand["name"], region)
        saving = round((p_now - p_new) * HOURS_PER_MONTH, 2) if p_now and p_new else None
        return {"status": "found", "verdict": "OVER_PROVISIONED", "current": cur["name"],
                "recommended": cand["name"], "monthly_saving_usd": saving,
                "mem_need_gib": round(mem_need, 2) if has_mem else None,
                "confidence": "high" if not notes else "medium", "notes": notes, **ev}
    return {"status": "none", "verdict": "RIGHT_SIZED", "notes": notes, **ev}


# ------------------------------------------------------------------ pipeline
def analyze_instance(session, region, inst, lookback_days=90, min_days=14):
    df, period, start, end = fetch_metrics(session, inst, lookback_days)
    report = {"id": inst["id"], "name": inst["tags"].get("Name", "(no name)"),
              "type": inst["type"], "period_s": period}
    if df.empty or "cpu_max" not in df or df["cpu_max"].notna().sum() == 0:
        report["status"] = "insufficient_data"
        return report

    ok, span, cov = data_gate(df, period, start, end, min_days)
    report.update(history_days=span, coverage=cov)
    if not ok:
        report["status"] = "insufficient_data"
        return report
    if span < 14:
        report["warning"] = f"only {span} days of data: results are LOW confidence (test mode)"

    idle, ev = classify_idle(df, period, span, inst["tags"])
    report["idle"] = {"status": idle, **ev}
    if idle == "IDLE":
        report["over_provisioned"] = {"status": "none", "verdict": "SKIPPED_IDLE"}
    else:
        report["over_provisioned"] = check_overprovisioned(session, region, inst, df, period, idle)
    report["status"] = "ok"
    return report


def run(region, min_days=14, lookback_days=90, access_key=None, secret_key=None):
    session = make_session(region, access_key, secret_key)
    return [analyze_instance(session, region, i, lookback_days, min_days)
            for i in discover_instances(session)]


def category(r):
    if r.get("status") != "ok":
        return "INSUFFICIENT DATA"
    idle = r["idle"]["status"]
    if idle == "IDLE":
        return "IDLE"
    if r["over_provisioned"].get("verdict") == "OVER_PROVISIONED":
        return "OVER-PROVISIONED" + (" (needs review)" if idle == "NEEDS_REVIEW" else "")
    return "NEEDS REVIEW" if idle == "NEEDS_REVIEW" else "ACTIVE / RIGHT-SIZED"


def detail(r):
    if r.get("status") != "ok":
        return f"history {r.get('history_days', 0)}d, coverage {r.get('coverage', 0)}"
    i, o = r["idle"], r["over_provisioned"]
    s = f"CPU p95 {i['cpu_p95']}%, max {i['cpu_max']}%, net {i['net_mb_per_day']} MB/day"
    if o.get("verdict") == "OVER_PROVISIONED":
        save = f"${o['monthly_saving_usd']}/mo" if o["monthly_saving_usd"] is not None else "saving n/a"
        s += f" -> {o['current']} to {o['recommended']} ({save}, {o['confidence']} confidence)"
    elif i.get("reason"):
        s += f" ({i['reason']})"
    return s


def reason(r):
    """Plain-English explanation of why the instance landed in its category."""
    if r.get("status") != "ok":
        if "history_days" not in r:
            return "No CPU datapoints returned by CloudWatch"
        return (f"Only {r['history_days']} days of history / {int(r['coverage'] * 100)}% datapoint "
                f"coverage; need the minimum history and {int(MIN_COVERAGE * 100)}% coverage")
    i, o = r["idle"], r["over_provisioned"]
    st, v = i["status"], o.get("verdict")
    if st == "IDLE":
        return (f"CPU p95 {i['cpu_p95']}% < {IDLE_CPU_P95}% and p99-max {i['cpu_max']}% < {IDLE_CPU_MAX}%, "
                f"network p95 {i['net_p95_mb_per_hour']} MB/h < {IDLE_NET_P95_MB_PER_HOUR} "
                f"(total {i['net_mb_per_day']} MB/day < {IDLE_NET_MB_PER_DAY}), "
                f"EBS p95 {i['ebs_p95_mb_per_hour']} MB/h < {IDLE_EBS_P95_MB_PER_HOUR} "
                f"(total {i['ebs_mb_per_day']} MB/day < {IDLE_EBS_MB_PER_DAY}), no protective tag")
    parts = []
    if st == "NEEDS_REVIEW":
        why = (f"tag {', '.join(i['protect_tags'])}" if i["protect_tags"]
               else f"steady traffic (CV {i['net_hourly_cv']} < {STEADY_CV}, {i['net_mb_per_day']} MB/day)")
        parts.append(f"CPU is idle-level (p95 {i['cpu_p95']}%, max {i['cpu_max']}%) but {why}, so not called idle")
    elif i["cpu_p95"] >= IDLE_CPU_P95 or i["cpu_max"] >= IDLE_CPU_MAX:
        parts.append(f"Active: CPU p95 {i['cpu_p95']}% / max {i['cpu_max']}% above idle limits")
    else:
        over = []
        if i["net_p95_mb_per_hour"] >= IDLE_NET_P95_MB_PER_HOUR:
            over.append(f"network p95 {i['net_p95_mb_per_hour']} MB/h >= {IDLE_NET_P95_MB_PER_HOUR}")
        if i["ebs_p95_mb_per_hour"] >= IDLE_EBS_P95_MB_PER_HOUR:
            over.append(f"EBS p95 {i['ebs_p95_mb_per_hour']} MB/h >= {IDLE_EBS_P95_MB_PER_HOUR}")
        if i["net_mb_per_day"] >= IDLE_NET_MB_PER_DAY:
            over.append(f"network total {i['net_mb_per_day']} MB/day >= {IDLE_NET_MB_PER_DAY}")
        if i["ebs_mb_per_day"] >= IDLE_EBS_MB_PER_DAY:
            over.append(f"EBS total {i['ebs_mb_per_day']} MB/day >= {IDLE_EBS_MB_PER_DAY}")
        parts.append("Active: low CPU but " + ", ".join(over))
    if v == "OVER_PROVISIONED":
        save = f"${o['monthly_saving_usd']}/month" if o["monthly_saving_usd"] is not None else "saving unknown"
        parts.append(f"p99 max CPU {o['p99_cpu_max']}% needs {o['needed_vcpu']} of {o['current_vcpu']} vCPU "
                     f"(70% target) -> {o['recommended']} fits; {save}, {o['confidence']} confidence")
        if o.get("notes"):
            parts.append("notes: " + "; ".join(o["notes"]))
    elif v == "RIGHT_SIZED":
        parts.append(f"Right-sized: needs {o['needed_vcpu']} of {o['current_vcpu']} vCPU, "
                     f"no smaller size in the family passes CPU/memory/EBS checks")
    elif v and v.startswith("BLOCKED"):
        parts.append(f"Downsize blocked: {v.replace('BLOCKED_BY_', '').lower()} (burstable credits low/charged)")
    elif v == "UNSUPPORTED_INSTANCE_TYPE":
        parts.append("Size ladder for this family not found")
    return ". ".join(parts)


def export_csv(reports, path):
    import csv
    cols = ["name", "instance_id", "type", "category", "reason", "history_days", "coverage",
            "cpu_p95", "cpu_max", "net_p95_mb_per_hour", "ebs_p95_mb_per_hour", "net_mb_per_day", "ebs_mb_per_day", "net_hourly_cv",
            "p99_cpu_max", "needed_vcpu", "recommended", "monthly_saving_usd", "confidence", "warning"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in reports:
            i, o = r.get("idle", {}), r.get("over_provisioned", {})
            w.writerow({
                "name": r["name"], "instance_id": r["id"], "type": r["type"],
                "category": category(r), "reason": reason(r),
                "history_days": r.get("history_days"), "coverage": r.get("coverage"),
                "cpu_p95": i.get("cpu_p95"), "cpu_max": i.get("cpu_max"),
                "net_p95_mb_per_hour": i.get("net_p95_mb_per_hour"),
                "ebs_p95_mb_per_hour": i.get("ebs_p95_mb_per_hour"),
                "net_mb_per_day": i.get("net_mb_per_day"), "ebs_mb_per_day": i.get("ebs_mb_per_day"),
                "net_hourly_cv": i.get("net_hourly_cv"), "p99_cpu_max": o.get("p99_cpu_max"),
                "needed_vcpu": o.get("needed_vcpu"), "recommended": o.get("recommended"),
                "monthly_saving_usd": o.get("monthly_saving_usd"), "confidence": o.get("confidence"),
                "warning": r.get("warning"),
            })


def print_summary(reports):
    order = ["IDLE", "OVER-PROVISIONED", "OVER-PROVISIONED (needs review)",
             "NEEDS REVIEW", "ACTIVE / RIGHT-SIZED", "INSUFFICIENT DATA"]
    groups = {}
    for r in reports:
        groups.setdefault(category(r), []).append(r)
    if not reports:
        print("No running instances found.")
    for cat in order:
        if cat not in groups:
            continue
        print(f"\n=== {cat} ({len(groups[cat])}) ===")
        for r in groups[cat]:
            print(f"  {r['name']:<25} {r['id']:<20} {r['type']:<12} {detail(r)}")
            print(f"  {'':<25} reason: {reason(r)}")
            if r.get("warning"):
                print(f"  {'':<25} ! {r['warning']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--min-days", type=float, default=14, help="use 1 to test on 24h of data")
    ap.add_argument("--idle-cpu-p95", type=float, default=IDLE_CPU_P95)
    ap.add_argument("--idle-cpu-max", type=float, default=IDLE_CPU_MAX)
    ap.add_argument("--idle-net-p95", type=float, default=IDLE_NET_P95_MB_PER_HOUR, help="MB/hour")
    ap.add_argument("--idle-ebs-p95", type=float, default=IDLE_EBS_P95_MB_PER_HOUR, help="MB/hour")
    ap.add_argument("--idle-net-mb", type=float, default=IDLE_NET_MB_PER_DAY)
    ap.add_argument("--idle-ebs-mb", type=float, default=IDLE_EBS_MB_PER_DAY)
    ap.add_argument("--warmup-hours", type=float, default=BOOT_WARMUP_HOURS)
    ap.add_argument("--lookback-days", type=int, default=90)
    ap.add_argument("--json", action="store_true", help="print full evidence as JSON")
    ap.add_argument("--csv", default="ec2_classification.csv", help="CSV output path")
    a = ap.parse_args()
    IDLE_CPU_P95, IDLE_CPU_MAX = a.idle_cpu_p95, a.idle_cpu_max
    IDLE_NET_MB_PER_DAY, IDLE_EBS_MB_PER_DAY = a.idle_net_mb, a.idle_ebs_mb
    IDLE_NET_P95_MB_PER_HOUR, IDLE_EBS_P95_MB_PER_HOUR = a.idle_net_p95, a.idle_ebs_p95
    BOOT_WARMUP_HOURS = a.warmup_hours
    reports = run(a.region, a.min_days, a.lookback_days)
    if a.json:
        print(json.dumps(reports, indent=2, default=str))
    else:
        print_summary(reports)
    export_csv(reports, a.csv)
    print(f"\nCSV written to {os.path.abspath(a.csv)}")
