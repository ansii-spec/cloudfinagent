# 01 — Product Requirements

## 1. Purpose
Help AWS users cut EC2 waste. The app detects three kinds of problems and fixes them on request:

| Label | Meaning | Typical fix |
|---|---|---|
| `IDLE` | Instance does almost no useful work (low CPU, network, disk) | Stop (default) or terminate |
| `OVER_PROVISIONED` | Instance is running but far larger than needed | Resize to a smaller type in the same family |
| `UNDER_PROVISIONED` | CPU sustained near the ceiling, or T-family credits starved | Resize to the next larger type (or enable unlimited credits for T-family) |

Other statuses the pipeline can return and the UI must handle: `NEEDS_REVIEW`, `ACTIVE`, `STOPPED`, `INSUFFICIENT_DATA`, `ERROR`.

## 2. Personas
- **Cloud owner / DevOps engineer** – wants savings without risking production.
- **Student/demo user** – evaluator of the FYP; needs a working demo even without real AWS (DEMO_MODE).

## 3. User stories & acceptance criteria

### Auth
- US-1: As a user I can register with name, email, password; log in; log out.
  - AC: passwords hashed (argon2); invalid credentials give a generic error; session via httpOnly cookie.

### Connect AWS (see doc 03)
- US-2: As a user I can connect my AWS account securely without sharing keys.
  - AC: wizard shows platform account ID + my unique External ID + a "Launch CloudFormation stack" button + manual fallback; I paste the Role ARN; app verifies with a real `AssumeRole`; status becomes **Connected** with the AWS account ID displayed.
  - AC: I can choose **Read-only** (analysis) or **Read + Actions** (enables one-click fixes). I can upgrade later.
  - AC: I can disconnect; this deletes the connection row and all derived data for it.
  - AC: if AWS later returns AccessDenied on AssumeRole (stack deleted), connection becomes **Broken** with a clear message.

### Scan
- US-3: As a user I can run a scan on demand and also get a daily automatic scan.
  - AC: I choose regions (default: all enabled regions that contain instances); scan runs in the background; UI shows progress (instances analysed / total) and results when done.
  - AC: a failure on one instance never stops the scan; that instance shows `ERROR` with a readable reason.

### Findings
- US-4: As a user I see a list of recommendations sorted by severity then confidence.
  - AC: columns – Name, Instance ID, Region, Current type, Status badge, Confidence (% + band), Suggested action, Est. monthly saving (or cost increase), Reason.
  - AC: filter by status, region, confidence band, text search; summary cards (counts per status + total potential savings).
- US-5: I can open an instance and see *why* the pipeline decided that.
  - AC: drawer shows score breakdown (idle / over / under scores), key metrics (CPU p95/p99, network, EBS, memory-checked yes/no), the pipeline **evidence steps table** (step / calculation / result), hourly charts (CPU avg & max, network, EBS, memory if available), data quality, protective tags that blocked IDLE.

### Apply fixes (see doc 05)
- US-6: I click the suggested action; a confirmation modal explains impact (downtime, IP change, cost change); I confirm; the action runs in the background and I see live status.
  - AC: `NEEDS_REVIEW` and `INSUFFICIENT_DATA` have no Apply button.
  - AC: Apply disabled with tooltip when connection is read-only (with an "Enable actions" CTA).
  - AC: every action is logged (who, when, before/after, result) and can be undone where technically possible.
- US-7: I can dismiss/snooze a recommendation ("keep as is" for 30 days or forever).

### Savings dashboard (see doc 06)
- US-8: I see how much money the app has saved me and how much more I could save.
  - AC: widgets – realized monthly run-rate, cumulative realized savings, potential savings, savings over time chart, breakdown by action type, top saved instances table, before/after table.

### Settings
- US-9: manage connections, regions, scan schedule (daily/weekly/off), email notification toggle (stretch), delete account.

## 4. Scope

### MVP (must)
Everything above except stretch items.

### Stretch (only after MVP is done and tested)
- Email / Slack notification of new findings.
- Schedule an action for a maintenance window.
- CSV / PDF export of findings and savings report.
- Google sign-in.
- Savings Plan / Reserved Instance awareness (currently ignored).
- Multiple AWS accounts per user (design the schema for it; UI may show one at first).

## 5. Non-goals
- Non-EC2 resources (RDS, EBS orphan volumes, ELB) — out of scope.
- Windows / BYOL pricing (Linux on-demand only; show a footnote).
- Changing detection thresholds from the UI (thresholds are config constants; expose read-only in Settings → "How detection works").
- Auto-applying fixes without user click.

## 6. Non-functional requirements
- A scan of 50 instances over a 14-day lookback finishes in < 5 minutes (parallelise per instance, max 5 workers, respect CloudWatch throttling).
- UI first load < 3 s on broadband; all lists paginated.
- Every AWS-facing error is translated to human-readable text (reuse `explain_aws_error`, extended per doc 04).
- Accessibility: keyboard navigable, colour is never the only status signal (use icon + text).
