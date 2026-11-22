import type { ActionPreview, Connection, Finding } from '@/lib/types'

export const connection: Connection = {
  id: 'c1', label: 'Demo', status: 'connected', aws_account_id: '000000000000', role_arn: 'arn:aws:iam::000000000000:role/X',
  enable_actions: true, actions_verified: true, last_error: null, last_verified_at: null, regions: [], scan_schedule: 'daily',
  is_demo: true, created_at: null,
}

export function finding(over: Partial<Finding> = {}): Finding {
  return {
    id: 'f1', scan_id: 's1', connection_id: 'c1', instance_id: 'i-0a1b2c3d4e5f60004', region: 'ap-south-1', name: 'reporting-worker',
    instance_type: 'm5.2xlarge', state: 'running', tags: {}, status: 'OVER_PROVISIONED', confidence: { score: 83.5, band: 'HIGH' },
    reason: 'p99 max CPU 9.8%', monthly_saving_usd: 210.24, monthly_delta_usd: -210.24, memory_checked: true, has_memory_metric: true,
    data_quality: 0.95, hours_analyzed: 336, action_state: 'none', dismissed: false, dismissed_until: null, dismissed_forever: false,
    cooldown_until: null, created_at: null,
    suggestion: {
      action: 'RESIZE', alternative_actions: [], from_type: 'm5.2xlarge', to_type: 'm5.large', current_hourly_usd: 0.384,
      target_hourly_usd: 0.096, monthly_delta_usd: -210.24, monthly_saving_usd: 210.24, risk: 'MEDIUM', downtime_estimate: '~2-5 min',
      headline: 'Downsize m5.2xlarge → m5.large', rationale: 'fits',
    },
    ...over,
  }
}

export function preview(over: Partial<ActionPreview> = {}): ActionPreview {
  return {
    action: 'RESIZE', instance: { id: 'i-0a1b2c3d4e5f60004', name: 'reporting-worker', region: 'ap-south-1' },
    change: { from: 'm5.2xlarge', to: 'm5.large' }, cost: { current_monthly: 280.32, new_monthly: 70.08, monthly_delta: -210.24 },
    downtime: '~2-5 minutes', blockers: [], warnings: ['Public IP will change'], requires_typed_confirmation: false,
    options: { create_backup_ami: { default: true, label: 'Create a backup AMI first' } }, undo: 'Resize back', estimate_note: 'Estimates.',
    ...over,
  }
}
