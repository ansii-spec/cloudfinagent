# 05 — Remediation Actions (apply from the app)

Implemented in `services/remediation_service.py`, executed by Celery task `execute_action`. All calls use the customer role session (doc 03) and require `connection.actions_enabled = true` and `actions_verified = true`.

## 1. Action catalogue

| Action code | Triggered by | AWS calls | Reversible? |
|---|---|---|---|
| `STOP_INSTANCE` | IDLE | `stop_instances` → wait `instance_stopped` | Yes – `start_instances` |
| `TERMINATE_INSTANCE` | IDLE (secondary, extra friction) | optional `create_snapshot`/`create_image` → `terminate_instances` | **No** (only via AMI/snapshot restore, which the app does not automate) |
| `RESIZE` (down or up) | OVER / UNDER | stop → `modify_instance_attribute(InstanceType)` → start | Yes – resize back to original type |
| `ENABLE_UNLIMITED_CREDITS` | UNDER (credit-starved T-family) | `modify_instance_credit_specification(CpuCredits="unlimited")` | Yes – set back to `standard` |

## 2. Common lifecycle

```
POST /findings/{id}/actions {action, options}
  1. authorise (finding belongs to user; connection actions_enabled)
  2. re-fetch live state of the instance (describe_instances) — finding may be stale
  3. PRE-CHECKS (below); any blocker → 422 with list of reasons, nothing executed
  4. DRY RUN: call the same AWS API with DryRun=True; expect DryRunOperation (= allowed)
  5. insert remediation_actions row status=pending (stores before-state snapshot)
  6. enqueue execute_action
  7. worker: status=running → perform steps, writing `steps_log` entries after each step
  8. success → status=succeeded, write savings_ledger start (doc 06), tag instance
     failure → attempt rollback → status=rolled_back (or failed if rollback also failed)
  9. mark finding.action_state accordingly; instance gets a 7-day "cool-down" before it is
     re-evaluated (prevents flapping: new size needs fresh metrics)
```

Always tag the instance after success: `ec2opt:last-action=<ACTION>`, `ec2opt:action-id=<uuid>`, `ec2opt:previous-type=<type>` (needs `ec2:CreateTags`; failure to tag is non-fatal).

One active action per instance at a time (DB unique partial index + Redis lock).

## 3. Pre-checks (blockers) per action

Common blockers:
- instance state not as expected (e.g. already stopped for STOP; not `running` for RESIZE).
- `DisableApiStop` / `DisableApiTermination` attribute true for STOP/TERMINATE respectively (`describe_instance_attribute`) → blocker "protection enabled; disable it in AWS first".
- Instance is part of an Auto Scaling group (`autoscaling:DescribeAutoScalingInstances` or tag `aws:autoscaling:groupName`) → blocker for STOP/TERMINATE/RESIZE: "managed by ASG X; change the launch template instead".
- Managed by EKS/ECS/Elastic Beanstalk (tags `eks:*`, `aws:eks:*`, `elasticbeanstalk:*`, `ecs` cluster tags) → blocker.
- Spot instance (`InstanceLifecycle == "spot"`) → blocker for STOP and RESIZE ("spot instances can't be resized").
- Instance changed since the scan (type differs from finding's `instance_type`) → blocker "state changed, re-scan".

RESIZE-specific:
- Root device must be EBS (`RootDeviceType == "ebs"`); instance-store root → blocker.
- Target type must exist in the region and in the same family & architecture (re-check with `describe_instance_types`).
- Warnings (not blockers, shown in the confirm modal): public IPv4 will change unless an Elastic IP is attached (`describe_addresses`); instance-store volumes (if any) lose data on stop; ~2-5 min downtime; EBS-optimised / ENA support differences.
- Hibernation-enabled instances → blocker.

TERMINATE-specific:
- Must pass all STOP blockers **and** the user must type the instance ID in the modal.
- Offer checkbox "Create a final snapshot of attached volumes first" (default ON) → `create_snapshot` per volume; wait not required, but record snapshot IDs.

## 4. Step logic

### STOP_INSTANCE
1. `stop_instances([id])`
2. waiter `instance_stopped` (delay 15 s, max 40 attempts)
3. record `before={state:"running"}`, `after={state:"stopped"}`.
Undo = `start_instances` + waiter `instance_running`.

### RESIZE
1. record before: type, state, public IP, EIP present, credit spec (if T-family).
2. (optional, user-selected) `create_image(NoReboot=True)` for a backup AMI; record AMI id.
3. `stop_instances` + waiter stopped.
4. `modify_instance_attribute(InstanceId, InstanceType={"Value": target})`.
   - On failure (e.g. `InvalidParameterCombination`, capacity) → **rollback**: start the instance with the original type, status `rolled_back`, message explains why.
5. `start_instances` + waiter `instance_running` + waiter `instance_status_ok`.
   - On `InsufficientInstanceCapacity` when starting the new type → rollback: set type back to original, start, status `rolled_back`.
6. record after: type, state, new public IP.
Undo = RESIZE back to `before.type` using the same procedure (action row `parent_action_id` set; type `UNDO_RESIZE`).

### ENABLE_UNLIMITED_CREDITS
`modify_instance_credit_specification(InstanceCreditSpecifications=[{InstanceId, CpuCredits:"unlimited"}])`. No downtime. Warn the user: unlimited mode can add surplus-credit charges. Undo sets `standard`.

### TERMINATE_INSTANCE
Snapshots (if chosen) → `terminate_instances` → waiter `instance_terminated`. No undo button. Savings = hourly price (+ EBS if deleted-on-termination, optional estimate).

## 5. Confirmation modal content (frontend ↔ backend contract)

`POST /findings/{id}/actions/preview {action}` returns (nothing executed):
```json
{
  "action": "RESIZE",
  "instance": {"id": "i-…", "name": "…", "region": "…"},
  "change": {"from": "m5.2xlarge", "to": "m5.large"},
  "cost": {"current_monthly": 280.32, "new_monthly": 70.08, "monthly_delta": -210.24},
  "downtime": "~2-5 minutes (instance is stopped and restarted)",
  "blockers": [],
  "warnings": ["Public IP will change (no Elastic IP attached)", "Memory was not monitored (lower confidence)"],
  "requires_typed_confirmation": false,
  "options": {"create_backup_ami": {"default": true}},
  "undo": "Resize back to m5.2xlarge from the Actions page"
}
```
UI: shows these fields, requires a checkbox "I understand" (and typed instance ID for terminate), then `POST /findings/{id}/actions {action, options}`.

## 6. Dismiss / snooze
`POST /findings/{id}/dismiss {until: "2026-12-31" | "forever", reason?}` hides it from the main list (still visible under filter "Dismissed") and excludes its potential saving from the dashboard.

## 7. Audit & safety
- Every attempt (even blocked / failed) is written to `audit_log` and `remediation_actions` (user, connection, instance, action, before, after, steps_log, error, timestamps).
- Rate-limit: max 10 actions per user per hour.
- Never run actions in `DEMO_MODE` against AWS; `demo_service` simulates steps with `sleep(1)` and mutates a fake in-DB instance state so Undo and savings behave realistically.

## 8. Tests
moto-based tests (moto supports EC2 `stop/start/modify_instance_attribute/terminate`):
- happy-path stop, resize down, resize up, undo resize;
- blockers (ASG tag, spot, protection flag, wrong state);
- modify failure → rollback path (patch client to raise);
- idempotency / concurrent action rejected.
