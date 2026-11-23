# CLAUDE.md — EC2 Optimizer (FYP) — MASTER BRIEF

> Claude Code: read this file first, then read every file in `/specs` **in numeric order**, then build.
> Do not ask clarifying questions. Where something is ambiguous, pick the simplest option that satisfies the docs and record the assumption in `ASSUMPTIONS.md`.

## 1. What we are building
A multi-user web app that finds **idle**, **over-provisioned** and **under-provisioned** AWS EC2 instances and lets the user fix them with one click.

End-to-end flow:
1. User registers / logs in.
2. User connects their AWS account **without sharing keys**: cross-account IAM Role + External ID + STS `AssumeRole` (see `specs/03_AWS_INTEGRATION.md`).
3. Backend fetches CloudWatch metrics + EC2 metadata using the temporary credentials.
4. The existing detection pipeline (`backend/pipeline_source/detector_original.py`) runs on that data.
5. UI shows findings: `IDLE`, `OVER_PROVISIONED`, `UNDER_PROVISIONED` (+ `NEEDS_REVIEW`, `ACTIVE`, etc.) with confidence and explainable evidence.
6. User clicks a suggestion → the app applies it directly in their AWS account (stop / resize / upsize), with confirmation, audit log and undo.
7. A savings dashboard shows realized and potential savings in USD.

## 2. Hard rules (do not violate)
1. **Never ask for, accept, or store AWS access keys / secret keys.** Role ARN + External ID only.
2. **Do NOT change the detection logic or thresholds** in `detector_original.py`. You may only refactor it as listed in `specs/04_DETECTION_PIPELINE_INTEGRATION.md` (remove CLI/env-key code, make it importable, JSON-safe, region-safe caches, expose hourly time series). Keep all scoring maths identical.
3. Default AWS access = **read-only**. Write permissions (stop/resize) are a separate, optional, explicitly-enabled permission set.
4. Every change to a user's AWS account must be: previewed → confirmed → executed asynchronously → audited → undoable where possible.
5. All savings numbers shown to the user are labelled **estimates** (Linux on-demand list price).
6. Must run locally with one command: `docker compose up`. There is **no demo mode** (removed 2026-11-23 at the owner's request): users connect a real AWS account and all data, prices and actions come from AWS. Do not re-add fake data paths.

## 3. Tech stack (use exactly this)
| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2 |
| Pipeline | existing code: boto3, pandas, numpy |
| Jobs | Celery + Redis (worker + beat) |
| DB | PostgreSQL 16 |
| Auth | email + password (argon2), JWT in httpOnly cookie, SameSite=Lax |
| Frontend | React 18 + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query, React Router, Recharts, lucide-react |
| Packaging | Docker Compose: `api`, `worker`, `beat`, `db`, `redis`, `web` |
| Tests | pytest + moto (AWS mocks) on backend, Vitest on frontend |

## 4. Documents (read in order)
| File | Content |
|---|---|
| `specs/01_PRODUCT_REQUIREMENTS.md` | user stories, screens, scope |
| `specs/02_ARCHITECTURE.md` | components, folder layout, data flow, jobs |
| `specs/03_AWS_INTEGRATION.md` | STS/External-ID onboarding, IAM policies, credential handling |
| `specs/04_DETECTION_PIPELINE_INTEGRATION.md` | how to wrap the existing detector, result schema, required refactors |
| `specs/05_REMEDIATION_ACTIONS.md` | apply / undo logic per finding type |
| `specs/06_SAVINGS_DASHBOARD.md` | savings maths and dashboard widgets |
| `specs/07_DATABASE_AND_API.md` | tables and REST endpoints |
| `specs/08_FRONTEND_SPEC.md` | pages, components, UX states, design |
| `specs/09_SECURITY_TESTING_DEMO.md` | security checklist, tests, demo mode, test-instance lab |
| `aws/cloudformation-role.yaml` | the template the user deploys in their own account |
| `backend/pipeline_source/detector_original.py` | the team's pipeline (source of truth for logic) |

## 5. Build order (self-verify after each phase before moving on)
- **Phase 0** – repo scaffold, docker compose, health endpoints, DB migrations.
- **Phase 1** – auth (register / login / logout / me) + frontend shell.
- **Phase 2** – AWS connection flow (pending → connected), verified via real `AssumeRole`, moto-tested.
- **Phase 3** – pipeline adapter + scan job + findings API.
- **Phase 4** – Findings UI (list, filters, detail drawer with evidence + charts).
- **Phase 5** – Remediation engine (dry-run, apply, undo, audit) + confirm modal + action history.
- **Phase 6** – Savings ledger, daily accrual job, dashboard.
- **Phase 7** – scheduled scans, settings, polish, README, tests.

## 6. Definition of done
- `docker compose up` brings everything up; `http://localhost:5173` works.
- With real AWS, a user can connect, scan, see findings, apply an action and see savings.
- Backend tests pass (`pytest`), frontend builds (`npm run build`), no TypeScript errors.
- `README.md` documents setup, env vars, and the AWS platform-account setup steps.
