import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, RotateCcw, Undo2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { useAction, useActionPreview, useApplyAction, useUndo } from '@/api/hooks'
import { MonthlyDelta } from '@/components/Money'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Input, Label } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ACTION_LABEL, money } from '@/lib/format'
import type { ActionCode, ActionPreview, RemediationAction, StepLog } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface ConfirmActionModalProps {
  findingId: string
  action: ActionCode | null
  onClose: () => void
}

export function ConfirmActionModal({ findingId, action, onClose }: ConfirmActionModalProps) {
  const [actionId, setActionId] = useState<string | null>(null)
  useEffect(() => { if (!action) setActionId(null) }, [action])
  return (
    <Dialog open={!!action} onOpenChange={(o) => { if (!o) onClose() }}>
      {action && (
        <DialogContent title={actionId ? 'Applying change' : `${ACTION_LABEL[action]}?`} className="max-w-xl">
          {actionId
            ? <ActionProgress actionId={actionId} onClose={onClose} onUndo={(id) => setActionId(id)} />
            : <PreviewStep findingId={findingId} action={action} onStarted={setActionId} onCancel={onClose} />}
        </DialogContent>
      )}
    </Dialog>
  )
}

function PreviewStep({ findingId, action, onStarted, onCancel }: {
  findingId: string; action: ActionCode; onStarted: (id: string) => void; onCancel: () => void
}) {
  const preview = useActionPreview(findingId, action)
  const apply = useApplyAction(findingId)
  const [understood, setUnderstood] = useState(false)
  const [typed, setTyped] = useState('')
  const [opts, setOpts] = useState<Record<string, boolean>>({})
  const [serverBlockers, setServerBlockers] = useState<string[]>([])

  useEffect(() => {
    if (preview.data) setOpts(Object.fromEntries(Object.entries(preview.data.options).map(([k, v]) => [k, v.default])))
  }, [preview.data])

  if (preview.isLoading) return <div className="space-y-3" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-24" /><Skeleton className="h-10" /></div>
  if (preview.error || !preview.data) {
    return <p role="alert" className="text-sm text-destructive">{preview.error?.message ?? 'Could not load the preview'}</p>
  }
  const p: ActionPreview = preview.data
  const blockers = [...p.blockers, ...serverBlockers]
  const typedOk = !p.requires_typed_confirmation || typed.trim() === p.instance.id
  const canConfirm = blockers.length === 0 && understood && typedOk && !apply.isPending

  const submit = () => apply.mutate(
    { action, options: opts, typed_confirmation: p.requires_typed_confirmation ? typed.trim() : undefined },
    {
      onSuccess: (r) => onStarted(r.action_id),
      onError: (e) => {
        if (e instanceof ApiError && e.blockers.length) setServerBlockers(e.blockers)
        else toast.error(e.message)
      },
    },
  )

  return (
    <div className="space-y-4 text-sm">
      <div className="rounded-md border bg-muted/50 p-3">
        <p className="font-medium">{p.instance.name || p.instance.id}</p>
        <p className="text-xs text-muted-foreground">{p.instance.id} · {p.instance.region}</p>
        <p className="mt-2"><span className="font-mono">{p.change.from}</span> → <span className="font-mono font-semibold">{p.change.to}</span></p>
      </div>

      <table className="w-full text-sm" aria-label="Cost impact">
        <tbody>
          <tr><th scope="row" className="py-1 text-left font-normal text-muted-foreground">Current (est.)</th><td className="text-right tabular-nums">{money(p.cost.current_monthly)}/mo</td></tr>
          <tr><th scope="row" className="py-1 text-left font-normal text-muted-foreground">After (est.)</th><td className="text-right tabular-nums">{money(p.cost.new_monthly)}/mo</td></tr>
          <tr className="border-t"><th scope="row" className="py-1 text-left font-medium">Change</th><td className="text-right"><MonthlyDelta delta={p.cost.monthly_delta} /></td></tr>
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">Downtime: {p.downtime}. {p.estimate_note}</p>

      {blockers.length > 0 && (
        <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3">
          <p className="mb-1 flex items-center gap-2 font-medium text-destructive"><CircleSlash className="size-4" aria-hidden="true" />Can't apply</p>
          <ul className="list-disc space-y-1 pl-5">{blockers.map((b) => <li key={b}>{b}</li>)}</ul>
        </div>
      )}
      {p.warnings.length > 0 && (
        <div className="rounded-md border border-warning/40 bg-warning/10 p-3">
          <p className="mb-1 flex items-center gap-2 font-medium text-warning"><AlertTriangle className="size-4" aria-hidden="true" />Please note</p>
          <ul className="list-disc space-y-1 pl-5">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}

      {Object.entries(p.options).map(([k, o]) => (
        <label key={k} className="flex items-center gap-2">
          <Checkbox checked={!!opts[k]} onCheckedChange={(v) => setOpts({ ...opts, [k]: v === true })} />{o.label}
        </label>
      ))}
      <p className="text-xs text-muted-foreground">Undo: {p.undo}</p>

      {p.requires_typed_confirmation && (
        <div className="space-y-1">
          <Label htmlFor="typed-id">Type <span className="font-mono">{p.instance.id}</span> to confirm termination</Label>
          <Input id="typed-id" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" aria-invalid={typed.length > 0 && !typedOk} />
        </div>
      )}
      <label className="flex items-center gap-2 font-medium">
        <Checkbox checked={understood} onCheckedChange={(v) => setUnderstood(v === true)} aria-label="I understand" />I understand the impact of this change
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
        <Button variant={action === 'TERMINATE_INSTANCE' ? 'destructive' : 'default'} disabled={!canConfirm} onClick={submit}>
          {apply.isPending && <Loader2 className="animate-spin" />}Confirm {ACTION_LABEL[action].toLowerCase()}
        </Button>
      </div>
    </div>
  )
}

function StepIcon({ s }: { s: StepLog['status'] }) {
  if (s === 'ok') return <CheckCircle2 className="size-4 text-success" aria-label="done" />
  if (s === 'error') return <XCircle className="size-4 text-destructive" aria-label="error" />
  if (s === 'warning') return <AlertTriangle className="size-4 text-warning" aria-label="warning" />
  return <Loader2 className="size-4 animate-spin text-primary" aria-label="in progress" />
}

/** Collapses "running" + "ok" entries of the same step into one line. */
function collapse(log: StepLog[]): StepLog[] {
  const out: StepLog[] = []
  for (const s of log) {
    const last = out[out.length - 1]
    if (last && last.step === s.step && last.status === 'running') out[out.length - 1] = s
    else out.push(s)
  }
  return out
}

export function ActionProgress({ actionId, onClose, onUndo }: { actionId: string; onClose: () => void; onUndo?: (id: string) => void }) {
  const { data: a } = useAction(actionId)
  const undo = useUndo()
  if (!a) return <Skeleton className="h-32" />
  const done = a.status !== 'pending' && a.status !== 'running'
  return (
    <div className="space-y-4 text-sm" aria-live="polite">
      <p className="text-muted-foreground">{ACTION_LABEL[a.action]} on <strong className="text-foreground">{a.instance_name || a.instance_id}</strong></p>
      <ol className="space-y-2">
        {a.status === 'pending' && <li className="flex items-center gap-2"><StepIcon s="running" />Queued…</li>}
        {collapse(a.steps_log).map((s, i) => (
          <li key={i} className="flex items-start gap-2"><StepIcon s={s.status} /><span>{s.step}{s.message && <span className="block text-xs text-muted-foreground">{s.message}</span>}</span></li>
        ))}
      </ol>
      {done && <FinalState a={a} />}
      <div className="flex justify-end gap-2">
        {done && a.can_undo && onUndo && (
          <Button variant="outline" disabled={undo.isPending} onClick={() => undo.mutate(a.id, {
            onSuccess: (r) => onUndo(r.action_id), onError: (e) => toast.error(e.message),
          })}><Undo2 />Undo</Button>
        )}
        <Button variant={done ? 'default' : 'outline'} onClick={onClose}>{done ? 'Close' : 'Run in background'}</Button>
      </div>
    </div>
  )
}

function FinalState({ a }: { a: RemediationAction }) {
  const map = {
    succeeded: { icon: CheckCircle2, cls: 'border-success/40 bg-success/10 text-success', text: 'Success' },
    failed: { icon: XCircle, cls: 'border-destructive/40 bg-destructive/10 text-destructive', text: 'Failed' },
    rolled_back: { icon: RotateCcw, cls: 'border-warning/40 bg-warning/10 text-warning', text: 'Rolled back' },
  } as const
  const s = map[a.status as keyof typeof map]
  if (!s) return null
  return (
    <div role="status" className={cn('rounded-md border p-3', s.cls)}>
      <p className="flex items-center gap-2 font-medium"><s.icon className="size-4" aria-hidden="true" />{s.text}</p>
      {a.error && <p className="mt-1 text-foreground">{a.error}</p>}
      {a.status === 'succeeded' && a.monthly_saving_usd != null && a.monthly_saving_usd !== 0 && (
        <p className="mt-1 text-foreground">Estimated {a.monthly_saving_usd > 0 ? 'saving' : 'extra cost'}: {money(Math.abs(a.monthly_saving_usd))}/mo</p>
      )}
    </div>
  )
}
