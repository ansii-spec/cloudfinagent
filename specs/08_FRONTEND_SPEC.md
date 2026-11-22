# 08 — Frontend Specification

Stack: React 18 + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query, React Router, Recharts, lucide-react. Responsive (desktop-first, usable at 375 px), light + dark mode.

## 1. Design language
- Clean SaaS dashboard: left sidebar (Dashboard, Recommendations, Actions, Settings), top bar (connection switcher, "Run scan" button, user menu).
- Neutral background, one accent colour (indigo/teal). Cards with soft borders, 12 px radius, generous spacing.
- **Status badges** (always icon + text, never colour alone):
  | Status | Colour | Icon |
  |---|---|---|
  | IDLE | slate/grey-blue | `PowerOff` |
  | OVER_PROVISIONED | amber | `TrendingDown` |
  | UNDER_PROVISIONED | red | `TrendingUp` |
  | NEEDS_REVIEW | yellow | `Eye` |
  | ACTIVE | green | `CheckCircle2` |
  | STOPPED | grey | `Square` |
  | INSUFFICIENT_DATA | grey dashed | `Hourglass` |
  | ERROR | red outline | `AlertTriangle` |
- Confidence shown as a thin progress bar + `83 %` + band chip (HIGH green, MEDIUM amber, LOW grey).
- Money formatted with `Intl.NumberFormat('en-US',{style:'currency',currency:'USD'})`; savings in green, cost increases in neutral/blue (not red).
- Every page implements **loading skeletons, empty states, error states with retry**.
- Toasts for success/failure; optimistic UI not needed.

## 2. Routes

| Route | Auth | Page |
|---|---|---|
| `/login`, `/register` | public | Auth pages |
| `/` | auth | redirects to `/dashboard` (or `/connect` if no connection) |
| `/connect` | auth | Connection wizard |
| `/dashboard` | auth | Savings dashboard (doc 06 §5) |
| `/recommendations` | auth | Findings list |
| `/recommendations/:id` | auth | Same list with the detail drawer open (deep-linkable) |
| `/actions` | auth | Action history |
| `/settings` | auth | Connections, regions, schedule, account, "How detection works" |
| `*` | | 404 |

Route guard: redirect unauthenticated users to `/login?next=…`.

## 3. Pages in detail

### 3.1 Login / Register
Split layout: form on one side, product value-prop on the other (three bullets: "Find idle & oversized EC2", "No AWS keys – secure role access", "One-click fixes & savings tracking"). Inline validation (email format, password ≥ 10 chars).

### 3.2 Connect wizard (`/connect`)
Stepper with 3 steps; state persisted by connection id so a refresh resumes.
1. **Access level** – two selectable cards: *Read-only* (recommended to start) / *Read + Actions*. Short list of exactly which AWS permissions each includes (from API payload).
2. **Create the role** – tabs *One-click (CloudFormation)* and *Manual*. Show: platform account ID, **External ID** (copy button), explanation tooltip "Why an External ID?". Illustrate the security flow with the 5-box diagram from the team's picture (User creates IAM role → shares ARN + external ID → app calls STS AssumeRole → STS validates trust → temporary credentials ~1 h). Render it as an SVG/Tailwind component (not an image file).
3. **Verify** – input for Role ARN, "Verify connection" button → checklist result (✔ AssumeRole, ✔ EC2 read, ✔ CloudWatch read, ✔/✖ Actions). On success: confetti-free success state + "Run first scan" button, region multi-select.
Footer note: "You can revoke access any time by deleting the CloudFormation stack."

### 3.3 Recommendations (`/recommendations`)
- **Summary strip** (clickable filters): IDLE n · OVER n · UNDER n · NEEDS REVIEW n · Potential savings $X/mo.
- **Toolbar:** search, status multi-select, region multi-select, confidence band, "show dismissed", sort dropdown, "Last scanned 2 h ago · Run scan".
- **Scan progress banner** while a scan runs (`processed/total`, polling `GET /scans/{id}` every 2 s).
- **Table** (TanStack Table, paginated): Name+ID · Region · Type · Status badge · Confidence bar · Suggestion (`headline`) · Est. $/month (green `−$210`/blue `+$30`) · Risk chip · primary button **Apply** (or *Review*/*Details*).
  - Apply is disabled with tooltip when: connection read-only (button "Enable actions" opens the upgrade dialog), action not applicable (`NONE`), action in progress, or cool-down active.
  - Row click opens the drawer.
- Mobile: table collapses to cards.

### 3.4 Finding drawer (`FindingDrawer`)
Right-side sheet (wide), sections:
1. **Header:** name, instance ID, region, type, state, status badge, confidence, tags (protective tags highlighted if they blocked IDLE).
2. **Recommendation card:** headline, rationale, from→to type, cost before/after, risk, downtime, buttons **Apply** · **Dismiss** · *Alternative* (e.g. Terminate for idle).
3. **Why we think so (explainability):**
   - three score gauges: Idle / Over-provisioned / Under-provisioned (0-100) with the threshold marker (65/60/70);
   - key metrics tiles: CPU p95, CPU p99-max, network p95 MB/h, EBS p95 MB/h, data quality, hours analysed;
   - **EvidenceTable** of `evidence_steps` (step / calculation / result) – this is the pipeline's step trail;
   - guard messages (`idle.blocked_by`), memory-not-checked warning chip + "install CloudWatch agent" help link.
4. **Charts** (Recharts, hourly): CPU avg vs CPU max (line, with 5 % / 10 % / 80 % reference lines as relevant), network MB/h, EBS MB/h, memory % (if present). Range = analysed window.
5. **Action history** for this instance.

### 3.5 Confirm action modal (`ConfirmActionModal`)
Calls `POST /findings/{id}/actions/preview`; renders: change summary, cost table (current / new / delta per month), downtime, **blockers** (red, Apply disabled) and **warnings** (amber), options (e.g. "Create backup AMI first" checkbox), required "I understand" checkbox, typed-instance-ID input for terminate. On confirm → `POST …/actions` → modal switches to a **live progress view** (stepper fed by `steps_log`, polling every 2 s) with final states: ✔ Success (with "Undo" link) / ✖ Failed / ↩ Rolled back with explanation.

### 3.6 Actions history (`/actions`)
Table: time, instance, action, from → to, status, saving/month, performed by, **Undo** button (when allowed), expandable row with `steps_log` and error.

### 3.7 Dashboard (`/dashboard`)
As in doc 06 §5. Top of page: last scan time + "Run scan" + range selector. Use skeletons for charts.

### 3.8 Settings
Tabs: **Connections** (status chip, account ID, role ARN, regions, schedule, enable actions, re-verify, disconnect with confirm) · **Account** (name, password change, delete account) · **How detection works** (read-only table of thresholds and a plain-English explanation of Idle, Over- and Under-provisioned logic; link to CloudWatch agent guide).

## 4. Frontend architecture
- `api/client.ts`: fetch wrapper with `credentials: "include"`, JSON error normalisation, 401 → redirect to login.
- One TanStack Query hook per resource (`useFindings`, `useFinding`, `useScan`, `useActionPreview`, `useDashboardSummary`, …). Polling via `refetchInterval` while status is `queued|running|pending`.
- Global `ConnectionProvider` (selected connection id persisted in localStorage — this is the *app's own* frontend, not an artifact, so localStorage is fine).
- Components library under `components/ui` (shadcn) + domain components named in doc 02.
- Strict TypeScript, ESLint, Prettier; no `any` in API types.
- Accessibility: focus-trapped modal/drawer, ARIA labels on icon buttons, table headers scoped.

## 5. DEMO_MODE behaviour (frontend)
`GET /config/public` returns `demo_mode:true` → show a dismissible banner "Demo mode: sample data, no AWS account is touched". The connect wizard offers a **"Use demo account"** button that creates an instantly-connected demo connection with fixtures (≈ 14 instances covering every status), so the evaluator can click through the full flow.

## 6. Frontend tests
Vitest + Testing Library: StatusBadge rendering for all statuses, Recommendations filtering, ConfirmActionModal states (blockers disable confirm; terminate requires typed ID), money formatting, route guards.
