import type { Band } from '@/lib/types'
import { cn } from '@/lib/utils'

const BAND: Record<Band, string> = {
  HIGH: 'bg-success/10 text-success',
  MEDIUM: 'bg-warning/10 text-warning',
  LOW: 'bg-muted text-muted-foreground',
  NONE: 'bg-transparent text-muted-foreground',
}
const BAR: Record<Band, string> = { HIGH: 'bg-success', MEDIUM: 'bg-warning', LOW: 'bg-muted-foreground', NONE: 'bg-border' }

export function BandChip({ band }: { band: Band }) {
  return <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-semibold', BAND[band])}>{band === 'NONE' ? '—' : band}</span>
}

export function ConfidenceBar({ score, band, showBand = true }: { score: number; band: Band; showBand?: boolean }) {
  if (band === 'NONE') return <span className="text-xs text-muted-foreground">—</span>
  const v = Math.max(0, Math.min(100, score))
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted" role="meter" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label="Confidence">
        <div className={cn('h-full rounded-full', BAR[band])} style={{ width: `${v}%` }} />
      </div>
      <span className="w-9 text-xs tabular-nums">{Math.round(v)} %</span>
      {showBand && <BandChip band={band} />}
    </div>
  )
}
