import { STATUS_LABEL } from '@/lib/format'
import type { FindingStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

// Console-style status (same as the original design): coloured dot + label, readable without colour.
const STYLE: Record<FindingStatus, [text: string, dot: string]> = {
  IDLE: ['text-info', 'bg-info'],
  OVER_PROVISIONED: ['text-warning', 'bg-warning'],
  UNDER_PROVISIONED: ['text-destructive', 'bg-destructive'],
  NEEDS_REVIEW: ['text-warning', 'bg-warning'],
  ACTIVE: ['text-success', 'bg-success'],
  STOPPED: ['text-muted-foreground', 'bg-muted-foreground'],
  INSUFFICIENT_DATA: ['text-muted-foreground', 'border border-muted-foreground bg-transparent'],
  ERROR: ['text-destructive', 'border-2 border-destructive bg-transparent'],
}

export function StatusBadge({ status, className }: { status: FindingStatus; className?: string }) {
  const [text, dot] = STYLE[status]
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-sm font-medium whitespace-nowrap', text, className)} data-status={status}>
      <span className={cn('size-2 shrink-0 rounded-full', dot)} aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  )
}
