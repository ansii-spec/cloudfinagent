import { cn } from '@/lib/utils'

/** 0-100 score with a marker at the decision threshold. */
export function ScoreGauge({ label, score, threshold, hit }: { label: string; score: number | null | undefined; threshold: number; hit: boolean }) {
  const v = score == null ? null : Math.max(0, Math.min(100, score))
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className={cn('text-lg font-semibold tabular-nums', hit && 'text-primary')}>{v == null ? '—' : v.toFixed(1)}</span>
      </div>
      <div className="relative mt-2 h-2 rounded-full bg-muted" role="meter" aria-label={`${label} score`} aria-valuenow={v ?? 0} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full rounded-full', hit ? 'bg-primary' : 'bg-muted-foreground/40')} style={{ width: `${v ?? 0}%` }} />
        <div className="absolute -top-1 h-4 w-0.5 bg-foreground" style={{ left: `${threshold}%` }} title={`threshold ${threshold}`} />
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">threshold {threshold}{hit ? ' · reached' : ''}</p>
    </div>
  )
}
