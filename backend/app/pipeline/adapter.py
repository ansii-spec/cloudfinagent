"""Wraps the detector for the scan job (specs/04 §3). Mirrors the old __main__ loop body exactly."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.pipeline import detector as d
from app.pipeline import recommend
from app.pipeline.serialization import to_jsonable

log = logging.getLogger("pipeline")


@dataclass
class PipelineConfig:
    lookback_hours: int = 336
    min_history_hours: int = 168
    max_workers: int = 5


def _base(meta: dict, region: str) -> dict:
    return {"instance_id": meta["instance_id"], "name": meta["name"], "instance_type": meta["instance_type"],
            "region": region, "state": meta["state"], "launch_time": meta.get("launch_time"),
            "tags": meta.get("tags", {}), "confidence": {"score": 0.0, "band": "NONE"}}


def analyze_instance(meta: dict, cw, ec2, price_fn, cfg: PipelineConfig, region: str | None = None,
                     ladder_fn=None) -> dict:
    """Runs the detector cascade for ONE instance and returns the final JSON-safe finding dict."""
    region = region or ec2.meta.region_name
    ladder_fn = ladder_fn or (lambda t: d.family_ladder(ec2, t))
    base = _base(meta, region)
    ladder = None
    if meta["state"] != "running":
        r = {**base, "status": "STOPPED",
             "reason": f"state={meta['state']}: no live metrics (stopped instances still pay for EBS)"}
        metrics = {}
    else:
        metrics = d.fetch_cloudwatch_metrics(cw, instance_id=meta["instance_id"], volume_ids=meta["volume_ids"],
                                             launch_time=meta["launch_time"], lookback_hours=cfg.lookback_hours)
        r = d.classify_and_score(meta, metrics, min_history_hours=cfg.min_history_hours)
        if r["status"] != "INSUFFICIENT_DATA":
            idle_wins = r["idle"]["score"] >= d.IDLE_THRESHOLD and not r["idle"]["blocked_by"]
            if not idle_wins:
                ladder = ladder_fn(meta["instance_type"])
            over = None if idle_wins else d.check_overprovisioned(meta, metrics, ladder, price_fn)
            r = d.run_cascade(r, over)
        r = {**base, **r}
    if r["status"] == "UNDER_PROVISIONED" and ladder is None:
        ladder = ladder_fn(meta["instance_type"])
    r["has_memory_metric"] = bool(metrics.get("has_memory_metric", False))
    r["hourly_series"] = metrics.get("hourly_series", [])
    r["mem_hourly"] = metrics.get("mem_hourly", [])
    r["suggestion"] = recommend.build(r, ladder, price_fn, region)
    return to_jsonable(r)


def error_finding(meta: dict, region: str, e: Exception) -> dict:
    return to_jsonable({**_base(meta, region), "status": "ERROR", "reason": d.explain_aws_error(e),
                        "suggestion": recommend.build({"status": "ERROR"}, None, lambda t: None, region)})


def analyze_region(session, platform_session, region: str, cfg: PipelineConfig, on_progress=None,
                   price_fn=None, on_discovered=None, price_fn_factory=None) -> list[dict]:
    """Discovers instances in one region and analyses them in parallel (max 5 workers).
    A failing instance never stops the scan: it becomes an ERROR finding."""
    ec2, cw, pricing = d.get_clients(session, region, platform_session)
    if price_fn is None:
        price_fn = price_fn_factory(pricing) if price_fn_factory else (lambda t: d.hourly_price(pricing, t, region))
    metas = d.fetch_instance_metadata(ec2)
    if on_discovered:
        on_discovered(len(metas))
    results = []

    def one(meta):
        try:
            return analyze_instance(meta, cw, ec2, price_fn, cfg, region=region)
        except Exception as e:  # noqa: BLE001 - one bad instance must not stop the scan
            log.error("%s (%s): %s", meta["instance_id"], meta["name"] or "no name", d.explain_aws_error(e))
            return error_finding(meta, region, e)

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futures = [pool.submit(one, m) for m in metas.values()]
        for f in as_completed(futures):
            results.append(f.result())
            if on_progress:
                on_progress(1)
    return results
