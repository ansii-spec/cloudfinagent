import { ShieldAlert } from 'lucide-react'
import { Link } from 'react-router'
import { Button, type ButtonProps } from '@/components/ui/button'
import { Tip } from '@/components/ui/tooltip'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { ACTION_SHORT, shortDate } from '@/lib/format'
import type { ActionCode, Finding } from '@/lib/types'

/** Why Apply is not possible right now (null = allowed). */
export function applyBlockReason(f: Finding, readOnly: boolean): string | null {
  const action = f.suggestion?.action
  if (!action || action === 'NONE') return f.status === 'NEEDS_REVIEW' ? 'Review manually: no automatic fix' : 'No action suggested'
  if (f.status === 'NEEDS_REVIEW' || f.status === 'INSUFFICIENT_DATA') return 'No automatic fix for this status'
  if (f.action_state === 'in_progress') return 'An action is already running for this instance'
  if (f.cooldown_until) return `Recently changed; re-evaluated after ${shortDate(f.cooldown_until)}`
  if (readOnly) return 'This connection is read-only'
  return null
}

export function ApplyButton({ finding, action, onApply, size = 'sm', variant, label }: {
  finding: Finding
  action?: ActionCode
  onApply: (a: ActionCode) => void
  size?: ButtonProps['size']
  variant?: ButtonProps['variant']
  label?: string
}) {
  const { current } = useConnectionCtx()
  const readOnly = !(current?.enable_actions && current?.actions_verified)
  const act = action ?? (finding.suggestion?.action as ActionCode | undefined)
  const reason = applyBlockReason(finding, readOnly)
  if (reason === 'This connection is read-only' && act) {
    return (
      <Tip content="This connection is read-only. Enable actions to apply fixes in one click.">
        <Button size={size} variant="outline" asChild onClick={(e) => e.stopPropagation()}>
          <Link to="/settings?tab=connections"><ShieldAlert />Enable actions</Link>
        </Button>
      </Tip>
    )
  }
  return (
    <Tip content={reason}>
      {/* span keeps the tooltip working on a disabled button */}
      <span tabIndex={reason ? 0 : -1} className="inline-flex">
        <Button size={size} variant={variant} disabled={!!reason || !act}
          onClick={(e) => { e.stopPropagation(); if (act) onApply(act) }}>
          {label ?? (act && act in ACTION_SHORT ? `Apply: ${ACTION_SHORT[act]}` : 'Apply')}
        </Button>
      </span>
    </Tip>
  )
}
