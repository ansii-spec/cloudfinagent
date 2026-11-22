"""Turns a finished pipeline result into a concrete, priced 'suggestion' (specs/04 §5).

New code: it never changes any pipeline score, status or confidence."""
HOURS_PER_MONTH = 730
CREDIT_REASON_PREFIX = "CPU credits below"


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def upsize_target(ladder: list[dict], instance_type: str) -> dict | None:
    cur = next((x for x in ladder if x["name"] == instance_type), None)
    if cur is None:
        return None
    if cur["burstable"]:
        bigger = [x for x in ladder if x["mem_gib"] > cur["mem_gib"]]
        return min(bigger, key=lambda x: (x["mem_gib"], x["vcpu"])) if bigger else None
    return next((x for x in ladder if x["vcpu"] == 2 * cur["vcpu"] and x["mem_gib"] >= cur["mem_gib"]), None)


def build(result: dict, ladder: list[dict] | None, price_fn, region: str) -> dict:
    status = result.get("status")
    cur_type = result.get("instance_type")
    p_now = price_fn(cur_type) if cur_type and status not in ("ERROR",) else None
    s = {"action": "NONE", "alternative_actions": [], "from_type": cur_type, "to_type": None,
         "current_hourly_usd": _r(p_now, 4), "target_hourly_usd": None, "monthly_delta_usd": None,
         "monthly_saving_usd": None, "risk": None, "downtime_estimate": None, "headline": "", "rationale": ""}
    band = (result.get("confidence") or {}).get("band")

    if status == "IDLE":
        saving = p_now * HOURS_PER_MONTH if p_now else None
        idle = result.get("idle") or {}
        s.update(action="STOP_INSTANCE", alternative_actions=["TERMINATE_INSTANCE"], risk="LOW",
                 downtime_estimate="instance stays stopped until you start it again",
                 monthly_delta_usd=_r(-saving) if saving else None, monthly_saving_usd=_r(saving),
                 headline="Stop this idle instance",
                 rationale=("It has done almost no work in the analysed window "
                            f"(idle score {idle.get('score')}%). Stopping it is reversible; "
                            "attached EBS volumes are still billed while stopped."))
    elif status == "OVER_PROVISIONED":
        over = result.get("overprovisioned") or {}
        target = over.get("recommended")
        p_new = price_fn(target) if target else None
        saving = over.get("monthly_saving_usd")
        if saving is None and p_now and p_new:
            saving = (p_now - p_new) * HOURS_PER_MONTH
        mem_ok = over.get("memory_checked", False)
        risk = "HIGH" if (not mem_ok or band == "LOW") else "MEDIUM"
        s.update(action="RESIZE", to_type=target, target_hourly_usd=_r(p_new, 4), risk=risk,
                 downtime_estimate="~2-5 min", monthly_saving_usd=_r(saving),
                 monthly_delta_usd=_r(-saving) if saving is not None else None,
                 headline=f"Downsize {cur_type} → {target}",
                 rationale=(f"Peak CPU needs about {over.get('needed_vcpu')} of {over.get('current_vcpu')} vCPUs "
                            "(p99 of hourly max + 30% headroom); "
                            + ("memory p95 fits the smaller size." if mem_ok
                               else "memory is not monitored, so the memory fit was not checked.")))
    elif status == "UNDER_PROVISIONED":
        under = result.get("underprovisioned") or {}
        credit_starved = (under.get("reason") or "").startswith(CREDIT_REASON_PREFIX)
        target = upsize_target(ladder or [], cur_type) if cur_type else None
        p_new = price_fn(target["name"]) if target else None
        if credit_starved:
            s.update(action="ENABLE_UNLIMITED_CREDITS", risk="LOW", downtime_estimate="none",
                     monthly_delta_usd=None, monthly_saving_usd=0.0,
                     alternative_actions=["RESIZE"] if target else [],
                     to_type=target["name"] if target else None, target_hourly_usd=_r(p_new, 4),
                     headline="Enable unlimited CPU credits",
                     rationale=("The instance keeps running out of CPU credits and is throttled to its baseline. "
                                "Unlimited mode removes the throttle (surplus credits are billed)."))
        elif target:
            delta = (p_new - p_now) * HOURS_PER_MONTH if (p_now and p_new) else None
            s.update(action="RESIZE", to_type=target["name"], target_hourly_usd=_r(p_new, 4), risk="LOW",
                     downtime_estimate="~2-5 min", monthly_delta_usd=_r(delta), monthly_saving_usd=0.0,
                     headline=f"Upsize {cur_type} → {target['name']}",
                     rationale=f"CPU is saturated for sustained periods ({under.get('reason', '')}).")
        else:
            s.update(headline="Already the largest size in its family",
                     rationale="CPU is saturated but no larger size of this family exists; consider another family.")
    elif status == "NEEDS_REVIEW":
        guards = (result.get("idle") or {}).get("blocked_by") or []
        s.update(headline="Review manually",
                 rationale="Usage looks idle, but it was not declared idle because of: " + "; ".join(guards))
    elif status == "ACTIVE":
        s.update(headline="No change needed", rationale="Usage is within healthy limits.")
    elif status == "STOPPED":
        s.update(headline="Instance is stopped", rationale="No live metrics. Stopped instances still pay for EBS.")
    elif status == "INSUFFICIENT_DATA":
        s.update(headline="Not enough data yet", rationale=result.get("reason", ""))
    else:
        s.update(headline="Analysis failed", rationale=result.get("reason", ""))
    return s
