"""
Over-provisioned detection for ONE EC2 instance, using dummy data.

Scenario (same as the table in the guide):
    m5.2xlarge (8 vCPU, 32 GiB), p99 of hourly max CPU = 20%
    -> needs 2.29 vCPU -> recommend m5.xlarge -> saves about $140 a month

Run:  python overprovisioned_check.py
Needs: pip install numpy pandas
"""
import numpy as np
import pandas as pd

# ----------------------------------------------------------------- settings
TARGET_UTIL = 0.70        # keep 30% headroom
MIN_DAYS = 14             # minimum history
MIN_COVERAGE = 0.90       # require at least 90% valid non-NaN hourly points
MAX_STEPS_DOWN = 2        # never recommend more than two sizes down at once
HOURS_PER_MONTH = 730

# m5 family. Prices are us-east-1 on-demand examples; network and EBS are the
# "up to" burst limits. Check current AWS pricing and instance tables.
SIZES = [
    {"name": "m5.large",   "vcpu": 2,  "mem_gib": 8,  "price": 0.096, "net_mbps": 10_000, "ebs_mbps": 4_750},
    {"name": "m5.xlarge",  "vcpu": 4,  "mem_gib": 16, "price": 0.192, "net_mbps": 10_000, "ebs_mbps": 4_750},
    {"name": "m5.2xlarge", "vcpu": 8,  "mem_gib": 32, "price": 0.384, "net_mbps": 10_000, "ebs_mbps": 4_750},
    {"name": "m5.4xlarge", "vcpu": 16, "mem_gib": 64, "price": 0.768, "net_mbps": 10_000, "ebs_mbps": 4_750},
]


# ----------------------------------------------------------------- dummy data
def make_dummy_data(days=14, seed=None, scenario="subtle_cpu"):
    """
    Generate natural, organic hourly CloudWatch metrics without hardcoded percentiles.
    """
    rng = np.random.default_rng(seed)
    n = days * 24
    idx = pd.date_range("2026-11-01", periods=n, freq="h", tz="UTC")

    hours = np.asarray(idx.hour)
    is_weekend = np.asarray(idx.day_of_week >= 5)

    # Smooth 24-hour diurnal wave peaking around 14:00 UTC (0.0 at night -> 1.0 afternoon)
    diurnal = 0.5 * (1 - np.cos(2 * np.pi * (hours - 2) / 24))
    weekday_scale = np.where(is_weekend, 0.45, 1.0)
    load_factor = diurnal * weekday_scale

    if scenario == "two_step_blocked_to_one":
        # Low CPU (eligible for 2 sizes down), moderate RAM (blocks 2 sizes, allows 1 size)
        base_cpu = 4.0 + 7.5 * load_factor + rng.normal(0, 1.5, n)
        spike_mask = rng.random(n) < 0.025  # ~2.5% random cron/batch spikes
        cpu = np.clip(base_cpu + spike_mask * rng.uniform(5, 10, n), 1.0, 99.0)

        # Memory has a steady baseline (caches/JVM) + gentle daily drift
        mem = 24.0 + 5.5 * load_factor + rng.normal(0, 1.8, n)
        mem = np.clip(mem, 10.0, 95.0)
    else:
        # "subtle_cpu": Looks active during business hours, with a few sharp 1-hour spikes
        base_cpu = 8.0 + 16.5 * load_factor + rng.normal(0, 2.3, n)
        spike_indices = rng.choice(n, size=max(2, days // 5), replace=False)
        cpu = base_cpu.copy()
        cpu[spike_indices] += rng.uniform(14.0, 22.0, size=len(spike_indices))
        cpu = np.clip(cpu, 2.0, 99.0)

        # Memory stays moderately low (22% - 33%), correlated slightly with load
        mem = 21.0 + 8.5 * load_factor + rng.normal(0, 2.0, n)
        mem = np.clip(mem, 10.0, 95.0)

    # Natural network traffic (log-normal heavy-tailed bursts scaled by activity)
    net = rng.lognormal(mean=23.2, sigma=0.55, size=n) * (0.5 + 0.8 * load_factor)

    # Natural EBS I/O (baseline logging + occasional batch writes)
    ebs = rng.lognormal(mean=21.5, sigma=0.60, size=n) * (0.6 + 0.6 * load_factor)

    return pd.DataFrame({
        "cpu_max_pct": np.round(cpu, 2),
        "mem_used_pct": np.round(mem, 2),
        "net_bytes": np.round(net, 0),
        "ebs_bytes": np.round(ebs, 0),
    }, index=idx)

# ----------------------------------------------------------------- the detection
def check_overprovisioned(
    df,
    current_name,
    burstable=False,
    in_asg=False,
    idle_status="ACTIVE",
):
    """
    Evaluate whether an EC2 instance is over-provisioned.

    Returns a dictionary aligned with the pipeline status model:
      - status: "found" | "none" | "not_enough_data"
      - verdict: detailed outcome code
      - steps: list of (step_name, calculation, result) tuples
    """
    steps = []

    # Pre-check: Skip if Step 5 already confirmed the instance is IDLE
    if idle_status == "IDLE":
        steps.append(("Idle gate", "Instance already classified as IDLE in Step 5", "skip right-sizing"))
        return {"status": "none", "verdict": "SKIPPED_IDLE", "steps": steps}

    # Pre-check: Verify instance type exists in catalog
    names = [s["name"] for s in SIZES]
    if current_name not in names:
        steps.append(("Instance lookup", f"{current_name} not found in instance table", "stop"))
        return {"status": "none", "verdict": "UNSUPPORTED_INSTANCE_TYPE", "steps": steps}

    cur_i = names.index(current_name)
    cur = SIZES[cur_i]

    # Step 1: Data sufficiency gate (time span + actual non-NaN coverage)
    if len(df) == 0:
        steps.append(("Data length", "0 rows provided", "stop"))
        return {"status": "not_enough_data", "verdict": "INSUFFICIENT_DATA", "steps": steps}

    span_days = (df.index[-1] - df.index[0]).total_seconds() / 86400 + (1 / 24)
    valid_cpu_hours = int(df["cpu_max_pct"].notna().sum())
    min_required_hours = int(MIN_DAYS * 24 * MIN_COVERAGE)

    has_enough_span = span_days >= MIN_DAYS
    has_enough_points = valid_cpu_hours >= min_required_hours

    steps.append((
        "Data length",
        f"{span_days:.1f} days span, {valid_cpu_hours} valid hours (min {MIN_DAYS}d / {min_required_hours}h)",
        "pass" if (has_enough_span and has_enough_points) else "stop",
    ))
    if not (has_enough_span and has_enough_points):
        return {"status": "not_enough_data", "verdict": "INSUFFICIENT_DATA", "steps": steps}

    # Step 2: p99 of the hourly MAX CPU = realistic worst case (NaN-safe)
    p99 = float(np.nanquantile(df["cpu_max_pct"], 0.99))
    steps.append((
        "p99 of hourly max CPU",
        f"{valid_cpu_hours} valid hourly values, position 0.99 x {valid_cpu_hours - 1} "
        f"= {0.99 * (valid_cpu_hours - 1):.2f}",
        f"{p99:.2f}%",
    ))

    # Step 3: CPU actually needed at worst
    used = cur["vcpu"] * p99 / 100
    steps.append(("CPU actually needed at worst", f"{cur['vcpu']} vCPU x {p99 / 100:.2f}", f"{used:.2f} vCPU"))

    # Step 4: Add headroom
    needed = used / TARGET_UTIL
    steps.append(("Add 30% headroom", f"{used:.2f} / {TARGET_UTIL:.2f}", f"{needed:.2f} vCPU"))

    # Step 5: Half / quarter rule (shown for clarity)
    half, quarter = cur["vcpu"] / 2, cur["vcpu"] / 4
    steps.append((
        "Half of current size?",
        f"{needed:.2f} is {'at most' if needed <= half else 'above'} {half:g} (half of {cur['vcpu']})",
        "yes, at least one size down" if needed <= half else "no",
    ))
    steps.append((
        "Quarter of current size?",
        f"{needed:.2f} is {'at most' if needed <= quarter else 'above'} {quarter:g} (quarter of {cur['vcpu']})",
        "yes, two sizes down" if needed <= quarter else "no, not two sizes down",
    ))

    # Step 6: Smallest size that fits CPU, capped at MAX_STEPS_DOWN below current
    fit_i = next((i for i, s in enumerate(SIZES) if s["vcpu"] >= needed), len(SIZES))
    start_cand_i = max(fit_i, cur_i - MAX_STEPS_DOWN)

    if start_cand_i >= cur_i:
        steps.append(("Candidate", "no smaller size fits the CPU need", "keep current size"))
        return {
            "status": "none",
            "verdict": "RIGHT_SIZED",
            "p99_cpu_pct": round(p99, 2),
            "needed_vcpu": round(needed, 2),
            "steps": steps,
        }

    # Step 7: Burstable credit check (T-family only)
    if burstable:
        if "CPUCreditBalance" in df and df["CPUCreditBalance"].notna().any():
            min_credits = float(np.nanmin(df["CPUCreditBalance"]))
            if min_credits < 20:
                steps.append(("CPU credits", f"min credit balance {min_credits:.1f} (< 20)", "blocked: already starved"))
                return {"status": "none", "verdict": "BLOCKED_BY_CREDITS", "steps": steps}
        if "CPUSurplusCreditsCharged" in df and df["CPUSurplusCreditsCharged"].notna().any():
            surplus_charged = float(np.nansum(df["CPUSurplusCreditsCharged"]))
            if surplus_charged > 0:
                steps.append(("CPU surplus credits", f"{surplus_charged:.2f} surplus credits charged", "blocked: bursting past baseline"))
                return {"status": "none", "verdict": "BLOCKED_BY_SURPLUS_CREDITS", "steps": steps}

    # Track confidence modifiers
    confidence_notes = []
    if valid_cpu_hours < len(df):
        confidence_notes.append("metric gaps present")
    if idle_status == "NEEDS_REVIEW":
        confidence_notes.append("flagged Needs Review in idle check")
    if in_asg:
        confidence_notes.append("member of Auto Scaling Group (update Launch Template)")

    # Check if memory data is present and has sufficient non-NaN coverage (>= 50% of window)
    has_mem = (
        "mem_used_pct" in df
        and df["mem_used_pct"].notna().sum() >= int(MIN_DAYS * 24 * 0.50)
    )
    if has_mem:
        mem_p95 = float(np.nanquantile(df["mem_used_pct"], 0.95))
        mem_used = cur["mem_gib"] * mem_p95 / 100
        mem_need = mem_used / TARGET_UTIL
    else:
        mem_p95, mem_used, mem_need = None, None, 0.0
        confidence_notes.append("no memory data")

    # Peak network and disk throughput in Mbps (NaN-safe)
    net_mbps = float(np.nanmax(df["net_bytes"])) * 8 / 3600 / 1e6 if df["net_bytes"].notna().any() else 0.0
    ebs_mbps = float(np.nanmax(df["ebs_bytes"])) * 8 / 3600 / 1e6 if df["ebs_bytes"].notna().any() else 0.0

    confidence = "high" if not confidence_notes else f"medium ({', '.join(confidence_notes)})"

    # Step 8 & 9: Test candidates from smallest eligible (start_cand_i) up to 1 step below current (cur_i - 1).
    # This ensures if a 2-step downsize is blocked by memory/network/disk, a 1-step downsize is still tried.
    last_blocked = []
    for cand_i in range(start_cand_i, cur_i):
        cand = SIZES[cand_i]
        blocked = []

        if has_mem:
            ok_mem = mem_need <= cand["mem_gib"]
            if not ok_mem:
                blocked.append("memory")

        ok_net = net_mbps < cand["net_mbps"]
        ok_ebs = ebs_mbps < cand["ebs_mbps"]
        if not ok_net:
            blocked.append("network")
        if not ok_ebs:
            blocked.append("disk")

        if not blocked:
            steps.append((
                "Candidate",
                f"{cand['name']}: {cand['vcpu']} vCPU, {cand['mem_gib']} GiB",
                "fits the CPU need",
            ))
            if has_mem:
                steps.append((
                    "Memory check",
                    f"p95 memory {mem_p95:.0f}% of {cur['mem_gib']} GiB = {mem_used:.1f} GiB; "
                    f"with headroom {mem_used:.1f} / {TARGET_UTIL:.2f} = {mem_need:.1f} GiB",
                    f"{mem_need:.1f} is under {cand['mem_gib']} GiB, so it fits",
                ))
            steps.append((
                "Network and disk check",
                f"peak network {net_mbps:.0f} Mbps vs limit up to {cand['net_mbps']:,} Mbps; "
                f"peak EBS {ebs_mbps:.0f} Mbps vs limit up to {cand['ebs_mbps']:,} Mbps",
                "fits",
            ))

            # Step 10: Saving
            now, new = HOURS_PER_MONTH * cur["price"], HOURS_PER_MONTH * cand["price"]
            saving = round(now - new, 2)
            steps.append((
                "Saving",
                f"${cur['price']:.3f} to ${cand['price']:.3f} per hour; {HOURS_PER_MONTH} hours: "
                f"${now:,.2f} to ${new:,.2f}",
                f"about ${saving:,.2f} per month",
            ))

            return {
                "status": "found",
                "verdict": "OVER_PROVISIONED",
                "current": cur["name"],
                "recommended": cand["name"],
                "p99_cpu_pct": round(p99, 2),
                "needed_vcpu": round(needed, 2),
                "monthly_saving_usd": saving,
                "confidence": confidence,
                "steps": steps,
            }

        # Record why this candidate was blocked before trying the next larger candidate
        steps.append((
            f"Candidate rejected ({cand['name']})",
            f"Blocked by {', '.join(blocked)} "
            f"(mem need {mem_need:.1f}/{cand['mem_gib']} GiB, net {net_mbps:.0f}/{cand['net_mbps']} Mbps, "
            f"EBS {ebs_mbps:.0f}/{cand['ebs_mbps']} Mbps)",
            "trying next larger size" if cand_i + 1 < cur_i else "no smaller size fits",
        ))
        last_blocked = blocked

    return {
        "status": "none",
        "verdict": "BLOCKED_BY_" + "_AND_".join(b.upper() for b in last_blocked),
        "p99_cpu_pct": round(p99, 2),
        "needed_vcpu": round(needed, 2),
        "steps": steps,
    }


# ----------------------------------------------------------------- run it
if __name__ == "__main__":
    data = make_dummy_data()
    result = check_overprovisioned(data, "m5.2xlarge")

    print("Worked example: m5.2xlarge (8 vCPU, 32 GiB)\n")
    for i, (what, calc, res) in enumerate(result["steps"], 1):
        print(f"{i:>2}. {what}\n      calculation: {calc}\n      result:      {res}")

    print("\nSTATUS:", result["status"])
    print("VERDICT:", result["verdict"])
    for k in ("current", "recommended", "p99_cpu_pct", "needed_vcpu", "monthly_saving_usd", "confidence"):
        if k in result:
            print(f"  {k}: {result[k]}")
