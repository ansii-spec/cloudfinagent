# 02 — Architecture

## 1. Component diagram

```
 Browser (React SPA)
      │  HTTPS, cookie auth
      ▼
 FastAPI  (api)  ──────────────►  PostgreSQL  (users, connections, scans, findings, actions, ledger)
      │   enqueue                       ▲
      ▼                                 │
   Redis  ◄──── Celery worker(s) ───────┘
                 │   │
                 │   └─ pipeline adapter ──► detector (pandas/numpy logic)
                 │
                 ├─ sts:AssumeRole  ───────►  USER'S AWS ACCOUNT (EC2, CloudWatch)
                 └─ pricing:GetProducts ───►  AWS Pricing API (platform's own credentials)

 Celery beat: daily scans, daily savings accrual, nightly reconcile
```

## 2. Repository layout (create exactly this)

```
ec2-optimizer/
├── CLAUDE.md, ASSUMPTIONS.md, README.md, docker-compose.yml, .env.example
├── aws/cloudformation-role.yaml
├── docs/                         (these spec files, keep them)
├── backend/
│   ├── Dockerfile, pyproject.toml / requirements.txt, alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py               FastAPI app, CORS, routers
│   │   ├── config.py             pydantic-settings (env vars)
│   │   ├── db.py                 engine, session
│   │   ├── models/               SQLAlchemy models (doc 07)
│   │   ├── schemas/              Pydantic request/response models
│   │   ├── api/                  auth.py connections.py scans.py findings.py actions.py dashboard.py settings.py
│   │   ├── core/                 security.py (hash, jwt), deps.py (current_user), errors.py
│   │   ├── services/
│   │   │   ├── aws_session.py    AssumeRole + credential cache + error mapping
│   │   │   ├── scan_service.py   orchestrates a scan
│   │   │   ├── pricing_service.py platform-credential price lookup + DB cache
│   │   │   ├── remediation_service.py  apply/undo (doc 05)
│   │   │   ├── savings_service.py ledger + aggregates (doc 06)
│   │   │   └── demo_service.py   DEMO_MODE fixtures + fake executor
│   │   ├── pipeline/
│   │   │   ├── detector.py       REFACTORED copy of detector_original.py (doc 04)
│   │   │   ├── adapter.py        analyze_instance(...) / analyze_region(...) → JSON-safe dict
│   │   │   ├── recommend.py      builds the "suggested action" incl. upsize target
│   │   │   └── serialization.py  numpy/datetime/tuple → JSON
│   │   └── workers/
│   │       ├── celery_app.py
│   │       └── tasks.py          run_scan, execute_action, accrue_savings, reconcile, scheduled_scans
│   ├── tests/  (moto-based; fixtures/sample_findings.json)
│   └── pipeline_source/detector_original.py   (untouched reference copy)
└── frontend/
    ├── package.json, vite.config.ts, tailwind.config.ts
    └── src/
        ├── main.tsx, App.tsx, routes.tsx
        ├── api/ (client.ts, hooks per resource)
        ├── pages/ (Login, Register, Connect, Dashboard, Recommendations, Actions, Settings)
        ├── components/ (StatusBadge, ConfidenceBar, FindingDrawer, EvidenceTable, MetricChart, ConfirmActionModal, SavingsCards, ...)
        └── lib/ (format.ts, types.ts)
```

## 3. Key flows

### 3.1 Connect
`POST /connections` → creates `pending` row with a server-generated External ID → UI shows wizard → user deploys stack → `POST /connections/{id}/verify {role_arn}` → backend calls `AssumeRole` → success ⇒ `connected`.

### 3.2 Scan (Celery task `run_scan`)
```
for region in selected_regions:
    session = aws_session.get(connection)            # cached temporary credentials
    ec2, cw = clients(session, region)
    metas = fetch_instance_metadata(ec2)
    for each instance (ThreadPoolExecutor, max 5):
        if state != running → STOPPED row
        metrics = fetch_cloudwatch_metrics(...)       # 14 d lookback in production
        r = classify_and_score(...)
        over = check_overprovisioned(...) unless idle wins
        r = run_cascade(r, over)
        finding = recommend.build(r, ladder, price_fn) # adds suggested action, upsize target, savings
        save finding
update scan.progress after each instance (UI polls)
mark previous findings is_latest=false, new ones true
```

### 3.3 Apply
`POST /findings/{id}/actions` → validates → inserts `remediation_actions` (`pending`) → Celery `execute_action` → status updates `running → succeeded|failed|rolled_back` → on success writes savings ledger start row → UI polls `GET /actions/{id}`.

### 3.4 Savings accrual
Celery beat, daily 00:10 UTC: for every active action, add a ledger row for the elapsed hours; nightly reconcile compares real instance state with the ledger and stops accrual if the user changed it outside the app.

## 4. Configuration (env vars, put all in `.env.example`)

| Var | Purpose |
|---|---|
| `DATABASE_URL`, `REDIS_URL` | infra |
| `SECRET_KEY` | JWT signing |
| `PLATFORM_AWS_ACCOUNT_ID` | shown to users in the wizard |
| `PLATFORM_PRINCIPAL_ARN` | the principal users trust (role/user in platform account) |
| `PLATFORM_AWS_ACCESS_KEY_ID`, `PLATFORM_AWS_SECRET_ACCESS_KEY` | **dev only**; in production use an instance/task role instead |
| `PLATFORM_AWS_REGION` | default `us-east-1` |
| `CFN_TEMPLATE_URL` | public S3 URL of `aws/cloudformation-role.yaml` |
| `ROLE_NAME` | default `EC2OptimizerAccessRole` |
| `LOOKBACK_HOURS` | default `336` (14 d); dev may use `35` |
| `MIN_HISTORY_HOURS` | default `168`; dev may use `20` |
| `APPLY_DATA_QUALITY` | `true` in production, `false` for short test runs (mirrors the constant in the detector) |
| `DEMO_MODE` | `true` = no AWS calls anywhere, fixtures + fake executor |
| `FRONTEND_ORIGIN` | CORS |

## 5. Error-handling conventions
- API errors: `{ "error": { "code": "STRING_CODE", "message": "human text" } }` with correct HTTP status.
- AWS errors are mapped through one function `explain_aws_error(e)` (extend it for `AccessDenied` on `AssumeRole`, `InvalidClientTokenId`, `ExpiredToken`, `Throttling`, `UnauthorizedOperation`, `DryRunOperation`, `IncorrectInstanceState`).
- Configure boto3 with `Config(retries={"max_attempts": 10, "mode": "adaptive"}, connect_timeout=5, read_timeout=30)`.
