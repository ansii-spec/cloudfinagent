import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import boto3
import numpy as np
import pandas as pd

MB = 1_000_000            # decimal MB, same unit CloudWatch byte metrics are usually read in
BOOT_WARMUP_HOURS = 2     # ignore cloud-init / package updates right after launch
# TESTING: data quality (history length / gaps / memory) is computed and shown but NOT applied,
# so short test runs (~35 h) aren't capped at ~50 %. Set True for production (14+ days of data).
APPLY_DATA_QUALITY = False


def log_error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)


def explain_aws_error(e: Exception) -> str:
    """One-line, human-readable reason for common AWS failures."""
    name = type(e).__name__
    if name == "NoCredentialsError":
        return "no credentials: set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY"
    if name == "ClientError":
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        hint = {
            "AuthFailure": "access key / secret key is wrong",
            "UnauthorizedOperation": "IAM user lacks ec2:DescribeInstances permission",
            "AccessDenied": "IAM user lacks cloudwatch:GetMetricData permission",
        }.get(code)
        return f"{code}: {hint}" if hint else f"{code}: {e}"
    if name in ("EndpointConnectionError", "ConnectTimeoutError"):
        return "cannot reach AWS: check network / AWS_REGION"
    return f"{name}: {e}"


def get_aws_clients(access_key: str, secret_key: str, region: str):
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    # Pricing API only has endpoints in a few regions; us-east-1 serves every region's prices
    return (session.client("ec2"), session.client("cloudwatch"),
            session.client("pricing", region_name="us-east-1"))


def fetch_instance_metadata(ec2_client) -> dict[str, dict]:
    """Discovers ALL instances in the client's region (paginated, terminated ones excluded)."""
    now = datetime.now(timezone.utc)
    metadata = {}
    pages = ec2_client.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name",
                  "Values": ["pending", "running", "stopping", "stopped"]}])
    reservations = [r for page in pages for r in page.get("Reservations", [])]

    for reservation in reservations:
        for inst in reservation.get("Instances", []):
            iid = inst["InstanceId"]
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            launch_time = inst["LaunchTime"]
            age_hours = max((now - launch_time).total_seconds() / 3600.0, 1.0)
            volume_ids = [
                bdm["Ebs"]["VolumeId"]
                for bdm in inst.get("BlockDeviceMappings", [])
                if "Ebs" in bdm
            ]
            metadata[iid] = {
                "instance_id": iid,
                "name": tags.get("Name", ""),
                "tags": tags,
                "state": inst["State"]["Name"],
                "instance_type": inst["InstanceType"],
                "launch_time": launch_time,
                "age_hours": age_hours,
                "age_days": age_hours / 24.0,
                "volume_ids": volume_ids,
            }
    return metadata


def _stat_query(qid, namespace, name, dims, period, stat):
    return {"Id": qid, "MetricStat": {
        "Metric": {"Namespace": namespace, "MetricName": name, "Dimensions": dims},
        "Period": period, "Stat": stat}}


def fetch_cloudwatch_metrics(
    cw_client,
    instance_id: str,
    volume_ids: list[str],
    launch_time: datetime | None = None,
    lookback_hours: int = 35,
) -> dict:
    """
    Fetches CloudWatch metrics for the window and returns HOURLY arrays.

    - Raw data is pulled at 5-min resolution when the window is < 15 days (more points =
      meaningful p95/p99), otherwise hourly.
    - The window starts no earlier than launch + BOOT_WARMUP_HOURS.
    - Everything is reindexed onto a full regular grid, so missing hours are visible
      (previously the grid was built from the returned CPU timestamps, so gaps never showed).
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=lookback_hours)
    if launch_time is not None:
        start_time = max(start_time, launch_time + timedelta(hours=BOOT_WARMUP_HOURS))
    window_hours = max((end_time - start_time).total_seconds() / 3600.0, 0.0)
    period = 300 if window_hours < 15 * 24 else 3600
    # Align the window to whole periods: CloudWatch stamps datapoints relative to StartTime,
    # so an unaligned start (e.g. 19:24:37) gives timestamps that never match a 19:20/19:25 grid.
    start_time = pd.Timestamp(start_time).ceil(f"{period}s").to_pydatetime()
    end_time = pd.Timestamp(end_time).floor(f"{period}s").to_pydatetime()

    ec2_dim = [{"Name": "InstanceId", "Value": instance_id}]
    queries = [
        _stat_query("cpu_avg", "AWS/EC2", "CPUUtilization", ec2_dim, period, "Average"),
        _stat_query("cpu_max", "AWS/EC2", "CPUUtilization", ec2_dim, period, "Maximum"),
        _stat_query("net_in", "AWS/EC2", "NetworkIn", ec2_dim, period, "Sum"),
        _stat_query("net_out", "AWS/EC2", "NetworkOut", ec2_dim, period, "Sum"),
        _stat_query("ec2_ebs_read", "AWS/EC2", "EBSReadBytes", ec2_dim, period, "Sum"),
        _stat_query("ec2_ebs_write", "AWS/EC2", "EBSWriteBytes", ec2_dim, period, "Sum"),
        _stat_query("mem_used", "CWAgent", "mem_used_percent", ec2_dim, period, "Average"),
        # T-family only (empty otherwise): never downsize an instance that is out of credits
        _stat_query("credit_bal", "AWS/EC2", "CPUCreditBalance", ec2_dim, period, "Minimum"),
    ]
    # AWS/EBS per-volume metrics as a fallback when AWS/EC2 EBS metrics are empty
    for idx, vol_id in enumerate(volume_ids):
        vol_dim = [{"Name": "VolumeId", "Value": vol_id}]
        queries.append(_stat_query(f"vol_read_{idx}", "AWS/EBS", "VolumeReadBytes", vol_dim, period, "Sum"))
        queries.append(_stat_query(f"vol_write_{idx}", "AWS/EBS", "VolumeWriteBytes", vol_dim, period, "Sum"))

    series_map: dict[str, pd.Series] = {}
    kwargs = dict(MetricDataQueries=queries, StartTime=start_time, EndTime=end_time,
                  ScanBy="TimestampAscending")
    while True:  # get_metric_data paginates; 5-min data for 35 h is 420 points per metric
        response = cw_client.get_metric_data(**kwargs)
        for res in response.get("MetricDataResults", []):
            s = pd.Series(res["Values"], index=pd.to_datetime(res["Timestamps"], utc=True), dtype=float)
            series_map[res["Id"]] = pd.concat([series_map.get(res["Id"], pd.Series(dtype=float)), s])
        if not response.get("NextToken"):
            break
        kwargs["NextToken"] = response["NextToken"]

    cpu = series_map.get("cpu_avg", pd.Series(dtype=float))
    expected_hours = int(round(window_hours))
    if cpu.empty:
        return {"valid_hours": 0, "expected_hours": expected_hours}

    # Full regular grid from window start to end -> gaps become NaN rows
    grid = pd.date_range(pd.Timestamp(start_time), pd.Timestamp(end_time), freq=f"{period}s")
    df = pd.DataFrame(index=grid)
    for key, s in series_map.items():
        if s.empty:
            df[key] = np.nan
            continue
        s.index = pd.DatetimeIndex(s.index).floor(f"{period}s")  # snap leftover offset onto grid
        s = s[~s.index.duplicated()].sort_index()
        df[key] = s.reindex(grid)
    matched = int(df["cpu_avg"].notna().sum())
    if matched == 0 and len(cpu):
        log_error(f"{instance_id}: 0 of {len(cpu)} CPU timestamps matched the grid (first returned: {cpu.index.min()}, "
            f"grid starts {grid[0]})")

    # Long gaps: runs of > 3 h of missing CPU (measured BEFORE interpolation)
    missing = df["cpu_avg"].isna()
    run_id = (missing != missing.shift()).cumsum()
    run_len_h = missing.groupby(run_id).sum() * period / 3600
    long_gap_count = int((run_len_h > 3).sum())

    # Fill only gaps of up to 3 hours
    df = df.interpolate(method="linear", limit=int(3 * 3600 / period), limit_area="inside")

    ec2_ebs = df["ec2_ebs_read"].fillna(0.0) + df["ec2_ebs_write"].fillna(0.0)
    vol_cols = [c for c in df.columns if c.startswith("vol_")]
    vol_ebs = df[vol_cols].fillna(0.0).sum(axis=1) if vol_cols else pd.Series(0.0, index=grid)
    ebs = ec2_ebs if ec2_ebs.sum() > 0 else vol_ebs
    net = df["net_in"].fillna(0.0) + df["net_out"].fillna(0.0)

    # Aggregate to hourly: CPU avg -> mean, CPU max -> max, bytes -> sum (MB per hour)
    valid = df["cpu_avg"].notna()
    hourly = pd.DataFrame({
        "cpu_avg": df["cpu_avg"].resample("1h").mean(),
        "cpu_max": df["cpu_max"].resample("1h").max(),       # hourly MAXIMUM, as in the guide
        "net_mb": (net.where(valid) / MB).resample("1h").sum(min_count=1),
        "ebs_mb": (ebs.where(valid) / MB).resample("1h").sum(min_count=1),
    }).dropna(subset=["cpu_avg"])

    return {
        "valid_hours": int(len(hourly)),
        "expected_hours": expected_hours,
        "long_gap_count": long_gap_count,
        "has_memory_metric": bool(df["mem_used"].notna().any()),
        "period_s": period,
        # 5-min resolution samples for CPU percentiles (more points than hourly)
        "cpu_avg": df["cpu_avg"].dropna().to_numpy(),
        "cpu_max": df["cpu_max"].dropna().to_numpy(),
        # hourly MB for network / EBS percentiles and CV
        "network_mb_hourly": hourly["net_mb"].fillna(0.0).to_numpy(),
        "ebs_mb_hourly": hourly["ebs_mb"].fillna(0.0).to_numpy(),
        # for the over-provisioned check (scenario 3)
        "cpu_max_hourly": hourly["cpu_max"].dropna().to_numpy(),
        "mem_used_pct": df["mem_used"].dropna().to_numpy(),
        "credit_balance": df["credit_bal"].dropna().to_numpy(),   # T-family only, else empty
        "credit_balance_min": (float(df["credit_bal"].min())
                               if df["credit_bal"].notna().any() else None),
    }


def _log_margin(obs: float, lim: float, floor: float) -> float:
    """
    How far a value sits from its limit on a log scale, in [-1, 1].
    +1 = 10x (or more) below the limit, 0 = at the limit, -1 = 10x (or more) above.
    Log scale because I/O spans orders of magnitude: 2x over and 1000x over must differ.
    """
    ratio = max(obs, floor) / lim
    return max(-1.0, min(1.0, -math.log10(ratio)))


# ----------------------------------------------------------------------------------------------
# Cascade thresholds: a check "wins" only if its confidence score reaches its threshold.
# Starting values (not from the guide); tune them on labelled test instances.
# ----------------------------------------------------------------------------------------------
IDLE_THRESHOLD = 65.0     # idle score >= this -> IDLE
OVER_THRESHOLD = 60.0     # over-provisioned score >= this -> OVER_PROVISIONED
UNDER_THRESHOLD = 70.0    # under-provisioned score >= this -> UNDER_PROVISIONED

# Tags that mark an instance as sensitive: it can be right-sized but NEVER declared idle.
# Long words match as substrings ("db-replica"), short ones only as whole tokens ("Owner=Andrew" != dr)
PROTECT_SUBSTRINGS = ("replica", "standby", "failover", "backup", "database", "postgres", "mysql",
                      "mongo", "redis", "primary", "master", "bastion", "proxy", "critical",
                      "production", "donotstop", "do-not-stop", "protected")
PROTECT_TOKENS = ("db", "dr", "rds", "vpn", "prod", "ha")


def protected_tags(tags: dict) -> list[str]:
    text = " ".join(f"{k}={v}" for k, v in tags.items()).lower()
    tokens = set(re.split(r"[^a-z0-9]+", text))
    return [p for p in PROTECT_SUBSTRINGS if p in text] + [p for p in PROTECT_TOKENS if p in tokens]


def _band(score: float) -> str:
    return "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"


def classify_and_score(
    meta: dict,
    metrics: dict,
    # Set to ~20h for a 24-35h test dataset (production default is 14 * 24 = 336h)
    min_history_hours: int = 20,
    target_history_hours: int = 14 * 24,
    cpu_p95_limit: float = 5.0,          # % (CPU Average)
    cpu_max_limit: float = 10.0,         # % (p99 of CPU Maximum, not the single top sample)
    net_p95_mb_per_hour: float = 20.0,   # p95 of hourly network in+out
    ebs_p95_mb_per_hour: float = 60.0,   # p95 of hourly EBS read+write
    ebs_heavy_factor: float = 10.0,      # EBS >= 10x the limit with idle CPU = disk workload, block idle
    steady_cv_limit: float = 0.5,
    steady_min_mb_per_day: float = 50.0,
    under_cpu_p99_limit: float = 80.0,   # p99 of 5-min CPU Average (60-70 % is healthy, not "too small")
    credit_starved_below: float = 5.0,   # T-family: CPU credit balance under this = throttled to baseline
) -> dict:
    """
    Computes the IDLE score (with guards) and the UNDER-PROVISIONED score for one instance.
    The pipeline (__main__) runs the cascade: idle -> over-provisioned -> under-provisioned.
    """
    valid_hours = metrics.get("valid_hours", 0)
    base = {"instance_id": meta["instance_id"], "name": meta["name"]}
    if valid_hours < min_history_hours:
        return {**base, "status": "INSUFFICIENT_DATA", "confidence": {"score": 0.0, "band": "NONE"},
                "reason": f"Only {valid_hours}h available (minimum {min_history_hours}h)"}

    cpu_avg, cpu_max = metrics["cpu_avg"], metrics["cpu_max"]
    net_h, ebs_h = metrics["network_mb_hourly"], metrics["ebs_mb_hourly"]

    # ---- aggregates (percentiles, not raw totals / single max)
    cpu_p95 = float(np.percentile(cpu_avg, 95))
    cpu_p99 = float(np.percentile(cpu_avg, 99))
    share_over = float(np.mean(cpu_avg >= under_cpu_p99_limit))
    cpu_p99_max = float(np.percentile(cpu_max, 99))
    net_p95 = float(np.percentile(net_h, 95))
    ebs_p95 = float(np.percentile(ebs_h, 95))
    days = max(valid_hours / 24.0, 1 / 24)
    net_per_day = float(net_h.sum() / days)
    ebs_per_day = float(ebs_h.sum() / days)
    net_mean = float(np.mean(net_h))
    net_cv = float(np.std(net_h) / net_mean) if net_mean > 0 else None

    # ---- IDLE score: log-scale margins (+1 = 10x below limit, 0 = at limit, -1 = 10x above)
    margins = {
        "cpu_p95": _log_margin(cpu_p95, cpu_p95_limit, 0.05),
        "cpu_max": _log_margin(cpu_p99_max, cpu_max_limit, 0.1),
        "net_p95": _log_margin(net_p95, net_p95_mb_per_hour, 0.01),
        "ebs_p95": _log_margin(ebs_p95, ebs_p95_mb_per_hour, 0.01),
    }
    weights = {"cpu_p95": 0.35, "cpu_max": 0.20, "net_p95": 0.30, "ebs_p95": 0.15}
    weighted = sum(weights[k] * margins[k] for k in margins)
    # CPU and network are the "is it doing work" signals: the weakest of them must also be idle.
    # EBS only lowers the average (Pleco: background disk noise does not prove useful work).
    weakest_work = min(margins["cpu_p95"], margins["cpu_max"], margins["net_p95"])
    idle_evidence = 0.5 * weighted + 0.5 * weakest_work            # -1 .. +1
    idle_score = round((idle_evidence + 1) / 2 * 100, 1)           # 0 .. 100, 50 = at the limits

    # ---- guards: sensitive instances are never IDLE, whatever the score
    tag_hits = protected_tags(meta["tags"])
    steady = net_cv is not None and net_cv < steady_cv_limit and net_per_day >= steady_min_mb_per_day
    disk_heavy = ebs_p95 >= ebs_heavy_factor * ebs_p95_mb_per_hour
    guards = []
    if tag_hits:
        guards.append(f"sensitive tag ({', '.join(tag_hits)})")
    if steady:
        guards.append(f"steady network traffic (CV {net_cv:.2f}, {net_per_day:.0f} MB/day)")
    if disk_heavy:
        guards.append(f"heavy disk activity (EBS p95 {ebs_p95:.0f} MB/h)")

    idle = {
        "score": idle_score, "band": _band(idle_score), "blocked_by": guards,
        "reason": (f"idle score {idle_score}%: CPU p95 {cpu_p95:.2f}%, p99-max {cpu_p99_max:.2f}%, "
                   f"net p95 {net_p95:.2f} MB/h, EBS p95 {ebs_p95:.1f} MB/h"),
    }

    # ---- UNDER-PROVISIONED score: depth into the limit..100 band x how sustained it is.
    # Geometric mean: a box must be BOTH far over the limit AND over it often (bursts don't count).
    depth = max(0.0, (cpu_p99 - under_cpu_p99_limit) / max(100.0 - under_cpu_p99_limit, 1e-9))
    sustained = min(1.0, share_over / 0.10)            # >= 10 % of samples above limit = full
    if cpu_p99 >= under_cpu_p99_limit:
        under_score = round((0.5 + 0.5 * math.sqrt(depth * sustained)) * 100, 1)
    else:
        under_score = round(50.0 * cpu_p99 / under_cpu_p99_limit, 1)   # below limit -> < 50
    under_reason = (f"CPU p99 {cpu_p99:.1f}% vs {under_cpu_p99_limit}% "
                    f"({share_over * 100:.1f}% of the time above it): consider the next size up")

    # T-family credit starvation: a t3 with no credits is capped at its baseline (e.g. 20 %), so its
    # CPU can never reach the limit above - the CPU rule alone would miss it. Same sqrt shape:
    # starved >= 10 % of the time = 100, ~2 % = 72, a single dip = ~55.
    credits = metrics.get("credit_balance", np.array([]))
    if len(credits):
        share_starved = float(np.mean(credits < credit_starved_below))
        if share_starved > 0:
            credit_score = round((0.5 + 0.5 * math.sqrt(min(1.0, share_starved / 0.10))) * 100, 1)
            if credit_score > under_score:
                under_score = credit_score
                under_reason = (f"CPU credits below {credit_starved_below} for {share_starved * 100:.1f}% "
                                f"of the time (min {credits.min():.1f}): throttled to baseline, "
                                f"consider a larger size or unlimited mode")
    under = {"score": under_score, "band": _band(under_score), "reason": under_reason}

    # ---- data quality (computed, applied only when APPLY_DATA_QUALITY is True)
    w_history = 0.5 + 0.5 * min(1.0, valid_hours / target_history_hours)
    completeness = min(1.0, valid_hours / max(metrics["expected_hours"], 1))
    w_gaps = max(0.0, completeness - 0.05 * metrics["long_gap_count"])
    w_metrics = 1.0 if metrics["has_memory_metric"] else 0.9
    data_quality = max(0.0, min(1.0, w_history * w_gaps * w_metrics))
    if APPLY_DATA_QUALITY:
        idle["score"] = round(idle["score"] * data_quality, 1)
        under["score"] = round(under["score"] * data_quality, 1)

    return {
        **base,
        "hours_analyzed": valid_hours,
        "status": "SCORED",
        "idle": idle,
        "underprovisioned": under,
        "data_quality": round(data_quality, 3),
        "metrics": {
            "cpu_p95_pct": round(cpu_p95, 3), "cpu_p99_pct": round(cpu_p99, 3),
            "cpu_p99_max_pct": round(cpu_p99_max, 3), "cpu_share_over_under_limit": round(share_over, 3),
            "net_p95_mb_per_hour": round(net_p95, 3), "ebs_p95_mb_per_hour": round(ebs_p95, 3),
            "network_mb_per_day": round(net_per_day, 2), "ebs_mb_per_day": round(ebs_per_day, 2),
            "network_cv": round(net_cv, 3) if net_cv is not None else None,
            "margins": {k: round(v, 2) for k, v in margins.items()},
        },
    }


def run_cascade(r: dict, over: dict | None) -> dict:
    """
    Decides the final label from the scores, in order:
      1. IDLE              if idle score >= IDLE_THRESHOLD and no guard blocks it
      2. OVER_PROVISIONED  if over score >= OVER_THRESHOLD
      3. UNDER_PROVISIONED if under score >= UNDER_THRESHOLD
      4. NEEDS_REVIEW      if idle-level but a guard blocked it (sensitive tag, replica traffic, disk)
      5. ACTIVE            otherwise
    """
    idle, under = r["idle"], r["underprovisioned"]
    over_score = over["confidence"]["score"] if over and over["status"] == "found" else 0.0
    scores = f"[idle {idle['score']} | over {over_score} | under {under['score']}]"

    if idle["score"] >= IDLE_THRESHOLD and not idle["blocked_by"]:
        status, conf, reason = "IDLE", idle["score"], idle["reason"]
    elif over and over["status"] == "found" and over_score >= OVER_THRESHOLD:
        status, conf, reason = "OVER_PROVISIONED", over_score, over["reason"]
    elif under["score"] >= UNDER_THRESHOLD:
        status, conf, reason = "UNDER_PROVISIONED", under["score"], under["reason"]
    elif idle["score"] >= IDLE_THRESHOLD:
        status, conf = "NEEDS_REVIEW", idle["score"]
        reason = "idle-level usage, but NOT declared idle: " + "; ".join(idle["blocked_by"])
    else:
        status = "ACTIVE"
        conf = round(100 - max(idle["score"], over_score, under["score"]) / 2, 1)
        reason = "no idle / over / under score reached its threshold"
        if over and over["status"] != "found":
            reason += f" (right-size: {over['verdict']})"
    if idle["blocked_by"] and status != "NEEDS_REVIEW" and idle["score"] >= IDLE_THRESHOLD:
        # only worth saying when the guard actually stopped an IDLE verdict
        reason += " | blocked from IDLE: " + "; ".join(idle["blocked_by"])
    return {**r, "status": status, "reason": f"{reason} {scores}",
            "confidence": {"score": conf, "band": _band(conf)}, "overprovisioned": over}


# ----------------------------------------------------------------------------------------------
# Over-provisioned check (guide step 6, "Scenario 3: over-provisioned application server")
# ----------------------------------------------------------------------------------------------
_ladder_cache: dict[str, list[dict]] = {}

# Baseline CPU (% per vCPU) of burstable sizes: the level they can sustain without draining credits.
# Not exposed by describe_instance_types, so taken from the AWS "burstable performance" docs.
T_BASELINE_PCT = {
    "nano": 5, "micro": 10, "small": 20, "medium": 20, "large": 30, "xlarge": 40, "2xlarge": 40,
}
T_BASELINE_OVERRIDES = {  # t2 differs from t3/t3a/t4g at the top end
    "t2.xlarge": 22.5, "t2.2xlarge": 17,
}


def t_baseline_vcpu(t: dict) -> float | None:
    """Sustainable CPU of a burstable size, in vCPUs (e.g. t3.small: 2 x 20% = 0.4)."""
    if not t["burstable"]:
        return None
    pct = T_BASELINE_OVERRIDES.get(t["name"], T_BASELINE_PCT.get(t["name"].split(".", 1)[1]))
    return None if pct is None else t["vcpu"] * pct / 100
_price_cache: dict[tuple, float | None] = {}


def _type_info(t: dict) -> dict:
    net = t.get("NetworkInfo", {}).get("NetworkCards", [{}])[0]
    ebs = t.get("EbsInfo", {}).get("EbsOptimizedInfo", {})
    return {
        "name": t["InstanceType"],
        "vcpu": t["VCpuInfo"]["DefaultVCpus"],
        "mem_gib": t["MemoryInfo"]["SizeInMiB"] / 1024,
        "arch": tuple(sorted(t["ProcessorInfo"]["SupportedArchitectures"])),
        "burstable": t.get("BurstablePerformanceSupported", False),
        "net_baseline_mbps": (net.get("BaselineBandwidthInGbps") or 0) * 1000 or None,
        "ebs_baseline_mbs": ebs.get("BaselineThroughputInMBps"),
    }


def family_ladder(ec2_client, instance_type: str) -> list[dict]:
    """All sizes of the same family + architecture, smallest first (fetched from AWS, cached)."""
    family = instance_type.split(".")[0]
    if family not in _ladder_cache:
        sizes = []
        for page in ec2_client.get_paginator("describe_instance_types").paginate(
                Filters=[{"Name": "instance-type", "Values": [f"{family}.*"]},
                         {"Name": "bare-metal", "Values": ["false"]}]):
            sizes += [_type_info(t) for t in page["InstanceTypes"]]
        _ladder_cache[family] = sorted(sizes, key=lambda x: (x["vcpu"], x["mem_gib"]))
    ladder = _ladder_cache[family]
    cur = next((x for x in ladder if x["name"] == instance_type), None)
    return [x for x in ladder if cur is None or x["arch"] == cur["arch"]]


def hourly_price(pricing_client, instance_type: str, region: str) -> float | None:
    """Linux on-demand USD/hour from the Pricing API, None if unavailable (cached)."""
    key = (instance_type, region)
    if key not in _price_cache:
        try:
            f = {"instanceType": instance_type, "regionCode": region, "operatingSystem": "Linux",
                 "tenancy": "Shared", "preInstalledSw": "NA", "capacitystatus": "Used"}
            resp = pricing_client.get_products(
                ServiceCode="AmazonEC2", MaxResults=1,
                Filters=[{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in f.items()])
            import json
            term = next(iter(json.loads(resp["PriceList"][0])["terms"]["OnDemand"].values()))
            _price_cache[key] = float(next(iter(term["priceDimensions"].values()))["pricePerUnit"]["USD"])
        except Exception as e:  # noqa: BLE001 - price is optional, verdict still stands
            log_error(f"price lookup for {instance_type} failed: {explain_aws_error(e)}")
            _price_cache[key] = None
    return _price_cache[key]


def check_overprovisioned(
    meta: dict,
    metrics: dict,
    ladder: list[dict],
    price_fn,
    target_util: float = 0.70,         # keep 30 % headroom (guide)
    mem_percentile: float = 95,        # guide: p95 memory
    min_credit_balance: float = 20.0,  # T-family: below this the instance is already starved
) -> dict:
    """
    Scenario 3 from the guide, step by step:
      p99 of hourly MAX CPU -> CPU used at worst = vCPU x p99 -> / 0.70 headroom
      -> needed <= 1/2 current: one size down; <= 1/4: two sizes down
      -> memory (p95 / 0.70), network and EBS must fit the candidate -> monthly saving.
    Returns status "found" | "none" with every step recorded as evidence.
    """
    steps = []
    cur = next((x for x in ladder if x["name"] == meta["instance_type"]), None)
    if cur is None:
        return {"status": "none", "verdict": "UNKNOWN_TYPE", "steps": steps,
                "reason": f"{meta['instance_type']} not found in its family list"}

    cpu_max_h = metrics["cpu_max_hourly"]
    p99 = float(np.percentile(cpu_max_h, 99))
    used = cur["vcpu"] * p99 / 100
    needed = used / target_util
    steps += [("p99 of hourly max CPU", f"{len(cpu_max_h)} hourly values", f"{p99:.2f}%"),
              ("CPU used at worst", f"{cur['vcpu']} vCPU x {p99 / 100:.4f}", f"{used:.2f} vCPU"),
              ("Add 30% headroom", f"{used:.2f} / {target_util}", f"{needed:.2f} vCPU needed")]

    half, quarter = cur["vcpu"] / 2, cur["vcpu"] / 4
    size_steps = 2 if needed <= quarter else 1 if needed <= half else 0
    steps += [("Half of current?", f"{needed:.2f} vs {half:g}", "yes" if needed <= half else "no"),
              ("Quarter of current?", f"{needed:.2f} vs {quarter:g}", "yes" if needed <= quarter else "no")]
    ev = {"p99_cpu_max": round(p99, 2), "needed_vcpu": round(needed, 2), "current_vcpu": cur["vcpu"]}
    if size_steps == 0 and not cur["burstable"]:
        return {"status": "none", "verdict": "RIGHT_SIZED", "steps": steps, **ev,
                "reason": f"needs {needed:.2f} of {cur['vcpu']} vCPU (more than half): right-sized"}

    # Burstable guard (guide): never downsize a T instance whose credits are near zero
    bal = metrics.get("credit_balance_min")
    if cur["burstable"] and bal is not None and bal < min_credit_balance:
        steps.append(("CPU credits", f"min balance {bal:.1f} < {min_credit_balance}", "blocked"))
        return {"status": "none", "verdict": "BLOCKED_BY_CREDITS", "steps": steps, **ev,
                "reason": f"T-family credit balance fell to {bal:.1f}: already starved, do not downsize"}

    mem = metrics.get("mem_used_pct", np.array([]))
    has_mem = len(mem) > 0
    mem_need = cur["mem_gib"] * float(np.percentile(mem, mem_percentile)) / 100 / target_util if has_mem else None
    # peak network (Mbps) and EBS (MB/s) from the busiest hours (p99 of hourly totals)
    net_mbps = float(np.percentile(metrics["network_mb_hourly"], 99)) * 8 / 3600
    ebs_mbs = float(np.percentile(metrics["ebs_mb_hourly"], 99)) / 3600

    # Candidate list, deepest downsize first (tried in order; first one that fits wins)
    options = []
    if cur["burstable"]:
        # T-family: sizes differ in memory + baseline, not vCPU. Up to 2 sizes down (by memory),
        # each must keep vCPU >= peak need AND a baseline that covers the AVERAGE load (credits).
        mean_vcpu = cur["vcpu"] * float(np.mean(metrics["cpu_avg"])) / 100
        steps.append(("T-family path", f"average CPU {np.mean(metrics['cpu_avg']):.1f}% x {cur['vcpu']} vCPU",
                      f"{mean_vcpu:.2f} vCPU must fit under the candidate's baseline"))
        smaller = [x for x in ladder if x["mem_gib"] < cur["mem_gib"]]
        options = smaller[-2:]                            # nearest two smaller sizes, deepest first
    else:
        mean_vcpu = None
        for k in range(size_steps, 0, -1):
            target_vcpu = cur["vcpu"] / 2 ** k
            cands = [x for x in ladder if x["vcpu"] == target_vcpu and x["mem_gib"] <= cur["mem_gib"]]
            if not cands:
                steps.append((f"{k} size(s) down", f"no {target_vcpu:g}-vCPU size in family", "skip"))
                continue
            options.append(max(cands, key=lambda x: x["mem_gib"]))   # closest memory ratio

    for cand in options:
        blocked = []
        if cand["vcpu"] < needed:
            blocked.append(f"cpu ({needed:.2f} > {cand['vcpu']} vCPU)")
        base = t_baseline_vcpu(cand)
        if mean_vcpu is not None and (base is None or mean_vcpu > base):
            blocked.append(f"baseline ({mean_vcpu:.2f} > {base if base is not None else '?'} vCPU: "
                           f"would drain credits)")
        if has_mem and mem_need > cand["mem_gib"]:
            blocked.append(f"memory ({mem_need:.1f} > {cand['mem_gib']:g} GiB)")
        if cand["net_baseline_mbps"] and net_mbps > cand["net_baseline_mbps"] * target_util:
            blocked.append(f"network ({net_mbps:.0f} Mbps)")
        if cand["ebs_baseline_mbs"] and ebs_mbs > cand["ebs_baseline_mbs"] * target_util:
            blocked.append(f"EBS ({ebs_mbs:.1f} MB/s)")
        if blocked:
            steps.append((f"Candidate {cand['name']}", ", ".join(blocked), "rejected"))
            continue

        steps.append(("Candidate", f"{cand['name']}: {cand['vcpu']} vCPU, {cand['mem_gib']:g} GiB",
                      "fits the CPU need"))
        steps.append(("Memory check",
                      f"p95 {np.percentile(mem, mem_percentile):.0f}% of {cur['mem_gib']:g} GiB / {target_util}"
                      f" = {mem_need:.1f} GiB" if has_mem else "no CloudWatch agent data",
                      "fits" if has_mem else "NOT CHECKED (lower confidence)"))
        steps.append(("Network and disk", f"peak {net_mbps:.1f} Mbps, EBS {ebs_mbs:.2f} MB/s", "fits"))

        p_now, p_new = price_fn(cur["name"]), price_fn(cand["name"])
        saving = round((p_now - p_new) * 730, 2) if p_now and p_new else None
        steps.append(("Saving", f"730 h x (${p_now} - ${p_new})" if saving is not None else "price unavailable",
                      f"${saving}/month" if saving is not None else "-"))

        # Confidence: how much room the candidate leaves, discounted without memory data.
        # Standard: distance under the "half" line. T-family: headroom under the candidate baseline.
        if mean_vcpu is not None:
            fit = max(0.0, min(1.0, 1.0 - mean_vcpu / base))
        else:
            fit = max(0.0, min(1.0, 1.0 - needed / half))
        evidence = fit * (1.0 if has_mem else 0.5)   # guide: lower confidence without memory
        score = round((0.5 + 0.5 * evidence) * 100, 1)
        band = "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"
        return {
            "status": "found", "verdict": "OVER_PROVISIONED", "steps": steps, **ev,
            "current": cur["name"], "recommended": cand["name"], "monthly_saving_usd": saving,
            "memory_checked": has_mem,
            "confidence": {"score": score, "band": band},
            "reason": (f"p99 max CPU {p99:.1f}% -> needs {needed:.2f} of {cur['vcpu']} vCPU: "
                       f"{cur['name']} -> {cand['name']}"
                       + (f", saves ${saving}/month" if saving is not None else "")
                       + ("" if has_mem else " (memory not checked)")),
        }

    if not options and not cur["burstable"]:
        # e.g. t3.nano..t3.medium are ALL 2 vCPU: the vCPU-halving rule has nowhere to go
        return {"status": "none", "verdict": "NO_SMALLER_SIZE", "steps": steps, **ev,
                "reason": f"needs only {needed:.2f} vCPU, but {cur['name']} is already the smallest "
                          f"vCPU count in its family (smaller sizes differ only in memory)"}
    if not options:
        return {"status": "none", "verdict": "NO_SMALLER_SIZE", "steps": steps, **ev,
                "reason": f"{cur['name']} is already the smallest size in its family"}
    return {"status": "none", "verdict": "RIGHT_SIZED" if cur["burstable"] else "BLOCKED",
            "steps": steps, **ev,
            "reason": "no smaller size fits: " + steps[-1][1]}


REPORTED_STATUSES = ("IDLE", "OVER_PROVISIONED", "UNDER_PROVISIONED", "NEEDS_REVIEW")


def print_table(results: list[dict]) -> None:
    hidden = [r for r in results if r["status"] not in REPORTED_STATUSES]
    results = [r for r in results if r["status"] in REPORTED_STATUSES]
    order = {"IDLE": 0, "NEEDS_REVIEW": 1, "OVER_PROVISIONED": 2, "UNDER_PROVISIONED": 3, "ACTIVE": 4,
             "STOPPED": 5, "INSUFFICIENT_DATA": 6, "ERROR": 7}
    results = sorted(results, key=lambda r: (order.get(r["status"], 9), -r["confidence"]["score"]))
    hdr = f"{'NAME':<28} {'INSTANCE':<20} {'TYPE':<11} {'STATUS':<17} {'CONF':>6} {'BAND':<6}  REASON"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        c = r["confidence"]
        conf = f"{c['score']:.1f}%" if c["score"] else "-"
        print(f"{(r['name'] or '(no name)')[:28]:<28} {r['instance_id']:<20} {r.get('instance_type', ''):<11} "
              f"{r['status']:<17} {conf:>6} {c['band']:<6}  {r['reason']}")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\nSummary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9))))
    if hidden:
        print(f"Not shown ({len(hidden)}): " + ", ".join(
            f"{r['name'] or r['instance_id']}={r['status']}"
            for r in sorted(hidden, key=lambda r: order.get(r["status"], 9))))


if __name__ == "__main__":
    AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

    missing = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not os.getenv(k)]
    if missing:
        log_error(f"environment variable(s) not set: {', '.join(missing)}")
        sys.exit(1)

    try:
        ec2_client, cw_client, pricing_client = get_aws_clients(
            os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"], AWS_REGION)
        instances_meta = fetch_instance_metadata(ec2_client)
    except Exception as e:  # noqa: BLE001
        log_error(f"could not list instances in {AWS_REGION}: {explain_aws_error(e)}")
        sys.exit(1)

    if not instances_meta:
        print(f"No instances found in {AWS_REGION}.")
        sys.exit(0)
    print(f"Analysing {len(instances_meta)} instance(s) in {AWS_REGION}...\n")

    results = []
    for iid, meta in instances_meta.items():
        base = {"instance_id": iid, "name": meta["name"], "instance_type": meta["instance_type"],
                "confidence": {"score": 0.0, "band": "NONE"}}
        if meta["state"] != "running":
            results.append({**base, "status": "STOPPED",
                            "reason": f"state={meta['state']}: no live metrics (stopped instances "
                                      f"still pay for EBS)"})
            continue
        try:
            metrics = fetch_cloudwatch_metrics(cw_client, instance_id=iid, volume_ids=meta["volume_ids"],
                                               launch_time=meta["launch_time"], lookback_hours=35)
            # Cascade: idle -> over-provisioned -> under-provisioned (see run_cascade)
            r = classify_and_score(meta, metrics, min_history_hours=20)
            if r["status"] != "INSUFFICIENT_DATA":
                idle_wins = r["idle"]["score"] >= IDLE_THRESHOLD and not r["idle"]["blocked_by"]
                over = None if idle_wins else check_overprovisioned(   # only if not already idle
                    meta, metrics, family_ladder(ec2_client, meta["instance_type"]),
                    lambda t: hourly_price(pricing_client, t, AWS_REGION))
                r = run_cascade(r, over)
            results.append({**base, **r})
        except Exception as e:  # noqa: BLE001 - one bad instance must not stop the scan
            log_error(f"{iid} ({meta['name'] or 'no name'}): {explain_aws_error(e)}")
            results.append({**base, "status": "ERROR", "reason": explain_aws_error(e)})

    print_table(results)
    sys.exit(1 if any(r["status"] == "ERROR" for r in results) else 0)
