import { signedMoney } from '@/lib/format'
import type { Risk } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Monthly delta: savings in green (−$210), cost increases in neutral blue (+$30), never red. */
export function MonthlyDelta({ delta, className, suffix = true }: { delta: number | null | undefined; className?: string; suffix?: boolean }) {
  if (delta == null || delta === 0) return <span className={cn('text-muted-foreground', className)}>—</span>
  return (
    <span className={cn('font-medium tabular-nums', delta < 0 ? 'text-success' : 'text-info', className)}>
      {signedMoney(delta)}
      {suffix && <span className="text-xs font-normal text-muted-foreground">/mo</span>}
    </span>
  )
}

const RISK: Record<Risk, string> = {
  LOW: 'text-success bg-success/10',
  MEDIUM: 'text-warning bg-warning/10',
  HIGH: 'text-destructive bg-destructive/10',
}
export function RiskChip({ risk }: { risk: Risk | null | undefined }) {
  if (!risk) return <span className="text-muted-foreground">—</span>
  return <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-semibold', RISK[risk])}>{risk} risk</span>
}
