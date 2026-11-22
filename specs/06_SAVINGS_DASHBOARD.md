# 06 — Savings Calculation & Dashboard

Goal: show honestly how much money the app has saved the user, and how much more they could save.

## 1. Definitions

| Term | Definition |
|---|---|
| **Potential savings** | Sum of `monthly_saving_usd` of all *open* findings (not dismissed, no action applied), per month. Upsize recommendations are shown separately as "recommended investments" (cost increase), never netted into potential savings. |
| **Realized monthly run-rate** | Sum over *active* applied actions of the monthly saving they currently deliver. |
| **Cumulative realized savings** | Money not spent so far because of applied actions = Σ ledger rows. |
| **Waste identified** | Potential + realized (the total problem size the app found). |

All figures are **estimates** based on Linux on-demand list price in the instance's region (730 h/month). The UI footnote must say so and that Reserved Instances, Savings Plans, Spot, data transfer and EBS are not modelled.

## 2. Per-action saving formulas

Let `p_old`, `p_new` = hourly on-demand USD price (from `pricing_service`, cached).

| Action | Hourly saving while action is in effect | Notes |
|---|---|---|
| `STOP_INSTANCE` | `p_old` | EBS still billed; accrues until the instance is started again (undo or external start) |
| `TERMINATE_INSTANCE` | `p_old` (+ optional EBS estimate if volumes deleted on termination; keep EBS out for MVP) | permanent |
| `RESIZE` down | `p_old − p_new` | accrues while instance runs the new type |
| `RESIZE` up | `p_old − p_new` (negative) | recorded as "investment", shown separately, **not** subtracted from headline savings; listed in a small "Invested in performance: $X/mo" card |
| `ENABLE_UNLIMITED_CREDITS` | 0 | no saving |

`monthly_run_rate = hourly_saving × 730`.

## 3. Savings ledger (`savings_ledger`)

One row per action per day:
`(id, connection_id, action_id, instance_id, region, date, hours_in_effect, hourly_saving_usd, amount_usd, kind)`
where `amount_usd = hours_in_effect × hourly_saving_usd` and `kind ∈ {STOP, TERMINATE, RESIZE_DOWN, RESIZE_UP}`.

### Daily accrual task (`accrue_savings`, beat 00:10 UTC)
For each `remediation_actions` row with `status=succeeded` and `savings_active=true`:
- window start = max(action.completed_at, last accrued timestamp); window end = start of today (UTC).
- insert a row for the elapsed hours (≤ 24 per day; catch up missed days).
- On the action's completion day, accrue partial-day hours from `completed_at`.

### Reconcile task (`reconcile`, beat 02:00 UTC)
For each active action, describe the instance:
- STOP: if instance state is `running` → set `savings_active=false`, `ended_at=now`, reason "restarted outside the app".
- RESIZE: if current type ≠ action target → `savings_active=false`.
- instance gone → TERMINATE-like: keep accruing only if the action was terminate; otherwise stop with reason "instance no longer exists".
Undo through the app sets `savings_active=false` immediately and stores `ended_at`.

DEMO_MODE: reconcile is a no-op; seed the ledger with ~60 days of plausible history (see doc 09).

## 4. API (see doc 07 for shapes)

`GET /dashboard/summary?connection_id=…&range=30d|90d|12m|all`
```json
{
  "currency": "USD",
  "realized": {"monthly_run_rate": 412.55, "cumulative": 1380.12, "this_month": 402.10},
  "potential": {"monthly": 936.40, "open_findings": 14},
  "invested": {"monthly": 58.40},
  "counts": {"idle": 3, "over_provisioned": 7, "under_provisioned": 2, "needs_review": 2, "active": 21},
  "actions": {"applied": 9, "undone": 1, "failed": 1},
  "timeseries": [{"date": "2026-10-01", "daily": 13.2, "cumulative": 13.2}],
  "by_action": [{"kind": "RESIZE_DOWN", "amount": 910.2}, {"kind": "STOP", "amount": 469.9}],
  "top_instances": [{"instance_id": "i-…", "name": "…", "kind": "RESIZE_DOWN", "from": "m5.2xlarge", "to": "m5.large",
                     "monthly_run_rate": 210.24, "cumulative": 700.8, "since": "2026-10-04"}],
  "last_scan_at": "2026-11-21T08:00:00Z"
}
```

## 5. Dashboard widgets (frontend, page `/dashboard`)

1. **Hero row (4 cards):** *Saved so far* (cumulative, big number, count-up animation) · *Monthly run-rate* · *Potential savings* (with "Review N recommendations" button → `/recommendations`) · *Invested in performance* (small, neutral).
2. **Savings over time:** area chart (cumulative) + bars (daily) toggled; range selector 30d / 90d / 12m / all.
3. **Savings by action type:** donut (Resize / Stop / Terminate).
4. **Top saved instances:** table (instance, change `m5.2xlarge → m5.large`, since, run-rate, cumulative).
5. **Findings health:** stacked bar or tiles with counts per status, click = filter the recommendations page.
6. **Before / After cost strip:** "Your EC2 spend estimate: before $X/mo → now $Y/mo (−Z %)". Computed as `current_estimate = Σ hourly price of running instances × 730` and `before = current + realized run-rate − invested`.
7. **Footnote:** assumptions text (estimates, Linux on-demand, etc.) with an info tooltip.
8. Empty states: no connection → CTA "Connect AWS"; no actions yet → "Apply your first recommendation to start saving" with the potential number prominent.

## 6. Spend estimate helper
`GET /dashboard/spend-estimate` returns current estimated EC2 compute spend from the latest scan (each running instance × price × 730). This is a list-price estimate, **not** a bill; do not call Cost Explorer (no extra permissions in MVP).

## 7. Tests
- ledger arithmetic for partial days, catch-up after downtime, undo mid-day;
- reconcile stops accrual when instance restarted / resized externally;
- upsize never reduces headline savings;
- summary endpoint totals equal Σ ledger rows.
