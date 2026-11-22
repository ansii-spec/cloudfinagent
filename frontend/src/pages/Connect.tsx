import { Check, CheckCircle2, Copy, ExternalLink, Info, Loader2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import {
  useConnection, useCreateConnection, useCreateDemoConnection, usePublicConfig, useRegions, useStartScan,
  useUpdateConnection, useVerifyConnection,
} from '@/api/hooks'
import { SecurityFlowDiagram } from '@/components/SecurityFlowDiagram'
import { ErrorState, PageHeader } from '@/components/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { FieldError, Input, Label } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tip } from '@/components/ui/tooltip'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import type { Connection, VerifyCheck, WizardPayload } from '@/lib/types'
import { cn, copyText } from '@/lib/utils'

const ARN_RE = /^arn:aws:iam::\d{12}:role\/[\w+=,.@/-]+$/
const STEPS = ['Access level', 'Create the role', 'Verify']

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-2 text-sm" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2" aria-current={i === step ? 'step' : undefined}>
          <span className={cn('flex size-6 items-center justify-center rounded-full border text-xs font-semibold',
            i < step && 'border-primary bg-primary text-primary-foreground', i === step && 'border-primary text-primary')}>
            {i < step ? <Check className="size-3.5" aria-label="done" /> : i + 1}
          </span>
          <span className={i === step ? 'font-medium' : 'text-muted-foreground'}>{s}</span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-border" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  )
}

function CopyField({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const [done, setDone] = useState(false)
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="flex items-center gap-2 rounded-md border bg-muted px-3 py-2">
        <span className={cn('min-w-0 flex-1 truncate text-sm', mono && 'font-mono')}>{value}</span>
        <Button variant="ghost" size="icon" className="size-7" aria-label={`Copy ${label}`}
          onClick={() => copyText(value).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })}>
          {done ? <Check /> : <Copy />}
        </Button>
      </div>
    </div>
  )
}

export default function Connect() {
  const [params, setParams] = useSearchParams()
  const id = params.get('id')
  const conn = useConnection(id)
  if (!id) return <StepAccess onCreated={(cid) => setParams({ id: cid })} />
  if (conn.isLoading) return <Skeleton className="h-96" />
  if (conn.error || !conn.data) return <ErrorState error={conn.error} onRetry={() => conn.refetch()} />
  const c = conn.data
  const needsRole = c.status !== 'connected' || (c.enable_actions && !c.actions_verified)
  return needsRole && c.wizard ? <StepRole conn={c} wizard={c.wizard} /> : <StepDone conn={c} />
}

function StepAccess({ onCreated }: { onCreated: (id: string) => void }) {
  const { data: cfg } = usePublicConfig()
  const create = useCreateConnection()
  const demo = useCreateDemoConnection()
  const { setConnectionId } = useConnectionCtx()
  const navigate = useNavigate()
  const [actions, setActions] = useState(false)
  const [label, setLabel] = useState('Production')
  const cards = [
    { value: false, title: 'Read-only (analysis)', badge: 'Recommended to start',
      body: 'We can read EC2 and CloudWatch data and show recommendations. Nothing in your account can be changed.' },
    { value: true, title: 'Read + Actions (one-click fixes)', badge: null,
      body: 'Also allows stop / start / resize / terminate and credit changes — only when you click Apply and confirm.' },
  ]
  return (
    <div className="max-w-4xl">
      <PageHeader title="Connect your AWS account" description="Access uses an IAM role in your account. No access keys are shared." />
      <Stepper step={0} />
      <div className="grid gap-4 md:grid-cols-2" role="radiogroup" aria-label="Access level">
        {cards.map((c) => (
          <button key={c.title} type="button" role="radio" aria-checked={actions === c.value} onClick={() => setActions(c.value)}
            className={cn('rounded-lg border bg-card p-5 text-left transition cursor-pointer', actions === c.value ? 'border-primary ring-2 ring-primary/30' : 'hover:border-muted-foreground/40')}>
            <span className="font-bold">{c.title}</span>
            {c.badge && <span className="mt-2 inline-block rounded bg-accent px-2 py-0.5 text-xs text-accent-foreground">{c.badge}</span>}
            <p className="mt-2 text-sm text-muted-foreground">{c.body}</p>
          </button>
        ))}
      </div>
      <div className="mt-5 max-w-sm space-y-1.5">
        <Label htmlFor="label">Connection name</Label>
        <Input id="label" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={100} />
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <Button disabled={create.isPending} onClick={() => create.mutate({ label: label || 'AWS account', enable_actions: actions }, {
          onSuccess: (w) => onCreated(w.id), onError: (e) => toast.error(e.message),
        })}>{create.isPending && <Loader2 className="animate-spin" />}Continue</Button>
        {cfg?.demo_mode && (
          <Button variant="outline" disabled={demo.isPending} onClick={() => demo.mutate(undefined, {
            onSuccess: (c) => { setConnectionId(c.id); toast.success('Demo account connected — first scan running'); navigate('/recommendations') },
            onError: (e) => toast.error(e.message),
          })}>Use demo account</Button>
        )}
      </div>
      <p className="mt-8 text-xs text-muted-foreground">You can revoke access any time by deleting the CloudFormation stack.</p>
    </div>
  )
}

function PolicyBlock({ title, doc }: { title: string; doc: object }) {
  const text = JSON.stringify(doc, null, 2)
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-sm font-medium">{title}</p>
        <Button variant="ghost" size="sm" onClick={() => copyText(text).then(() => toast.success('Copied'))}><Copy />Copy</Button>
      </div>
      <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">{text}</pre>
    </div>
  )
}

function StepRole({ conn, wizard }: { conn: Connection; wizard: WizardPayload }) {
  const verify = useVerifyConnection(conn.id)
  const [arn, setArn] = useState(conn.role_arn ?? '')
  const [checks, setChecks] = useState<VerifyCheck[] | null>(null)
  const arnErr = arn && !ARN_RE.test(arn.trim()) ? 'Expected arn:aws:iam::<12-digit account>:role/<name>' : undefined
  const perms = wizard.enable_actions ? [...wizard.permissions.read_only, ...wizard.permissions.actions] : wizard.permissions.read_only
  const upgrading = conn.status === 'connected'
  return (
    <div className="max-w-4xl">
      <PageHeader title={upgrading ? 'Enable one-click actions' : 'Create the access role'}
        description={upgrading ? 'Update your CloudFormation stack with EnableActions=true, then re-verify.' : `Connection: ${conn.label}`} />
      <Stepper step={1} />
      <Card className="mb-5">
        <CardHeader><CardTitle>How secure access works</CardTitle><CardDescription>We never ask for or store AWS access keys.</CardDescription></CardHeader>
        <CardContent><SecurityFlowDiagram /></CardContent>
      </Card>
      <div className="mb-5 grid gap-4 sm:grid-cols-2">
        <CopyField label="Platform AWS account ID" value={wizard.platform_account_id} />
        <div className="space-y-1">
          <div className="flex items-center gap-1">
            <CopyField label="Your External ID" value={wizard.external_id} />
          </div>
          <Tip content="The External ID proves the request is for YOUR connection. It stops another customer from tricking us into using your role (the 'confused deputy' problem). It is not a password.">
            <button type="button" className="inline-flex items-center gap-1 text-xs text-primary cursor-pointer"><Info className="size-3" aria-hidden="true" />Why an External ID?</button>
          </Tip>
        </div>
      </div>
      <Tabs defaultValue="oneclick">
        <TabsList><TabsTrigger value="oneclick">One-click (CloudFormation)</TabsTrigger><TabsTrigger value="manual">Manual</TabsTrigger></TabsList>
        <TabsContent value="oneclick">
          <Card><CardContent className="space-y-3 pt-5 text-sm">
            <ol className="list-decimal space-y-1 pl-5">
              <li>Open the stack in the AWS console (all parameters are pre-filled).</li>
              <li>Tick "I acknowledge that AWS CloudFormation might create IAM resources" and click <strong>{upgrading ? 'Update stack' : 'Create stack'}</strong>.</li>
              <li>When it finishes, copy the <strong>RoleArn</strong> from the stack's <em>Outputs</em> tab and paste it below.</li>
            </ol>
            {upgrading && <p className="text-muted-foreground">Already have the stack? Use <em>Update stack → Replace current template</em> and set EnableActions to <code>true</code>.</p>}
            <Button asChild><a href={wizard.cloudformation_quick_create_url} target="_blank" rel="noreferrer"><ExternalLink />Launch CloudFormation stack</a></Button>
          </CardContent></Card>
        </TabsContent>
        <TabsContent value="manual">
          <Card><CardContent className="space-y-4 pt-5 text-sm">
            <ol className="list-decimal space-y-1 pl-5">
              <li>IAM console → Roles → Create role → <em>Custom trust policy</em> → paste the trust policy.</li>
              <li>Name the role <code className="rounded bg-muted px-1">{wizard.role_name}</code>.</li>
              <li>Add an inline policy with the permissions JSON below, then create the role and copy its ARN.</li>
            </ol>
            <PolicyBlock title="Trust policy" doc={wizard.manual_trust_policy_json} />
            <PolicyBlock title="Permissions policy" doc={wizard.manual_permissions_policy_json} />
          </CardContent></Card>
        </TabsContent>
      </Tabs>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-muted-foreground">Exactly which permissions are granted ({perms.length})</summary>
        <ul className="mt-2 grid gap-1 font-mono text-xs sm:grid-cols-2">{perms.map((p) => <li key={p}>{p}</li>)}</ul>
      </details>

      <Card className="mt-6">
        <CardHeader><CardTitle>Step 3 · Verify</CardTitle><CardDescription>We call STS AssumeRole with your External ID and probe the permissions.</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="arn">Role ARN</Label>
          <Input id="arn" placeholder="arn:aws:iam::123456789012:role/EC2OptimizerAccessRole" value={arn} onChange={(e) => setArn(e.target.value)} aria-invalid={!!arnErr} className="font-mono" />
          <FieldError>{arnErr}</FieldError>
          <FieldError>{verify.error?.message}</FieldError>
          <Button disabled={!ARN_RE.test(arn.trim()) || verify.isPending} onClick={() => verify.mutate(arn.trim(), {
            onSuccess: (r) => { setChecks(r.checks); if (r.status === 'connected') toast.success('Connection verified') },
          })}>{verify.isPending && <Loader2 className="animate-spin" />}Verify connection</Button>
          {checks && <Checklist checks={checks} />}
        </CardContent>
      </Card>
      <p className="mt-8 text-xs text-muted-foreground">You can revoke access any time by deleting the CloudFormation stack.</p>
    </div>
  )
}

function Checklist({ checks }: { checks: VerifyCheck[] }) {
  return (
    <ul className="space-y-1.5 text-sm" aria-label="Verification results">
      {checks.map((c) => (
        <li key={c.name} className="flex items-start gap-2">
          {c.ok ? <CheckCircle2 className="mt-0.5 size-4 text-success" aria-label="passed" /> : <XCircle className="mt-0.5 size-4 text-destructive" aria-label="failed" />}
          <span><strong>{c.name}</strong>{c.message && <span className="text-muted-foreground"> — {c.message}</span>}</span>
        </li>
      ))}
    </ul>
  )
}

function StepDone({ conn }: { conn: Connection }) {
  const regions = useRegions(conn.id)
  const update = useUpdateConnection(conn.id)
  const scan = useStartScan(conn.id)
  const { setConnectionId } = useConnectionCtx()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<string[] | null>(null)
  const auto = (regions.data ?? []).filter((r) => r.instance_count > 0).map((r) => r.region)
  const sel = picked ?? (conn.regions.length ? conn.regions : auto)
  const toggle = (r: string) => setPicked(sel.includes(r) ? sel.filter((x) => x !== r) : [...sel, r])
  const run = async () => {
    try {
      await update.mutateAsync({ regions: sel })
      await scan.mutateAsync(sel)
      setConnectionId(conn.id)
      toast.success('Scan started')
      navigate('/recommendations')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not start the scan')
    }
  }
  return (
    <div className="max-w-3xl">
      <PageHeader title="Connected" />
      <Stepper step={3} />
      <Card>
        <CardContent className="space-y-4 pt-5">
          <p className="flex items-center gap-2 text-sm"><CheckCircle2 className="size-5 text-success" aria-hidden="true" />
            Connected to AWS account <strong className="font-mono">{conn.aws_account_id}</strong> ({conn.enable_actions && conn.actions_verified ? 'read + actions' : 'read-only'}).</p>
          <div>
            <p className="mb-2 text-sm font-medium">Regions to scan</p>
            {regions.isLoading ? <Skeleton className="h-24" /> : (
              <div className="grid gap-2 sm:grid-cols-3">
                {(regions.data ?? []).map((r) => (
                  <label key={r.region} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                    <Checkbox checked={sel.includes(r.region)} onCheckedChange={() => toggle(r.region)} />
                    <span className="font-mono">{r.region}</span><span className="ml-auto text-xs text-muted-foreground">{r.instance_count}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          <Button onClick={run} disabled={update.isPending || scan.isPending}>{(update.isPending || scan.isPending) && <Loader2 className="animate-spin" />}Run first scan</Button>
        </CardContent>
      </Card>
      <p className="mt-8 text-xs text-muted-foreground">You can revoke access any time by deleting the CloudFormation stack.</p>
    </div>
  )
}
