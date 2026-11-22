import { ChevronLeft, ChevronRight, Cloud, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useFindings, type FindingFilters } from '@/api/hooks'
import { RunScanButton } from '@/components/AppShell'
import { ApplyButton } from '@/components/ApplyButton'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { ConfirmActionModal } from '@/components/ConfirmActionModal'
import { FindingDrawer } from '@/components/FindingDrawer'
import { MonthlyDelta, RiskChip } from '@/components/Money'
import { EmptyState, ErrorState, EstimateFootnote, PageHeader, TableSkeleton } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input, Select } from '@/components/ui/input'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { money, STATUS_LABEL } from '@/lib/format'
import type { ActionCode, Finding, FindingStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

const ALL_STATUSES: FindingStatus[] = ['IDLE', 'NEEDS_REVIEW', 'OVER_PROVISIONED', 'UNDER_PROVISIONED', 'ACTIVE', 'STOPPED', 'INSUFFICIENT_DATA', 'ERROR']
const SUMMARY: FindingStatus[] = ['IDLE', 'OVER_PROVISIONED', 'UNDER_PROVISIONED', 'NEEDS_REVIEW']
const PAGE_SIZE = 25

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v]
}

export default function Recommendations() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { connectionId, current, isLoading: connLoading } = useConnectionCtx()
  const [status, setStatus] = useState<FindingStatus[]>(() => {
    const s = new URLSearchParams(window.location.search).get('status')
    return s ? (s.split(',') as FindingStatus[]) : []
  })
  const [region, setRegion] = useState<string[]>([])
  const [band, setBand] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('severity')
  const [dismissed, setDismissed] = useState(false)
  const [page, setPage] = useState(1)
  const [applying, setApplying] = useState<{ finding: Finding; action: ActionCode } | null>(null)

  const filters: FindingFilters = useMemo(() => ({
    status, region, band: band ? [band] : [], q: q.trim() || undefined, sort, only_dismissed: dismissed || undefined,
    page, page_size: PAGE_SIZE,
  }), [status, region, band, q, sort, dismissed, page])
  const { data, error, isLoading, refetch } = useFindings(connectionId, filters)
  const reset = (fn: () => void) => { fn(); setPage(1) }

  if (!connLoading && !current) {
    return <EmptyState icon={<Cloud className="size-8" />} title="Connect your AWS account" body="Recommendations appear after the first scan."
      action={<Button asChild><Link to="/connect">Connect AWS</Link></Button>} />
  }
  const counts = data?.summary.counts ?? {}
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div>
      <PageHeader title="Recommendations" description="Sorted by severity, then confidence." actions={<RunScanButton size="default" />} />

      {/* Summary strip = quick filters */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {SUMMARY.map((s) => (
          <button key={s} type="button" aria-pressed={status.length === 1 && status[0] === s}
            onClick={() => reset(() => setStatus(status.length === 1 && status[0] === s ? [] : [s]))}
            className={cn('rounded-lg border bg-card p-3 text-left transition cursor-pointer hover:border-primary/50', status.length === 1 && status[0] === s && 'border-primary ring-2 ring-primary/20')}>
            <StatusBadge status={s} />
            <p className="mt-2 text-2xl font-semibold tabular-nums">{counts[s] ?? 0}</p>
          </button>
        ))}
        <div className="col-span-2 rounded-lg border bg-card p-3 sm:col-span-1">
          <p className="text-xs text-muted-foreground">Potential savings</p>
          <p className="mt-2 text-2xl font-semibold text-success tabular-nums">{money(data?.summary.potential_monthly_saving ?? 0, { whole: true })}<span className="text-sm font-normal text-muted-foreground">/mo</span></p>
        </div>
      </div>

      {/* Toolbar */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border bg-card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search name, ID or type" placeholder="Search name, instance ID, type…" className="pl-8" value={q} onChange={(e) => reset(() => setQ(e.target.value))} />
          </div>
          <Select aria-label="Confidence band" value={band} onChange={(e) => reset(() => setBand(e.target.value))}>
            <option value="">Any confidence</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => reset(() => setSort(e.target.value))}>
            <option value="severity">Severity</option><option value="saving">Saving</option><option value="confidence">Confidence</option><option value="name">Name</option>
          </Select>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={dismissed} onCheckedChange={(v) => reset(() => setDismissed(v === true))} />Show dismissed ({data?.summary.dismissed ?? 0})</label>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
          {ALL_STATUSES.map((s) => (
            <button key={s} type="button" aria-pressed={status.includes(s)} onClick={() => reset(() => setStatus(toggle(status, s)))}
              className={cn('rounded-full border px-2.5 py-0.5 text-xs cursor-pointer', status.includes(s) ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted')}>
              {STATUS_LABEL[s]}
            </button>
          ))}
          {(data?.summary.regions.length ?? 0) > 1 && <span className="mx-1 w-px bg-border" aria-hidden="true" />}
          {(data?.summary.regions.length ?? 0) > 1 && data?.summary.regions.map((r) => (
            <button key={r} type="button" aria-pressed={region.includes(r)} onClick={() => reset(() => setRegion(toggle(region, r)))}
              className={cn('rounded-full border px-2.5 py-0.5 font-mono text-xs cursor-pointer', region.includes(r) ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted')}>
              {r}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={() => refetch()} /> : !data || data.items.length === 0 ? (
        <EmptyState title={data && data.total === 0 && !status.length && !q && !dismissed ? 'No findings yet' : 'Nothing matches these filters'}
          body={data && data.total === 0 && !status.length && !q ? 'Run a scan to analyse your instances.' : 'Try clearing a filter.'} />
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto rounded-lg border bg-card md:block">
            <table className="w-full text-sm">
              <caption className="sr-only">Recommendations</caption>
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  {['Instance', 'Region', 'Type', 'Status', 'Confidence', 'Suggestion', 'Est. $/month', 'Risk', ''].map((h, i) => (
                    <th key={i} scope="col" className="px-3 py-2 font-medium">{h || <span className="sr-only">Action</span>}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((f) => (
                  <tr key={f.id} tabIndex={0} onClick={() => navigate(`/recommendations/${f.id}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/recommendations/${f.id}`) }}
                    className="cursor-pointer border-t hover:bg-muted/40 focus:bg-muted/40">
                    <td className="px-3 py-2.5"><p className="font-medium">{f.name || '(no name)'}</p><p className="font-mono text-xs text-muted-foreground">{f.instance_id}</p></td>
                    <td className="px-3 py-2.5 font-mono text-xs">{f.region}</td>
                    <td className="px-3 py-2.5 font-mono text-xs">{f.instance_type}</td>
                    <td className="px-3 py-2.5"><StatusBadge status={f.status} /></td>
                    <td className="px-3 py-2.5"><ConfidenceBar score={f.confidence.score} band={f.confidence.band} /></td>
                    <td className="max-w-[16rem] px-3 py-2.5"><p className="truncate" title={f.reason}>{f.suggestion?.headline}</p>
                      {f.action_state !== 'none' && <p className="text-xs text-muted-foreground">action {f.action_state.replace('_', ' ')}</p>}</td>
                    <td className="px-3 py-2.5"><MonthlyDelta delta={f.monthly_delta_usd} /></td>
                    <td className="px-3 py-2.5"><RiskChip risk={f.suggestion?.risk} /></td>
                    <td className="px-3 py-2.5 text-right">
                      {f.suggestion?.action && f.suggestion.action !== 'NONE'
                        ? <ApplyButton finding={f} onApply={(a) => setApplying({ finding: f, action: a })} />
                        : <Button size="sm" variant="ghost">{f.status === 'NEEDS_REVIEW' ? 'Review' : 'Details'}</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Mobile cards */}
          <ul className="space-y-3 md:hidden">
            {data.items.map((f) => (
              <li key={f.id}>
                <button type="button" onClick={() => navigate(`/recommendations/${f.id}`)} className="w-full rounded-lg border bg-card p-4 text-left">
                  <div className="flex items-start justify-between gap-2">
                    <div><p className="font-medium">{f.name || f.instance_id}</p><p className="font-mono text-xs text-muted-foreground">{f.instance_type} · {f.region}</p></div>
                    <StatusBadge status={f.status} />
                  </div>
                  <p className="mt-2 text-sm">{f.suggestion?.headline}</p>
                  <div className="mt-2 flex items-center justify-between"><ConfidenceBar score={f.confidence.score} band={f.confidence.band} /><MonthlyDelta delta={f.monthly_delta_usd} /></div>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
            <span>{data.total} instance{data.total === 1 ? '' : 's'}</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft /></Button>
              <span>Page {page} of {pages}</span>
              <Button variant="outline" size="icon" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight /></Button>
            </div>
          </div>
        </>
      )}
      <EstimateFootnote />
      <FindingDrawer findingId={id ?? null} onClose={() => navigate('/recommendations')} />
      {applying && <ConfirmActionModal findingId={applying.finding.id} action={applying.action} onClose={() => setApplying(null)} />}
    </div>
  )
}
