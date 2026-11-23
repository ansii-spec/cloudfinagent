import inspect

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.pipeline import detector as d

router = APIRouter(tags=["settings"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/config/public")
def public_config():
    s = get_settings()
    # limits are the detector's own defaults (single source of truth)
    lim = {k: v.default for k, v in inspect.signature(d.classify_and_score).parameters.items()
           if v.default is not inspect.Parameter.empty}
    return {
        "platform_account_id": s.platform_aws_account_id,
        "version": __version__,
        "thresholds": {
            "idle_threshold": d.IDLE_THRESHOLD, "over_threshold": d.OVER_THRESHOLD,
            "under_threshold": d.UNDER_THRESHOLD, "cpu_p95_limit_pct": lim["cpu_p95_limit"],
            "cpu_p99_max_limit_pct": lim["cpu_max_limit"], "net_p95_mb_per_hour": lim["net_p95_mb_per_hour"],
            "ebs_p95_mb_per_hour": lim["ebs_p95_mb_per_hour"], "under_cpu_p99_limit_pct": lim["under_cpu_p99_limit"],
            "credit_starved_below": lim["credit_starved_below"], "headroom_pct": 30, "idle_weights": {
                "cpu_p95": 0.35, "cpu_max": 0.20, "net_p95": 0.30, "ebs_p95": 0.15},
            "lookback_hours": s.lookback_hours, "min_history_hours": s.min_history_hours,
            "apply_data_quality": s.apply_data_quality,
            "protect_substrings": list(d.PROTECT_SUBSTRINGS), "protect_tokens": list(d.PROTECT_TOKENS),
        },
    }
