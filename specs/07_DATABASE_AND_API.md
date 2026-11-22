# 07 — Database & REST API

PostgreSQL 16, SQLAlchemy 2, Alembic migrations. UUID primary keys (`uuid4`), `created_at`/`updated_at` (timestamptz, UTC) on every table.

## 1. Tables

### users
`id, email (unique, lowercased), name, password_hash, is_active, created_at`

### aws_connections
| column | type | notes |
|---|---|---|
| id | uuid | |
| user_id | fk users | |
| label | text | e.g. "Production" |
| external_id | text | generated server-side, unique |
| role_arn | text null | filled on verify |
| aws_account_id | text null | 12 digits |
| enable_actions | bool | user's chosen access level |
| actions_verified | bool | result of DryRun probe |
| status | enum | `pending, connected, broken, disconnected` |
| last_error | text null | |
| last_verified_at | timestamptz null | |
| regions | jsonb | selected regions, `[]` = auto |
| scan_schedule | enum | `off, daily, weekly` (default daily) |
Unique: `(user_id, aws_account_id)` where aws_account_id not null.

### scans
`id, connection_id, status (queued|running|completed|failed|partial), trigger (manual|scheduled), regions jsonb, total_instances int, processed_instances int, started_at, finished_at, error text null, summary jsonb` (summary = counts per status + potential saving).

### findings
| column | type | notes |
|---|---|---|
| id | uuid | |
| scan_id, connection_id | fk | |
| is_latest | bool | only latest per (connection, instance) is true; index it |
| instance_id, region, name | text | |
| instance_type, state | text | |
| tags | jsonb | |
| status | enum | IDLE, OVER_PROVISIONED, UNDER_PROVISIONED, NEEDS_REVIEW, ACTIVE, STOPPED, INSUFFICIENT_DATA, ERROR |
| confidence_score | numeric(5,1) | |
| confidence_band | text | HIGH/MEDIUM/LOW/NONE |
| reason | text | pipeline reason string |
| suggestion | jsonb | doc 04 §5 |
| monthly_saving_usd | numeric(12,2) null | denormalised for sorting/aggregation |
| monthly_delta_usd | numeric(12,2) null | negative = saving |
| metrics, idle, underprovisioned, overprovisioned, evidence_steps | jsonb | |
| hourly_series | jsonb | charts |
| data_quality | numeric null | |
| hours_analyzed | int | |
| memory_checked | bool null | |
| has_memory_metric | bool | |
| action_state | enum | `none, in_progress, applied, undone, failed` |
| dismissed_until | timestamptz null, dismissed_forever bool | |
| cooldown_until | timestamptz null | set after an applied action |

### remediation_actions
`id, user_id, connection_id, finding_id, instance_id, region, action (STOP_INSTANCE|TERMINATE_INSTANCE|RESIZE|ENABLE_UNLIMITED_CREDITS|UNDO_STOP|UNDO_RESIZE|UNDO_CREDITS), parent_action_id null, status (pending|running|succeeded|failed|rolled_back), before jsonb, after jsonb, options jsonb, steps_log jsonb[], error text null, hourly_saving_usd numeric null, savings_active bool, savings_ended_at null, savings_end_reason null, requested_at, started_at, completed_at, celery_task_id`.
Partial unique index: one row per `(connection_id, instance_id)` where status in (`pending`,`running`).

### savings_ledger
`id, connection_id, action_id, instance_id, region, date, hours_in_effect numeric, hourly_saving_usd numeric, amount_usd numeric, kind`. Unique `(action_id, date)`.

### price_cache
`instance_type, region, hourly_usd numeric null, fetched_at` (PK `(instance_type, region)`; TTL 7 days).

### audit_log
`id, user_id null, connection_id null, event (LOGIN, ASSUME_ROLE_OK, ASSUME_ROLE_FAIL, SCAN_START, ACTION_REQUESTED, ACTION_BLOCKED, ACTION_DONE, …), detail jsonb, ip, created_at`.

## 2. REST API (all under `/api/v1`, JSON, cookie auth except register/login)

### Auth
| Method & path | Body | Response |
|---|---|---|
| `POST /auth/register` | `{name,email,password}` | `201` user |
| `POST /auth/login` | `{email,password}` | `200` user + sets cookie |
| `POST /auth/logout` | – | `204` |
| `GET /auth/me` | – | user |

### Connections
| | | |
|---|---|---|
| `GET /connections` | | list (never returns temp creds) |
| `POST /connections` | `{label, enable_actions}` | wizard payload (doc 03 §3) |
| `GET /connections/{id}` | | detail incl. status |
| `POST /connections/{id}/verify` | `{role_arn}` | `{status, checks:[{name,ok,message}]}` |
| `PATCH /connections/{id}` | `{label?, regions?, scan_schedule?, enable_actions?}` | updated; changing `enable_actions` returns a fresh quick-create URL |
| `GET /connections/{id}/regions` | | enabled regions + instance counts |
| `DELETE /connections/{id}` | | `204`, cascades |

### Scans
| | | |
|---|---|---|
| `POST /connections/{id}/scans` | `{regions?}` | `202 {scan_id}` (409 if one already running) |
| `GET /scans/{id}` | | status + progress `{processed, total}` + summary |
| `GET /connections/{id}/scans` | | history (paginated) |

### Findings
| | | |
|---|---|---|
| `GET /findings` | query: `connection_id, status[], region[], band[], q, sort (default: severity then confidence), page, page_size, include_dismissed` | `{items, total, summary:{counts, potential_monthly_saving}}` |
| `GET /findings/{id}` | | full finding incl. evidence + hourly_series |
| `POST /findings/{id}/dismiss` | `{until|forever, reason?}` | updated |
| `POST /findings/{id}/undismiss` | | updated |

Sort order = IDLE, NEEDS_REVIEW, OVER_PROVISIONED, UNDER_PROVISIONED, ACTIVE, …, then confidence desc (mirror `print_table`).

### Actions
| | | |
|---|---|---|
| `POST /findings/{id}/actions/preview` | `{action}` | doc 05 §5 |
| `POST /findings/{id}/actions` | `{action, options, typed_confirmation?}` | `202 {action_id}` |
| `GET /actions/{id}` | | status + `steps_log` (poll every 2 s) |
| `GET /actions` | `connection_id, status, page` | history |
| `POST /actions/{id}/undo` | – | `202 {action_id}` of the undo action (only when reversible & `status=succeeded`) |

### Dashboard
`GET /dashboard/summary`, `GET /dashboard/spend-estimate` (doc 06).

### Misc
`GET /health`, `GET /config/public` → `{demo_mode, platform_account_id, thresholds:{…}, version}`.

## 3. Conventions
- Pagination: `page`, `page_size` (≤100) → `{items,total,page,page_size}`.
- Money: JSON numbers with 2 decimals, currency implied USD.
- Timestamps: ISO-8601 UTC with `Z`.
- Authorisation: every query scoped by `user_id` (via connection ownership). Return `404` (not 403) for other users' resources.
- Validation errors → `422` using Pydantic; domain errors → `409/422` with `{error:{code,message,details?}}`.
- OpenAPI docs enabled at `/docs` in dev.
- Generate TypeScript types for the frontend from the OpenAPI schema (`openapi-typescript`) or hand-write in `lib/types.ts` matching these shapes.
