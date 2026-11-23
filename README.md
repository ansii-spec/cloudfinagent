# EC2 Optimizer (FYP)

Finds **idle**, **over-provisioned** and **under-provisioned** EC2 instances in a user's AWS account, explains why (the team's detection pipeline, unchanged), and fixes them with one click (stop / resize / unlimited credits) with preview, confirmation, audit log and undo. A savings dashboard tracks realized and potential savings (estimates).

```
 Browser (React SPA) ──cookie──► FastAPI (api) ──► PostgreSQL
                                   │ enqueue
                                   ▼
                     Redis ◄── Celery worker / beat ──► sts:AssumeRole ──► USER'S AWS (EC2, CloudWatch)
                                   │                └─► Pricing API (platform credentials)
                                   └─ pipeline adapter ──► detector (pandas / numpy)
```

No AWS access keys are ever accepted: users deploy a CloudFormation role (`aws/cloudformation-role.yaml`) that trusts our platform principal only with their unique **External ID**.

## Quick start (One Command)

To run the entire application stack (Database, Redis, Backend API, Worker, Beat, and Frontend Web):

```bash
./run.sh
```

Or using Docker Compose directly:
```bash
docker compose up -d
```

Or using Make:
```bash
make run
```

Once running:
- **Web App**: http://localhost:5173
- **API Backend**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

### Without Docker
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export DATABASE_URL=sqlite:///./local.db CELERY_EAGER=true DEMO_MODE=true
.venv/bin/alembic upgrade head && .venv/bin/python -m app.scripts.seed_demo
.venv/bin/uvicorn app.main:app --port 8000
cd ../frontend && npm install && npm run dev
```

## Platform AWS account setup (real mode)
1. In **your** (platform) account create an IAM role or user `ec2opt-backend` with:
   ```json
   {"Version":"2012-10-17","Statement":[
     {"Effect":"Allow","Action":"sts:AssumeRole","Resource":"arn:aws:iam::*:role/EC2OptimizerAccessRole"},
     {"Effect":"Allow","Action":"pricing:GetProducts","Resource":"*"}]}
   ```
2. Upload `aws/cloudformation-role.yaml` to a public S3 bucket; set `CFN_TEMPLATE_URL`.
3. Set `DEMO_MODE=false`, `PLATFORM_AWS_ACCOUNT_ID`, `PLATFORM_PRINCIPAL_ARN` and (dev only) `PLATFORM_AWS_ACCESS_KEY_ID/SECRET`. In production use an instance/task role instead of keys.

All variables are documented in `.env.example`. For quick lab runs use `LOOKBACK_HOURS=35 MIN_HISTORY_HOURS=20 APPLY_DATA_QUALITY=false`.

## Tests
```bash
cd backend && .venv/bin/python -m pytest       # pipeline regression vs original, moto AWS, API, savings
cd frontend && npm test && npm run build       # Vitest + tsc + vite build
```
Dependency audits: `pip-audit -r backend/requirements.txt`, `npm audit` (in `frontend/`).

## Detector evaluation (FYP report)
`python backend/scripts/evaluate.py labels.csv --connection-id <uuid> --scan` → `evaluation_report.md` (confusion matrix, precision / recall).

## Cost of running
`GetMetricData` is billed per metric (~8–12 per instance per scan): daily scans of 50 instances cost cents per month. Pricing API calls are free and cached 7 days. A single small VM running Docker Compose is enough for the demo.

## Known limitations
Linux on-demand list prices only (no RI / Savings Plans / Spot / Windows), EC2 only, EBS not modelled, ASG/EKS/ECS-managed instances are never modified, 7-day cool-down after a change.

## Screenshots
_TODO_
