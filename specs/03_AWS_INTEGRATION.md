# 03 — AWS Integration (cross-account role + External ID + STS)

This implements the diagram the team chose (AWS Well-Architected "share securely with third parties"):

```
User creates IAM role (in their account)
  → shares Role ARN + External ID (identifiers, not secrets)
    → our backend calls STS AssumeRole(RoleArn, ExternalId)
      → STS validates trust policy + External ID match
        → temporary credentials (~1 h) used for API calls
```

**We never see or store access keys.**

## 1. Two AWS identities involved

| Identity | Lives in | Purpose |
|---|---|---|
| **Platform principal** (`PLATFORM_PRINCIPAL_ARN`) | OUR AWS account | The only principal allowed to assume customer roles. Needs `sts:AssumeRole` on `arn:aws:iam::*:role/EC2OptimizerAccessRole` and `pricing:GetProducts`. Dev: an IAM user whose keys sit in `.env`. Production: instance/task role. |
| **Customer role** (`EC2OptimizerAccessRole`) | USER'S AWS account | Trusts the platform principal, only when the correct External ID is presented. Carries the EC2/CloudWatch permissions. |

### Platform principal policy (document in README)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": "arn:aws:iam::*:role/EC2OptimizerAccessRole"},
    {"Effect": "Allow", "Action": "pricing:GetProducts", "Resource": "*"}
  ]
}
```
Pricing is public list-price data, so the **platform's own credentials** call the Pricing API (always endpoint `us-east-1`). The customer role therefore does NOT need `pricing:*`. This changes `get_aws_clients` in the detector (see doc 04).

## 2. External ID rules
- Generated **by our backend**, never chosen by the user: `secrets.token_urlsafe(24)`.
- Unique per connection; stored in `aws_connections.external_id`.
- Not a secret, but never shown to other users and never logged with the role ARN.
- Purpose: prevents the "confused deputy" problem (another customer can't make us assume your role).

## 3. Onboarding wizard (backend + UI behaviour)

**Step 1 – Choose access level**
- "Read-only (analysis)" → `EnableActions=false`.
- "Read + Actions (one-click fixes)" → `EnableActions=true`.

**Step 2 – Create the role**
Backend `POST /connections` returns:
```json
{
  "id": "uuid",
  "external_id": "…",
  "platform_account_id": "123456789012",
  "platform_principal_arn": "arn:aws:iam::123456789012:role/ec2opt-backend",
  "role_name": "EC2OptimizerAccessRole",
  "enable_actions": false,
  "cloudformation_quick_create_url": "https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?templateURL=<CFN_TEMPLATE_URL>&stackName=EC2OptimizerAccess&param_PlatformPrincipalArn=<…>&param_ExternalId=<…>&param_EnableActions=false&param_RoleName=EC2OptimizerAccessRole",
  "manual_trust_policy_json": { … },
  "manual_permissions_policy_json": { … }
}
```
UI offers two tabs:
1. **One-click (recommended)** – button opens the quick-create URL in a new tab; user clicks "Create stack"; copies the stack **Output `RoleArn`**.
2. **Manual** – shows copy-able trust policy + permission policy JSON and console instructions.

**Step 3 – Verify**
User pastes Role ARN → `POST /connections/{id}/verify`.

Backend verification algorithm:
1. Validate ARN with regex `^arn:aws:iam::(\d{12}):role/[\w+=,.@/-]+$`; extract account id.
2. `sts.assume_role(RoleArn, RoleSessionName=f"ec2opt-{user_id[:8]}", ExternalId=conn.external_id, DurationSeconds=3600)`.
3. With the temp credentials call `sts.get_caller_identity()`; assert `Account` equals the ARN's account.
4. Probe permissions with cheap calls: `ec2.describe_regions()`, `cloudwatch.list_metrics(Namespace="AWS/EC2")` (limit), `ec2.describe_instance_types(MaxResults=5)`. If `enable_actions`, probe with `DryRun=True` on `ec2.stop_instances` for a nonexistent id and expect `InvalidInstanceID.*` or `DryRunOperation` / `UnauthorizedOperation` → interpret (UnauthorizedOperation = actions policy missing).
5. Save `role_arn`, `aws_account_id`, `status="connected"`, `last_verified_at`, `actions_verified` boolean; return what passed/failed per probe so the UI can show a checklist (✔ AssumeRole, ✔ EC2 read, ✔ CloudWatch read, ✔/✖ Actions).
6. On `AccessDenied`: show "Trust policy / External ID mismatch. Check the stack parameters." Don't leak internals.

**Upgrading to actions later:** UI shows "Enable actions" → returns a new quick-create URL with `EnableActions=true` (CloudFormation *update stack* works; show both instructions) → user clicks "Re-verify".

## 4. Credential handling (`services/aws_session.py`)

```python
def get_session(connection) -> boto3.Session:
    """Return a boto3 Session using cached temporary credentials for this connection."""
```
- Cache per `connection.id` in Redis (key `awscreds:{id}`), value = encrypted JSON (Fernet using `SECRET_KEY`-derived key) with expiry; refresh when < 5 min remain.
- Never write temporary credentials to Postgres or logs.
- Long jobs: refresh credentials between instances/regions (a scan can outlive 1 hour).
- Use `RoleSessionName` containing the user/connection id so the customer sees our activity in their CloudTrail.
- If AssumeRole returns `AccessDenied` ⇒ mark connection `broken`, store `last_error`, stop scheduled scans for it, show banner.

## 5. Customer IAM permissions

### 5.1 Always (analysis) — policy `ReadOnlyAnalysis`
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstanceStatus",
      "ec2:DescribeRegions",
      "ec2:DescribeVolumes",
      "ec2:DescribeTags",
      "ec2:DescribeAddresses",
      "ec2:DescribeImages",
      "ec2:DescribeSnapshots",
      "autoscaling:DescribeAutoScalingInstances",
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics"
    ],
    "Resource": "*"
  }]
}
```
(`DescribeAddresses`, `autoscaling:Describe*` are used by remediation pre-checks: Elastic IP present? ASG-managed?)

### 5.2 Optional (actions) — policy `RemediationActions`, only when `EnableActions=true`
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:StopInstances",
      "ec2:StartInstances",
      "ec2:TerminateInstances",
      "ec2:ModifyInstanceAttribute",
      "ec2:ModifyInstanceCreditSpecification",
      "ec2:CreateTags",
      "ec2:CreateSnapshot",
      "ec2:CreateImage"
    ],
    "Resource": "*"
  }]
}
```
The shipped CloudFormation template (`aws/cloudformation-role.yaml`) already encodes both policies behind the `EnableActions` parameter. Keep the template and the JSON in this doc in sync; the backend's `manual_*_policy_json` response fields must be generated from the same source constants.

## 6. Regions
- After connecting, call `ec2.describe_regions()` (enabled regions only) and let the user pick regions (default: all with ≥1 non-terminated instance, discovered by a cheap `describe_instances` per region).
- Pipeline functions already take a region-specific client; the scan loops over regions.

## 7. Security notes
- Trust policy principal should be the specific platform role/user ARN, not `:root`, in production (the template parameter `PlatformPrincipalArn` allows either).
- Max session duration 1 hour; we re-assume as needed.
- Tell users in the UI: "You can revoke access any time by deleting the CloudFormation stack."
- Log every AssumeRole success/failure in `audit_log` (no credentials).
