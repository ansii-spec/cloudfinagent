# 04 — Detection Pipeline Integration

Source of truth: `backend/pipeline_source/detector_original.py` (keep untouched). Create the working copy at `backend/app/pipeline/detector.py`.

> **Golden rule:** scoring logic, thresholds, weights, formulas stay byte-for-byte equivalent. Add a regression test that runs both the original and the refactored functions on the same synthetic metrics and asserts identical scores/statuses.

## 1. What the pipeline does (as implemented)

| Function | Role |
|---|---|
| `fetch_instance_metadata(ec2)` | lists pending/running/stopping/stopped instances (paginated): id, name, tags, state, type, launch_time, volume_ids |
| `fetch_cloudwatch_metrics(cw, instance_id, volume_ids, launch_time, lookback_hours)` | `GetMetricData` for CPU avg/max, NetworkIn/Out, EBS read/write (+ AWS/EBS fallback), `CWAgent mem_used_percent`, `CPUCreditBalance`; builds a regular grid, interpolates gaps ≤ 3 h, returns 5-min CPU arrays and hourly network/EBS arrays |
| `classify_and_score(meta, metrics, min_history_hours)` | computes IDLE score (log-margin, weights 0.35/0.20/0.30/0.15, guards: sensitive tags, steady network, heavy disk) and UNDER-PROVISIONED score (CPU p99 depth × sustained share; T-family credit starvation) + data quality |
| `family_ladder(ec2, type)` | all sizes of the same family + architecture, smallest first |
| `hourly_price(pricing, type, region)` | Linux on-demand USD/hour |
| `check_overprovisioned(meta, metrics, ladder, price_fn)` | p99 hourly max CPU → vCPU needed with 30 % headroom → 1 or 2 sizes down; memory/network/EBS/credit checks; monthly saving; confidence |
| `run_cascade(r, over)` | final label: IDLE → OVER_PROVISIONED → UNDER_PROVISIONED → NEEDS_REVIEW → ACTIVE |

Thresholds (keep as module constants, surface read-only in the UI "How detection works" page):
`IDLE_THRESHOLD=65`, `OVER_THRESHOLD=60`, `UNDER_THRESHOLD=70`, CPU p95 limit 5 %, CPU p99-max limit 10 %, net p95 20 MB/h, EBS p95 60 MB/h, under-provisioned CPU p99 limit 80 %, credit starved < 5.

## 2. Required refactors (the ONLY allowed changes to the code)

1. **Remove all CLI / env-var code.** Delete the whole `if __name__ == "__main__":` block, `print_table`, `sys.exit`, and `log_error` printing to stderr → replace with `logging.getLogger("detector")`.
2. **Replace access-key clients with session-based clients.**
   ```python
   def get_clients(session: boto3.Session, region: str, platform_session: boto3.Session):
       cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"}, connect_timeout=5, read_timeout=30)
       return (session.client("ec2", region_name=region, config=cfg),
               session.client("cloudwatch", region_name=region, config=cfg),
               platform_session.client("pricing", region_name="us-east-1", config=cfg))
   ```
   `session` = temporary credentials from AssumeRole; `platform_session` = our own credentials (pricing).
3. **Fix cache keys for multi-tenant / multi-region use.**
   - `_ladder_cache` key → `(region, family)` (available sizes differ by region). `family_ladder(ec2_client, instance_type)` must read the region from `ec2_client.meta.region_name`.
   - `_price_cache` already keyed by `(type, region)`; additionally persist prices in the `price_cache` DB table with a 7-day TTL (`pricing_service.py`) so scans don't hammer the Pricing API.
4. **Move `import json` to the top** of the file (currently imported inside `hourly_price`).
5. **Configurable runtime constants** read from `config.py` (defaults in brackets): `lookback_hours` [336], `min_history_hours` [168], `APPLY_DATA_QUALITY` [True in production]. Do not change any formula.
6. **Expose an hourly time series for charts.** In `fetch_cloudwatch_metrics`, in addition to current outputs, return:
   ```python
   "hourly_series": [
     {"ts": "2026-11-20T14:00:00Z", "cpu_avg": 3.2, "cpu_max": 11.0, "net_mb": 4.1, "ebs_mb": 12.3},
     ...
   ],
   "mem_hourly": [{"ts": "...", "mem_pct": 41.2}, ...]   # empty if no CWAgent data
   ```
   built from the existing `hourly` DataFrame index (and an hourly resample of `mem_used`). The existing arrays remain untouched (the existing `dropna` calls make them misaligned with timestamps, so charts must use the new series).
7. **Make results JSON-safe** via `serialization.to_jsonable()`:
   - `numpy` scalars/arrays → Python float/int/list, `NaN/inf` → `null`
   - `datetime` → ISO-8601 UTC string
   - `steps` tuples `(step, calculation, result)` → objects `{"step":…, "calculation":…, "result":…}`
   - never persist the raw numpy metric arrays in the DB (only aggregates + `hourly_series`).
8. **Extend `explain_aws_error`** for role-based access: `AccessDenied` (on AssumeRole → trust/external-ID problem; on API call → missing permission), `ExpiredToken`, `Throttling`, `RequestLimitExceeded`. Remove the "set AWS_ACCESS_KEY_ID" wording.
9. **Stopped / pending instances:** keep behaviour (`STOPPED` row). Include in the output `state` and `launch_time`.

## 3. Adapter API (`app/pipeline/adapter.py`)

```python
def analyze_instance(meta, cw, ec2, price_fn, cfg) -> dict: ...
    # mirrors the old __main__ loop body for ONE instance, returns the final JSON-safe finding dict

def analyze_region(session, platform_session, region, cfg, on_progress=None) -> list[dict]: ...
    # discovers instances, runs analyze_instance in a ThreadPoolExecutor(max_workers=5),
    # catches per-instance exceptions → {"status": "ERROR", "reason": explain_aws_error(e)}
```
Per-instance logic (exactly the old loop):
```
if state != running → status STOPPED
metrics = fetch_cloudwatch_metrics(cw, iid, volume_ids, launch_time, lookback_hours)
r = classify_and_score(meta, metrics, min_history_hours)
if r.status != INSUFFICIENT_DATA:
    idle_wins = r.idle.score >= IDLE_THRESHOLD and not r.idle.blocked_by
    over = None if idle_wins else check_overprovisioned(meta, metrics, family_ladder(...), price_fn)
    r = run_cascade(r, over)
```

## 4. Raw pipeline result → what the pipeline gives us

Top-level keys of a finished result (`{**base, **r}`): `instance_id, name, instance_type, status, confidence{score,band}, reason, hours_analyzed, idle{score,band,blocked_by,reason}, underprovisioned{score,band,reason}, overprovisioned{status,verdict,steps,recommended,current,monthly_saving_usd,memory_checked,confidence,p99_cpu_max,needed_vcpu,current_vcpu,reason} | null, data_quality, metrics{…}`.

`overprovisioned.status` is `"found"` or `"none"`; `verdict` values: `OVER_PROVISIONED`, `RIGHT_SIZED`, `NO_SMALLER_SIZE`, `BLOCKED`, `BLOCKED_BY_CREDITS`, `UNKNOWN_TYPE`.

Final `status` values: `IDLE, OVER_PROVISIONED, UNDER_PROVISIONED, NEEDS_REVIEW, ACTIVE, STOPPED, INSUFFICIENT_DATA, ERROR`.

## 5. The gap we must fill: the "suggested action" (`app/pipeline/recommend.py`)

The detector says *what is wrong* but only produces a target size for OVER_PROVISIONED, and no action/price for IDLE or UNDER_PROVISIONED. `recommend.build(result, ladder, price_fn, region)` adds a `suggestion` object. **This is new code; it must not alter any pipeline score.**

```jsonc
"suggestion": {
  "action": "STOP_INSTANCE | TERMINATE_INSTANCE | RESIZE | ENABLE_UNLIMITED_CREDITS | NONE",
  "alternative_actions": ["TERMINATE_INSTANCE"],
  "from_type": "t3.large",
  "to_type": "t3.medium",                 // RESIZE only
  "current_hourly_usd": 0.0832,
  "target_hourly_usd": 0.0416,            // RESIZE only
  "monthly_delta_usd": -30.37,            // NEGATIVE = saving, POSITIVE = extra cost (upsize)
  "monthly_saving_usd": 30.37,            // max(0, -delta)
  "risk": "LOW | MEDIUM | HIGH",
  "downtime_estimate": "none | ~2-5 min",
  "headline": "Stop this idle instance",
  "rationale": "…one human sentence built from the pipeline reason…"
}
```

Rules:
| Status | `action` | Target / savings |
|---|---|---|
| `IDLE` | `STOP_INSTANCE` (alternative `TERMINATE_INSTANCE`) | saving = `current_hourly × 730` (compute only; note: EBS is still billed while stopped) |
| `OVER_PROVISIONED` | `RESIZE` | `to_type = overprovisioned.recommended`; saving from detector `monthly_saving_usd` (recompute with same price_fn if null) |
| `UNDER_PROVISIONED` | `RESIZE` upwards, **or** `ENABLE_UNLIMITED_CREDITS` when `underprovisioned.reason` is the credit-starvation reason (instance is burstable) | `to_type` = next entry in `family_ladder` (same arch): for non-burstable the first size with `vcpu == 2 × current vcpu` and `mem_gib >= current`; for burstable the next size by `mem_gib`. `monthly_delta_usd` is positive (cost increase). If no larger size exists → `action = NONE` with an explanatory headline. |
| `NEEDS_REVIEW` | `NONE` | headline "Review manually" + the guard reasons (`idle.blocked_by`) |
| `ACTIVE`, `STOPPED`, `INSUFFICIENT_DATA`, `ERROR` | `NONE` | – |

Risk heuristic: `IDLE` stop = LOW (reversible) ; terminate = HIGH; downsize = MEDIUM (HIGH when `memory_checked=false` or confidence band LOW); upsize = LOW.

## 5b. Normalised `findings` row mapping
Store (see doc 07): `status`, `confidence_score`, `confidence_band`, `reason`, `suggestion` JSON, `metrics` JSON, `evidence_steps` JSON (= `overprovisioned.steps` when present), `idle`/`underprovisioned` JSON, `hourly_series` JSON, `data_quality`, `memory_checked`, `has_memory_metric`, `hours_analyzed`, plus denormalised `instance_id, region, name, instance_type, state, tags` and `monthly_saving_usd` for sorting/aggregation.

## 6. Memory data (important UX)
Without the CloudWatch Agent no memory metric exists; the detector then halves the evidence and flags `memory_checked=false`. The UI must:
- show a yellow "Memory not monitored – lower confidence" chip,
- link to a help page "How to install the CloudWatch agent" (static content: install `amazon-cloudwatch-agent`, config with `mem_used_percent`, IAM role `CloudWatchAgentServerPolicy` on the instance).

## 7. Test requirements for the pipeline layer
- Unit tests with synthetic arrays for: clearly idle, clearly over-provisioned (p99 max CPU 12 % on 4 vCPU), clearly under-provisioned (p99 CPU 95 % sustained), T-family credit-starved, sensitive-tag instance (must be NEEDS_REVIEW not IDLE), insufficient data.
- moto test for `fetch_instance_metadata` and a full `analyze_region` run with `DEMO`-style stubbed CloudWatch data (moto does not return CPU data realistically → inject a fake `cw` client).
- Regression test: refactored detector == original detector on the same inputs.
- `to_jsonable` round-trip test (no numpy types after `json.dumps`).

## 8. Sample finished finding (use as fixture `tests/fixtures/sample_findings.json` and in DEMO_MODE)

```json
{
  "instance_id": "i-0abc123def4567890",
  "name": "reporting-worker",
  "region": "ap-south-1",
  "instance_type": "m5.2xlarge",
  "state": "running",
  "status": "OVER_PROVISIONED",
  "confidence": {"score": 83.5, "band": "HIGH"},
  "reason": "p99 max CPU 9.8% -> needs 1.12 of 8 vCPU: m5.2xlarge -> m5.large, saves $229.95/month",
  "hours_analyzed": 336,
  "data_quality": 0.95,
  "idle": {"score": 41.2, "band": "LOW", "blocked_by": [], "reason": "idle score 41.2% …"},
  "underprovisioned": {"score": 8.0, "band": "LOW", "reason": "CPU p99 6.4% vs 80.0% …"},
  "overprovisioned": {
    "status": "found", "verdict": "OVER_PROVISIONED", "recommended": "m5.large", "current": "m5.2xlarge",
    "monthly_saving_usd": 229.95, "memory_checked": true, "p99_cpu_max": 9.8, "needed_vcpu": 1.12, "current_vcpu": 8,
    "steps": [
      {"step": "p99 of hourly max CPU", "calculation": "336 hourly values", "result": "9.80%"},
      {"step": "CPU used at worst", "calculation": "8 vCPU x 0.0980", "result": "0.78 vCPU"},
      {"step": "Add 30% headroom", "calculation": "0.78 / 0.7", "result": "1.12 vCPU needed"},
      {"step": "Quarter of current?", "calculation": "1.12 vs 2", "result": "yes"},
      {"step": "Candidate", "calculation": "m5.large: 2 vCPU, 8 GiB", "result": "fits the CPU need"},
      {"step": "Saving", "calculation": "730 h x ($0.384 - $0.096)", "result": "$210.24/month"}
    ]
  },
  "metrics": {"cpu_p95_pct": 6.1, "cpu_p99_pct": 7.9, "cpu_p99_max_pct": 9.8, "net_p95_mb_per_hour": 310.0, "ebs_p95_mb_per_hour": 95.0, "network_cv": 0.9},
  "suggestion": {
    "action": "RESIZE", "alternative_actions": [], "from_type": "m5.2xlarge", "to_type": "m5.large",
    "current_hourly_usd": 0.384, "target_hourly_usd": 0.096, "monthly_delta_usd": -210.24, "monthly_saving_usd": 210.24,
    "risk": "MEDIUM", "downtime_estimate": "~2-5 min",
    "headline": "Downsize m5.2xlarge → m5.large",
    "rationale": "Peak CPU never needs more than ~1.1 of 8 vCPUs; memory p95 fits the smaller size."
  }
}
```
(The numbers in this sample are illustrative; make them internally consistent when generating fixtures.)
