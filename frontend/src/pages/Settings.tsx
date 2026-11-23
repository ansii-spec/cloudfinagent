import { ExternalLink, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import {
  useDeleteAccount, useDeleteConnection, useMe, usePublicConfig, useRegions, useUpdateAccount, useUpdateConnection,
} from '@/api/hooks'
import { PageHeader } from '@/components/States'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { FieldError, Input, Label, Select } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { dateTime } from '@/lib/format'
import type { AwsCleanup, Connection } from '@/lib/types'
import { cn } from '@/lib/utils'

export default function Settings() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'connections'
  return (
    <div>
      <PageHeader title="Settings" />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v })}>
        <TabsList>
          <TabsTrigger value="connections">Connections</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
          <TabsTrigger value="detection">How detection works</TabsTrigger>
        </TabsList>
        <TabsContent value="connections"><ConnectionsTab /></TabsContent>
        <TabsContent value="account"><AccountTab /></TabsContent>
        <TabsContent value="detection"><DetectionTab /></TabsContent>
      </Tabs>
    </div>
  )
}

const STATUS_CHIP: Record<string, string> = {
  connected: 'border-success/40 bg-success/10 text-success', pending: 'bg-muted',
  broken: 'border-destructive/40 bg-destructive/10 text-destructive', disconnected: 'bg-muted',
}

function ConnectionsTab() {
  const { connections } = useConnectionCtx()
  const [cleanup, setCleanup] = useState<AwsCleanup | null>(null)
  return (
    <div className="space-y-4">
      {connections.map((c) => <ConnectionCard key={c.id} c={c} onDisconnected={setCleanup} />)}
      <Dialog open={!!cleanup} onOpenChange={(o) => !o && setCleanup(null)}>
        <DialogContent title="One last step: remove access in AWS"
          description="The connection and all its data were deleted from EC2 Optimizer. The app only has read access, so it cannot delete the IAM role in your AWS account - delete its CloudFormation stack to finish.">
          {cleanup && (
            <div className="space-y-3 text-sm">
              <ol className="list-decimal space-y-1 pl-5">
                <li>Open CloudFormation (us-east-1) and select the stack <code className="rounded bg-muted px-1">{cleanup.stack_name}</code>.</li>
                <li>Click <strong>Delete</strong>. This removes the role <code className="rounded bg-muted px-1">{cleanup.role_name}</code> and all its permissions.</li>
              </ol>
              <p className="text-xs text-muted-foreground">New connections use their own role name, so reconnecting works even if you skip this.</p>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setCleanup(null)}>Done</Button>
                <Button asChild><a href={cleanup.console_url} target="_blank" rel="noreferrer"><ExternalLink />Open CloudFormation</a></Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <Button asChild variant="outline"><Link to="/connect"><Plus />Add AWS account</Link></Button>
    </div>
  )
}

function ConnectionCard({ c, onDisconnected }: { c: Connection; onDisconnected: (x: AwsCleanup | null) => void }) {
  const update = useUpdateConnection(c.id)
  const remove = useDeleteConnection()
  const navigate = useNavigate()
  const regions = useRegions(c.id, c.status === 'connected')
  const [confirm, setConfirm] = useState(false)
  const save = (b: Parameters<typeof update.mutate>[0], msg = 'Saved') =>
    update.mutate(b, { onSuccess: () => toast.success(msg), onError: (e) => toast.error(e.message) })
  const toggleRegion = (r: string) => save({ regions: c.regions.includes(r) ? c.regions.filter((x) => x !== r) : [...c.regions, r] })

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
        <div>
          <CardTitle className="flex items-center gap-2">{c.label}<Badge className={STATUS_CHIP[c.status]}>{c.status}</Badge></CardTitle>
          <CardDescription className="mt-1 font-mono">{c.aws_account_id ?? 'not verified'} · {c.role_arn ?? '—'}</CardDescription>
          {c.last_error && <p className="mt-1 text-xs text-destructive">{c.last_error}</p>}
          <p className="mt-1 text-xs text-muted-foreground">Last verified {dateTime(c.last_verified_at)}</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => navigate(`/connect?id=${c.id}`)}>{c.status === 'connected' ? 'Re-verify' : 'Continue setup'}</Button>
          <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setConfirm(true)}><Trash2 />Disconnect</Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <p className="text-sm font-medium">Access level</p>
          <div className="flex items-center gap-3 text-sm">
            <ShieldCheck className="size-4 text-primary" aria-hidden="true" />
            {c.enable_actions ? (c.actions_verified ? 'Read + Actions' : 'Actions requested — update the stack and re-verify') : 'Read-only'}
          </div>
          {c.enable_actions ? (
            <Button size="sm" variant="outline" onClick={() => save({ enable_actions: false }, 'Switched to read-only')}>Switch to read-only</Button>
          ) : (
            <Button size="sm" onClick={() => update.mutate({ enable_actions: true }, {
              onSuccess: () => { toast.success('Update your stack, then re-verify'); navigate(`/connect?id=${c.id}`) },
            })}>Enable actions</Button>
          )}
          <p className="text-xs text-muted-foreground">You can revoke access any time by deleting the CloudFormation stack.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`sched-${c.id}`}>Automatic scan</Label>
          <Select id={`sched-${c.id}`} value={c.scan_schedule} onChange={(e) => save({ scan_schedule: e.target.value as Connection['scan_schedule'] })}>
            <option value="daily">Daily</option><option value="weekly">Weekly (Mondays)</option><option value="off">Off</option>
          </Select>
        </div>
        {c.status === 'connected' && (
          <div className="md:col-span-2">
            <p className="mb-2 text-sm font-medium">Regions <span className="font-normal text-muted-foreground">(none selected = all regions with instances)</span></p>
            <div className="flex flex-wrap gap-2">
              {(regions.data ?? []).map((r) => (
                <label key={r.region} className={cn('flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs', c.regions.includes(r.region) && 'border-primary')}>
                  <Checkbox checked={c.regions.includes(r.region)} onCheckedChange={() => toggleRegion(r.region)} />
                  <span className="font-mono">{r.region}</span><span className="text-muted-foreground">{r.instance_count}</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </CardContent>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent title="Disconnect this AWS account?" description="This deletes the connection and all its scans, findings, action history and savings data. Your EC2 instances are not touched; afterwards you'll get a link to delete the access role from your AWS account.">
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(c.id, {
              onSuccess: (r) => { toast.success('Disconnected'); setConfirm(false); onDisconnected(r?.aws_cleanup ?? null) }, onError: (e) => toast.error(e.message),
            })}>Disconnect</Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function AccountTab() {
  const { data: me } = useMe()
  const update = useUpdateAccount()
  const del = useDeleteAccount()
  const navigate = useNavigate()
  const [name, setName] = useState(me?.name ?? '')
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [delOpen, setDelOpen] = useState(false)
  const [delPw, setDelPw] = useState('')
  return (
    <div className="grid max-w-3xl gap-4">
      <Card><CardHeader><CardTitle>Profile</CardTitle><CardDescription>{me?.email}</CardDescription></CardHeader>
        <CardContent className="flex items-end gap-2">
          <div className="flex-1 space-y-1"><Label htmlFor="name">Name</Label><Input id="name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <Button disabled={!name.trim()} onClick={() => update.mutate({ name }, { onSuccess: () => toast.success('Saved') })}>Save</Button>
        </CardContent></Card>
      <Card><CardHeader><CardTitle>Change password</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1"><Label htmlFor="cur">Current password</Label><Input id="cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="new">New password (10+ characters)</Label><Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></div>
          <FieldError>{update.error?.message}</FieldError>
          <Button disabled={!cur || next.length < 10 || update.isPending} onClick={() => update.mutate({ current_password: cur, new_password: next }, {
            onSuccess: () => { toast.success('Password changed'); setCur(''); setNext('') },
          })}>Change password</Button>
        </CardContent></Card>
      <Card className="border-destructive/40"><CardHeader><CardTitle>Delete account</CardTitle><CardDescription>Permanently deletes your account and all connections and data. Your AWS resources are not touched.</CardDescription></CardHeader>
        <CardContent><Button variant="destructive" onClick={() => setDelOpen(true)}><Trash2 />Delete account</Button></CardContent></Card>
      <Dialog open={delOpen} onOpenChange={setDelOpen}>
        <DialogContent title="Delete your account?" description="Enter your password to confirm. This cannot be undone.">
          <Input type="password" aria-label="Password" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
          <FieldError>{del.error?.message}</FieldError>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDelOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={!delPw || del.isPending} onClick={() => del.mutate(delPw, { onSuccess: () => navigate('/login') })}>
              {del.isPending && <Loader2 className="animate-spin" />}Delete forever</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function DetectionTab() {
  const { data } = usePublicConfig()
  const t = data?.thresholds
  if (!t) return null
  const rows: [string, string][] = [
    ['Idle score threshold', `${t.idle_threshold} / 100`],
    ['Over-provisioned score threshold', `${t.over_threshold} / 100`],
    ['Under-provisioned score threshold', `${t.under_threshold} / 100`],
    ['Idle: CPU p95 limit', `${t.cpu_p95_limit_pct} %`],
    ['Idle: p99 of CPU maximum limit', `${t.cpu_p99_max_limit_pct} %`],
    ['Idle: network p95 limit', `${t.net_p95_mb_per_hour} MB/h`],
    ['Idle: EBS p95 limit', `${t.ebs_p95_mb_per_hour} MB/h`],
    ['Idle score weights', Object.entries(t.idle_weights).map(([k, v]) => `${k} ${v}`).join(' · ')],
    ['Under-provisioned: CPU p99 limit', `${t.under_cpu_p99_limit_pct} %`],
    ['Under-provisioned: CPU credits starved below', String(t.credit_starved_below)],
    ['Right-sizing headroom', `${t.headroom_pct} %`],
    ['Lookback window', `${t.lookback_hours} h`],
    ['Minimum history', `${t.min_history_hours} h`],
    ['Data quality applied to scores', t.apply_data_quality ? 'yes' : 'no'],
  ]
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Thresholds (read-only)</CardTitle><CardDescription>Fixed in the detection pipeline; not editable from the UI.</CardDescription></CardHeader>
        <CardContent><table className="w-full text-sm"><tbody>
          {rows.map(([k, v]) => <tr key={k} className="border-t"><th scope="row" className="py-1.5 pr-4 text-left font-normal text-muted-foreground">{k}</th><td className="font-mono text-xs">{v}</td></tr>)}
        </tbody></table></CardContent></Card>
      <Card><CardHeader><CardTitle>In plain English</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p><strong>Idle:</strong> CPU, network and disk all sit far below their limits (measured on a log scale, so 10× below counts much more than just under). The weakest "is it doing work" signal must also be idle. Instances with sensitive tags (e.g. <em>{t.protect_substrings.slice(0, 4).join(', ')}</em>), steady network traffic or heavy disk use are never called idle — they become <em>Needs review</em>.</p>
          <p><strong>Over-provisioned:</strong> take the 99th percentile of the hourly CPU maximum, convert it to vCPUs, add {t.headroom_pct} % headroom. If that fits in half (or a quarter) of the current vCPUs, suggest one (or two) sizes down in the same family — but only if memory, network and disk also fit. Without the CloudWatch agent, memory can't be checked and confidence is halved.</p>
          <p><strong>Under-provisioned:</strong> CPU sits above {t.under_cpu_p99_limit_pct} % for a sustained share of the time, or a burstable (T-family) instance keeps running out of CPU credits.</p>
          <p>Order: Idle → Over-provisioned → Under-provisioned → Needs review → Active.</p>
          <Link to="/help/cloudwatch-agent" className="text-primary hover:underline">How to install the CloudWatch agent</Link>
        </CardContent></Card>
    </div>
  )
}
