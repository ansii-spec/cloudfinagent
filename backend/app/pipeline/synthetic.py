"""Synthetic CloudWatch data: a fake `cw` client that answers get_metric_data from a workload profile.

Used to generate DEMO_MODE fixtures by running the REAL detector, and by the pipeline tests
(moto does not return realistic CloudWatch datapoints)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

MB = 1_000_000


@dataclass
class Profile:
    cpu_mean: float                 # % CPU average level
    cpu_amp: float = 0.3            # daily seasonality amplitude (fraction of mean)
    cpu_noise: float = 0.1          # noise (fraction of mean)
    cpu_max_factor: float = 1.5     # 5-min Maximum vs Average
    cpu_cap: float = 100.0          # e.g. T-family baseline when out of credits
    net_mb_h: float = 1.0           # network in+out MB per hour
    ebs_mb_h: float = 1.0           # EBS read+write MB per hour
    mem_pct: float | None = None    # None = no CloudWatch agent
    credits: str | None = None      # None | "healthy" | "starved"
    spikes: list[tuple[int, float]] = field(default_factory=list)  # (every_n_hours, cpu_max %)
    seed: int = 1


class FakeCloudWatch:
    """Implements the subset of boto3 cloudwatch used by detector.fetch_cloudwatch_metrics."""

    def __init__(self, profiles: dict[str, Profile]):
        self.profiles = profiles

    def _series(self, p: Profile, grid: pd.DatetimeIndex, period: int) -> dict[str, np.ndarray]:
        rng = np.random.default_rng(p.seed)
        hours = grid.hour.to_numpy() + grid.minute.to_numpy() / 60
        season = 1 + p.cpu_amp * np.sin(2 * np.pi * (hours - 8) / 24)
        cpu = p.cpu_mean * season * (1 + p.cpu_noise * rng.standard_normal(len(grid)))
        cpu = np.clip(cpu, 0.05, p.cpu_cap)
        cpu_max = np.clip(cpu * p.cpu_max_factor * (1 + 0.1 * rng.random(len(grid))), 0.1, 100.0)
        for every, peak in p.spikes:
            idx = np.arange(0, len(grid), max(1, int(every * 3600 / period)))
            cpu_max[idx] = np.maximum(cpu_max[idx], peak)
        per_sample = period / 3600
        net = p.net_mb_h * per_sample * MB * season * (1 + 0.15 * rng.standard_normal(len(grid)))
        net = np.clip(net, 0, None)
        ebs = np.clip(p.ebs_mb_h * per_sample * MB * (1 + 0.3 * rng.standard_normal(len(grid))), 0, None)
        out = {"cpu_avg": cpu, "cpu_max": cpu_max, "net_in": net * 0.6, "net_out": net * 0.4,
               "ec2_ebs_read": ebs * 0.3, "ec2_ebs_write": ebs * 0.7}
        if p.mem_pct is not None:
            out["mem_used"] = np.clip(p.mem_pct * (1 + 0.08 * rng.standard_normal(len(grid))), 1, 99)
        if p.credits == "healthy":
            out["credit_bal"] = 400 + 50 * rng.random(len(grid))
        elif p.credits == "starved":
            # drains to ~0 every afternoon and stays there for hours
            out["credit_bal"] = np.clip(60 * np.cos(2 * np.pi * (hours - 3) / 24) - 10, 0, None)
        return out

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **_):
        iid = MetricDataQueries[0]["MetricStat"]["Metric"]["Dimensions"][0]["Value"]
        period = MetricDataQueries[0]["MetricStat"]["Period"]
        p = self.profiles.get(iid)
        grid = pd.date_range(pd.Timestamp(StartTime), pd.Timestamp(EndTime), freq=f"{period}s")
        data = self._series(p, grid, period) if p else {}
        results = []
        for q in MetricDataQueries:
            vals = data.get(q["Id"])
            if vals is None:
                results.append({"Id": q["Id"], "Timestamps": [], "Values": []})
            else:
                results.append({"Id": q["Id"], "Timestamps": [t.to_pydatetime() for t in grid],
                                "Values": [float(v) for v in vals]})
        return {"MetricDataResults": results}


def make_meta(instance_id: str, name: str, instance_type: str, tags: dict | None = None, state: str = "running",
              age_hours: float = 24 * 60) -> dict:
    launch = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    tags = {"Name": name, **(tags or {})}
    return {"instance_id": instance_id, "name": name, "tags": tags, "state": state, "instance_type": instance_type,
            "launch_time": launch, "age_hours": age_hours, "age_days": age_hours / 24, "volume_ids": []}
