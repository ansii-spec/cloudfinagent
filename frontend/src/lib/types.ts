// Hand-written to match the API shapes in specs/07 (no `any`).

export type FindingStatus =
  | 'IDLE' | 'OVER_PROVISIONED' | 'UNDER_PROVISIONED' | 'NEEDS_REVIEW'
  | 'ACTIVE' | 'STOPPED' | 'INSUFFICIENT_DATA' | 'ERROR'
export type Band = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'
export type ActionCode = 'STOP_INSTANCE' | 'TERMINATE_INSTANCE' | 'RESIZE' | 'ENABLE_UNLIMITED_CREDITS'
export type AnyActionCode = ActionCode | 'UNDO_STOP' | 'UNDO_RESIZE' | 'UNDO_CREDITS'
export type SuggestedAction = ActionCode | 'NONE'
export type ActionStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'rolled_back'
export type ConnectionStatus = 'pending' | 'connected' | 'broken' | 'disconnected'
export type ScanStatus = 'queued' | 'running' | 'completed' | 'failed' | 'partial'
export type Risk = 'LOW' | 'MEDIUM' | 'HIGH'

export interface ApiErrorBody { error: { code: string; message: string; details?: unknown } }

export interface User { id: string; email: string; name: string; created_at: string | null }

export interface Connection {
  id: string
  label: string
  status: ConnectionStatus
  aws_account_id: string | null
  role_arn: string | null
  enable_actions: boolean
  actions_verified: boolean
  last_error: string | null
  last_verified_at: string | null
  regions: string[]
  scan_schedule: 'off' | 'daily' | 'weekly'
  is_demo: boolean
  created_at: string | null
  wizard?: WizardPayload
}

export interface PolicyDoc { Version: string; Statement: Record<string, unknown>[] }

export interface WizardPayload {
  id: string
  label: string
  status: ConnectionStatus
  external_id: string
  platform_account_id: string
  platform_principal_arn: string
  role_name: string
  enable_actions: boolean
  cloudformation_quick_create_url: string
  cloudformation_template_url: string
  manual_trust_policy_json: PolicyDoc
  manual_permissions_policy_json: PolicyDoc
  permissions: { read_only: string[]; actions: string[] }
}

export interface VerifyCheck { name: string; ok: boolean; message: string }
export interface VerifyResult { status: ConnectionStatus; checks: VerifyCheck[]; connection: Connection }
export interface RegionCount { region: string; instance_count: number }

export interface Scan {
  id: string
  connection_id: string
  status: ScanStatus
  trigger: string
  regions: string[]
  progress: { processed: number; total: number }
  started_at: string | null
  finished_at: string | null
  error: string | null
  summary: { counts?: Partial<Record<FindingStatus, number>>; potential_monthly_saving?: number; total?: number }
  created_at: string | null
}

export interface Suggestion {
  action: SuggestedAction
  alternative_actions: ActionCode[]
  from_type: string | null
  to_type: string | null
  current_hourly_usd: number | null
  target_hourly_usd: number | null
  monthly_delta_usd: number | null
  monthly_saving_usd: number | null
  risk: Risk | null
  downtime_estimate: string | null
  headline: string
  rationale: string
}

export interface EvidenceStep { step: string; calculation: string; result: string }
export interface HourlyPoint { ts: string; cpu_avg: number | null; cpu_max: number | null; net_mb: number | null; ebs_mb: number | null }
export interface MemPoint { ts: string; mem_pct: number | null }

export interface Finding {
  id: string
  scan_id: string
  connection_id: string
  instance_id: string
  region: string
  name: string
  instance_type: string | null
  state: string | null
  tags: Record<string, string>
  status: FindingStatus
  confidence: { score: number; band: Band }
  reason: string
  suggestion: Suggestion | null
  monthly_saving_usd: number | null
  monthly_delta_usd: number | null
  memory_checked: boolean | null
  has_memory_metric: boolean
  data_quality: number | null
  hours_analyzed: number
  action_state: 'none' | 'in_progress' | 'applied' | 'undone' | 'failed'
  dismissed: boolean
  dismissed_until: string | null
  dismissed_forever: boolean
  cooldown_until: string | null
  created_at: string | null
}

export interface ScoreBlock { score: number; band: Band; reason: string; blocked_by?: string[] }
export interface OverBlock {
  status: 'found' | 'none'
  verdict: string
  recommended?: string
  current?: string
  monthly_saving_usd?: number | null
  memory_checked?: boolean
  p99_cpu_max?: number
  needed_vcpu?: number
  current_vcpu?: number
  confidence?: { score: number; band: Band }
  reason: string
}
export interface FindingMetrics {
  cpu_p95_pct?: number
  cpu_p99_pct?: number
  cpu_p99_max_pct?: number
  net_p95_mb_per_hour?: number
  ebs_p95_mb_per_hour?: number
  network_mb_per_day?: number
  network_cv?: number | null
}

export interface FindingDetail extends Finding {
  metrics: FindingMetrics | null
  idle: ScoreBlock | null
  underprovisioned: ScoreBlock | null
  overprovisioned: OverBlock | null
  evidence_steps: EvidenceStep[]
  hourly_series: HourlyPoint[]
  mem_hourly: MemPoint[]
  dismiss_reason: string | null
  actions: RemediationAction[]
}

export interface FindingsResponse extends Page<Finding> {
  summary: {
    counts: Partial<Record<FindingStatus, number>>
    potential_monthly_saving: number
    regions: string[]
    dismissed: number
  }
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface StepLog { ts: string; step: string; status: 'ok' | 'running' | 'error' | 'warning'; message: string }

export interface RemediationAction {
  id: string
  connection_id: string
  finding_id: string | null
  instance_id: string
  instance_name: string
  region: string
  action: AnyActionCode
  parent_action_id: string | null
  status: ActionStatus
  before: { instance_type?: string; state?: string; public_ip?: string | null; price_hourly?: number | null }
  after: { instance_type?: string; state?: string; public_ip?: string | null; backup_ami?: string; snapshots?: string[] }
  options: Record<string, unknown>
  steps_log: StepLog[]
  error: string | null
  monthly_saving_usd: number | null
  savings_active: boolean
  savings_ended_at: string | null
  savings_end_reason: string | null
  undone: boolean
  can_undo: boolean
  performed_by: string | null
  requested_at: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ActionPreview {
  action: ActionCode
  instance: { id: string; name: string; region: string }
  change: { from: string | null; to: string | null }
  cost: { current_monthly: number | null; new_monthly: number | null; monthly_delta: number | null }
  downtime: string
  blockers: string[]
  warnings: string[]
  requires_typed_confirmation: boolean
  options: Record<string, { default: boolean; label: string }>
  undo: string
  estimate_note: string
}

export type SavingsKind = 'STOP' | 'TERMINATE' | 'RESIZE_DOWN' | 'RESIZE_UP'

export interface DashboardSummary {
  currency: 'USD'
  realized: { monthly_run_rate: number; cumulative: number; this_month: number }
  potential: { monthly: number; open_findings: number }
  invested: { monthly: number }
  counts: Record<string, number>
  actions: { applied: number; undone: number; failed: number }
  timeseries: { date: string; daily: number; cumulative: number }[]
  by_action: { kind: SavingsKind; amount: number }[]
  top_instances: {
    action_id: string
    instance_id: string
    name: string
    kind: SavingsKind
    from: string | null
    to: string | null
    monthly_run_rate: number
    cumulative: number
    since: string | null
    active: boolean
  }[]
  spend: { current_monthly: number; before_monthly: number }
  last_scan_at: string | null
}

export interface PublicConfig {
  demo_mode: boolean
  platform_account_id: string
  version: string
  thresholds: {
    idle_threshold: number
    over_threshold: number
    under_threshold: number
    cpu_p95_limit_pct: number
    cpu_p99_max_limit_pct: number
    net_p95_mb_per_hour: number
    ebs_p95_mb_per_hour: number
    under_cpu_p99_limit_pct: number
    credit_starved_below: number
    headroom_pct: number
    idle_weights: Record<string, number>
    lookback_hours: number
    min_history_hours: number
    apply_data_quality: boolean
    protect_substrings: string[]
    protect_tokens: string[]
  }
}
