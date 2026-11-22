import { AlertTriangle, BellOff, ExternalLink, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useDismiss, useFinding, usePublicConfig, useUndismiss } from '@/api/hooks'
import { ApplyButton } from '@/components/ApplyButton'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { ConfirmActionModal } from '@/components/ConfirmActionModal'
import { EvidenceTable } from '@/components/EvidenceTable'
import { MetricChart } from '@/components/MetricChart'
import { MonthlyDelta, RiskChip } from '@/components/Money'
import { ScoreGauge } from '@/components/ScoreGauge'
import { ErrorState } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, SheetContent } from '@/components/ui/dialog'
import { Input, Label } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ACTION_LABEL, ACTION_SHORT, dateTime, money, num, pct } from '@/lib/format'
import type { ActionCode, FindingDetail } from '@/lib/types'

export function FindingDrawer({ findingId, onClose }: { findingId: string | null; onClose: () => void }) {
  const { data, error, isLoading, refetch } = useFinding(findingId)
  const [action, setAction] = useState<ActionCode | null>(null)
  return (
    <Dialog open={!!findingId} onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent title={data?.name || data?.instance_id || 'Instance details'}>
        <div className="flex-1 overflow-y-auto p-5 sm:p-6">
          {isLoading && <div className="space-y-4"><Skeleton className="h-20" /><Skeleton className="h-40" /><Skeleton className="h-64" /></div>}
          {error && <ErrorState error={error} onRetry={() => refetch()} />}
          {data && <DrawerBody f={data} onApply={setAction} />}
        </div>
        {data && <ConfirmActionModal findingId={data.id} action={action} onClose={() => setAction(null)} />}
      </SheetContent>
    </Dialog>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function DrawerBody({ f, onApply }: { f: FindingDetail; onApply: (a: ActionCode) => void }) {
  const { data: cfg } = usePublicConfig()
  const th = cfg?.thresholds
  const s = f.suggestion
  const blocked = f.idle?.blocked_by ?? []
  const protectedWords = new Set([...(th?.protect_substrings ?? []), ...(th?.protect_tokens ?? [])])
  const isProtective = (k: string, v: string) =>
    blocked.length > 0 && [...protectedWords].some((w) => `${k}=${v}`.toLowerCase().includes(w))
  const over = f.overprovisioned
  const overScore = over?.status === 'found' ? over.confidence?.score ?? null : 0
  const mem = new Map(f.mem_hourly.map((m) => [m.ts, m.mem_pct]))
  const series = f.hourly_series.map((p) => ({ ...p, mem_pct: mem.get(p.ts) ?? null }))

  return (
    <div className="pr-6">
      {/* 1. Header */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-xl font-semibold">{f.name || f.instance_id}</h2>
        <StatusBadge status={f.status} />
      </div>
      <p className="mt-1 font-mono text-xs text-muted-foreground">{f.instance_id} · {f.region} · {f.instance_type} · {f.state}</p>
      <div className="mt-3"><ConfidenceBar score={f.confidence.score} band={f.confidence.band} /></div>
      {Object.keys(f.tags).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {Object.entries(f.tags).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
            <Badge key={k} className={isProtective(k, v) ? 'border-warning/50 bg-warning/10 text-warning' : 'bg-muted'}>
              {isProtective(k, v) && <ShieldCheck aria-label="protective tag" />}{k}={v}
            </Badge>
          ))}
        </div>
      )}

      {/* 2. Recommendation */}
      {s && (
        <div className="mt-5 rounded-lg border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-semibold">{s.headline}</p>
              <p className="mt-1 text-sm text-muted-foreground">{s.rationale}</p>
            </div>
            <RiskChip risk={s.risk} />
          </div>
          {s.action !== 'NONE' && (
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div><dt className="text-xs text-muted-foreground">Change</dt><dd className="font-mono">{s.from_type}{s.to_type && s.action === 'RESIZE' ? ` → ${s.to_type}` : ''}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Cost now</dt><dd>{money(s.current_hourly_usd != null ? s.current_hourly_usd * 730 : null)}/mo</dd></div>
              <div><dt className="text-xs text-muted-foreground">Est. change</dt><dd><MonthlyDelta delta={s.monthly_delta_usd} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">Downtime</dt><dd>{s.downtime_estimate ?? '—'}</dd></div>
            </dl>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {s.action !== 'NONE' && <ApplyButton finding={f} onApply={onApply} size="default" />}
            {s.alternative_actions.map((alt) => (
              <ApplyButton key={alt} finding={f} action={alt} onApply={onApply} size="default" variant="outline" label={`Alternative: ${ACTION_SHORT[alt]}`} />
            ))}
            <DismissButton f={f} />
          </div>
        </div>
      )}

      {/* 3. Explainability */}
      <Section title="Why we think so">
        <div className="grid gap-3 sm:grid-cols-3">
          <ScoreGauge label="Idle" score={f.idle?.score} threshold={th?.idle_threshold ?? 65} hit={(f.idle?.score ?? 0) >= (th?.idle_threshold ?? 65)} />
          <ScoreGauge label="Over-provisioned" score={overScore} threshold={th?.over_threshold ?? 60} hit={(overScore ?? 0) >= (th?.over_threshold ?? 60)} />
          <ScoreGauge label="Under-provisioned" score={f.underprovisioned?.score} threshold={th?.under_threshold ?? 70} hit={(f.underprovisioned?.score ?? 0) >= (th?.under_threshold ?? 70)} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Tile label="CPU p95" value={pct(f.metrics?.cpu_p95_pct, 2)} />
          <Tile label="CPU p99 of max" value={pct(f.metrics?.cpu_p99_max_pct, 2)} />
          <Tile label="Network p95" value={`${num(f.metrics?.net_p95_mb_per_hour)} MB/h`} />
          <Tile label="EBS p95" value={`${num(f.metrics?.ebs_p95_mb_per_hour)} MB/h`} />
          <Tile label="Data quality" value={f.data_quality != null ? `${Math.round(f.data_quality * 100)} %` : '—'} />
          <Tile label="Hours analysed" value={String(f.hours_analyzed)} />
        </div>
        <p className="mt-3 rounded-md bg-muted p-3 font-mono text-xs">{f.reason}</p>
        {blocked.length > 0 && (
          <div className="mt-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
            <p className="flex items-center gap-2 font-medium"><ShieldCheck className="size-4" aria-hidden="true" />Not declared idle because of:</p>
            <ul className="mt-1 list-disc pl-5">{blocked.map((b) => <li key={b}>{b}</li>)}</ul>
          </div>
        )}
        {!f.has_memory_metric && f.status !== 'STOPPED' && (
          <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <Badge className="border-warning/50 bg-warning/10 text-warning"><AlertTriangle aria-hidden="true" />Memory not monitored – lower confidence</Badge>
            <Link to="/help/cloudwatch-agent" className="inline-flex items-center gap-1 text-primary hover:underline">How to install the CloudWatch agent<ExternalLink className="size-3" aria-hidden="true" /></Link>
          </p>
        )}
        <h4 className="mt-5 mb-2 text-xs font-semibold text-muted-foreground uppercase">Pipeline evidence steps</h4>
        <EvidenceTable steps={f.evidence_steps} />
      </Section>

      {/* 4. Charts */}
      {series.length > 0 && (
        <Section title={`Hourly metrics (${f.hours_analyzed} h analysed)`}>
          <div className="grid gap-3 lg:grid-cols-2">
            <MetricChart title="CPU %" unit="%" data={series}
              series={[{ key: 'cpu_avg', label: 'CPU avg', color: 'var(--chart-1)' }, { key: 'cpu_max', label: 'CPU max', color: 'var(--chart-4)' }]}
              refs={f.status === 'UNDER_PROVISIONED' ? [{ y: 80, label: '80 %' }] : [{ y: 5, label: '5 %' }, { y: 10, label: '10 %' }]} />
            <MetricChart title="Network MB/h (in + out)" unit="MB" data={series} series={[{ key: 'net_mb', label: 'Network', color: 'var(--chart-1)' }]} />
            <MetricChart title="EBS MB/h (read + write)" unit="MB" data={series} series={[{ key: 'ebs_mb', label: 'EBS', color: 'var(--chart-3)' }]} />
            {f.mem_hourly.length > 0 && (
              <MetricChart title="Memory used %" unit="%" data={series} series={[{ key: 'mem_pct', label: 'Memory', color: 'var(--chart-2)' }]} />
            )}
          </div>
        </Section>
      )}

      {/* 5. History */}
      <Section title="Action history for this instance">
        {f.actions.length === 0 ? <p className="text-sm text-muted-foreground">No actions yet.</p> : (
          <ul className="space-y-2 text-sm">
            {f.actions.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-card px-3 py-2">
                <span>{ACTION_LABEL[a.action]}{a.before.instance_type && a.after.instance_type && a.before.instance_type !== a.after.instance_type ? ` (${a.before.instance_type} → ${a.after.instance_type})` : ''}</span>
                <span className="text-xs text-muted-foreground">{a.status.replace('_', ' ')} · {dateTime(a.completed_at ?? a.requested_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}

function DismissButton({ f }: { f: FindingDetail }) {
  const dismiss = useDismiss()
  const undismiss = useUndismiss()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  if (f.dismissed) {
    return <Button variant="ghost" onClick={() => undismiss.mutate(f.id, { onSuccess: () => toast.success('Restored') })}>Restore recommendation</Button>
  }
  const in30 = new Date(Date.now() + 30 * 86400_000).toISOString().slice(0, 10)
  const go = (b: { forever?: boolean; until?: string }) => dismiss.mutate({ id: f.id, reason: reason || undefined, ...b }, {
    onSuccess: () => { toast.success('Recommendation dismissed'); setOpen(false) },
    onError: (e) => toast.error(e.message),
  })
  return (
    <>
      <Button variant="ghost" onClick={() => setOpen(true)}><BellOff />Dismiss</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Keep as is?" description="The recommendation is hidden from the list and its saving is excluded from the dashboard.">
          <div className="space-y-2">
            <Label htmlFor="dismiss-reason">Reason (optional)</Label>
            <Input id="dismiss-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. needed for quarterly batch" />
          </div>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={() => go({ until: in30 })}>Snooze 30 days</Button>
            <Button onClick={() => go({ forever: true })}>Dismiss forever</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
