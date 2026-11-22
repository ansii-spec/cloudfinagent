import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { Fragment, useState } from 'react'
import { toast } from 'sonner'
import { useActions, useUndo } from '@/api/hooks'
import { ActionProgress } from '@/components/ConfirmActionModal'
import { EmptyState, ErrorState, EstimateFootnote, PageHeader, TableSkeleton } from '@/components/States'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { ACTION_LABEL, dateTime, money } from '@/lib/format'
import type { ActionStatus, RemediationAction } from '@/lib/types'
import { cn } from '@/lib/utils'

const STATUS_CLS: Record<ActionStatus, string> = {
  pending: 'bg-muted', running: 'border-info/40 bg-info/10 text-info',
  succeeded: 'border-success/40 bg-success/10 text-success', failed: 'border-destructive/40 bg-destructive/10 text-destructive',
  rolled_back: 'border-warning/40 bg-warning/10 text-warning',
}

function change(a: RemediationAction): string {
  if (a.before.instance_type && a.after.instance_type && a.before.instance_type !== a.after.instance_type) return `${a.before.instance_type} → ${a.after.instance_type}`
  if (a.action === 'RESIZE' && typeof a.options.target_type === 'string') return `${a.before.instance_type} → ${a.options.target_type}`
  if (a.before.state && a.after.state && a.before.state !== a.after.state) return `${a.before.state} → ${a.after.state}`
  return '—'
}

export default function Actions() {
  const { connectionId } = useConnectionCtx()
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<string | null>(null)
  const [watching, setWatching] = useState<string | null>(null)
  const { data, error, isLoading, refetch } = useActions(connectionId, page)
  const undo = useUndo()
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div>
      <PageHeader title="Actions" />
      {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={() => refetch()} /> : !data?.items.length ? (
        <EmptyState title="No actions yet" body="Apply a recommendation and it will show up here." />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <caption className="sr-only">Action history</caption>
            <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>{['', 'Time', 'Instance', 'Action', 'Change', 'Status', 'Saving/month', 'By', ''].map((h, i) => <th key={i} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <Fragment key={a.id}>
                  <tr className="border-t">
                    <td className="px-2"><Button variant="ghost" size="icon" className="size-7" aria-expanded={open === a.id} aria-label="Show steps" onClick={() => setOpen(open === a.id ? null : a.id)}>
                      <ChevronDown className={cn('transition', open === a.id && 'rotate-180')} /></Button></td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap">{dateTime(a.requested_at)}</td>
                    <td className="px-3 py-2"><p className="font-medium">{a.instance_name || a.instance_id}</p><p className="font-mono text-xs text-muted-foreground">{a.instance_id}</p></td>
                    <td className="px-3 py-2">{ACTION_LABEL[a.action]}</td>
                    <td className="px-3 py-2 font-mono text-xs">{change(a)}</td>
                    <td className="px-3 py-2"><Badge className={STATUS_CLS[a.status]}>{a.status.replace('_', ' ')}</Badge>{a.undone && <span className="ml-1 text-xs text-muted-foreground">undone</span>}</td>
                    <td className={cn('px-3 py-2 tabular-nums', (a.monthly_saving_usd ?? 0) > 0 ? 'text-success' : (a.monthly_saving_usd ?? 0) < 0 ? 'text-info' : '')}>
                      {a.monthly_saving_usd ? money(a.monthly_saving_usd) : '—'}{a.monthly_saving_usd && !a.savings_active ? <span className="block text-xs text-muted-foreground">not active</span> : null}</td>
                    <td className="px-3 py-2 text-xs">{a.performed_by ?? '—'}</td>
                    <td className="px-3 py-2 text-right">
                      {a.can_undo && <Button size="sm" variant="outline" disabled={undo.isPending} onClick={() => undo.mutate(a.id, {
                        onSuccess: (r) => { setWatching(r.action_id); refetch() }, onError: (e) => toast.error(e.message),
                      })}>Undo</Button>}
                    </td>
                  </tr>
                  {open === a.id && (
                    <tr className="bg-muted/30"><td colSpan={9} className="px-6 py-3">
                      {a.error && <p className="mb-2 text-sm text-destructive">{a.error}</p>}
                      {a.savings_end_reason && <p className="mb-2 text-xs text-muted-foreground">Savings ended: {a.savings_end_reason}</p>}
                      <ol className="space-y-1 text-xs">
                        {a.steps_log.map((s, i) => <li key={i}><span className="text-muted-foreground">{dateTime(s.ts)}</span> · <strong>{s.step}</strong> · {s.status}{s.message && ` — ${s.message}`}</li>)}
                        {a.steps_log.length === 0 && <li className="text-muted-foreground">No steps recorded.</li>}
                      </ol>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-end gap-2 border-t p-2 text-sm text-muted-foreground">
            <Button variant="outline" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft /></Button>
            Page {page} of {pages}
            <Button variant="outline" size="icon" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight /></Button>
          </div>
        </div>
      )}
      <EstimateFootnote />
      <Dialog open={!!watching} onOpenChange={(o) => { if (!o) setWatching(null) }}>
        {watching && <DialogContent title="Undoing change"><ActionProgress actionId={watching} onClose={() => setWatching(null)} /></DialogContent>}
      </Dialog>
    </div>
  )
}
