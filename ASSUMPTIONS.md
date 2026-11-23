# Assumptions & decisions

1. **Layout:** repo root = `ec2-optimizer/`. Spec docs live in `specs/` (the existing `docs/` folder is git-ignored team material). The older JS prototype in `web/` is left untouched; the real app is `frontend/` (TypeScript).
2. **Frontend versions:** React 19 / react-router 8 / Tailwind 4 (the versions already used in this repo) instead of React 18; Tailwind 4 needs no `tailwind.config.ts`. A plain semantic table replaces TanStack Table.
3. **No demo mode (2026-11-23):** demo mode, its fixtures, fake executor and `demo_instances` table were removed (migration `0002`). Users must connect a real AWS account; prices come only from the AWS Pricing API (no hard-coded list - unknown price = no estimate). Test-only fixed data lives in `backend/tests/support/`.
4. **Per-connection IAM names:** each connection uses its own stack `EC2OptimizerAccess-<id8>` and role `EC2OptimizerAccessRole-<id8>`, so a role left over from a deleted connection never blocks a reconnect. The app has read-only access and cannot delete the stack itself; disconnect returns a cleanup link instead.
7. **Savings ledger "start row":** no row is written at apply time; accrual starts at `completed_at` and the daily job (idempotent, re-computes partial days) writes the rows. The dashboard totals equal Σ ledger rows (today's partial day is accrued tomorrow).
8. **Rate limit** counts all non-blocked action requests (incl. undo) per user per rolling hour.
9. **Blocked attempts** are stored as `remediation_actions` rows with status `failed` and an error starting with "Blocked:", plus an `ACTION_BLOCKED` audit event.
10. **CSRF:** header check `X-Requested-With: ec2opt` on all non-GET `/api/` requests.
11. **Redis fallback:** if Redis is unreachable the cache (credentials, rate limits) falls back to process memory - fine for tests and single-process dev, not for production.
12. **Downtime text** for STOP is descriptive ("stays stopped until you start it") rather than "none".
14. **Design:** the frontend keeps the original `web/` look - CloudFinAgent branding, enterprise-console palette (navy top bar, #0972d3 blue, grey surfaces, white sidebar with left-border active item, 6px cards with bordered headers, centred auth card). Status badges keep an icon + label so colour is never the only signal.
