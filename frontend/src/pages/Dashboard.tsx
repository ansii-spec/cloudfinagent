import { ArrowRight, Cloud, Info, PiggyBank, Rocket, TrendingUp, Wallet } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useDashboard } from '@/api/hooks'
import { RunScanButton } from '@/components/AppShell'
import { EmptyState, ErrorState, EstimateFootnote, PageHeader } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tip } from '@/components/ui/tooltip'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { KIND_LABEL, money, relativeTime, shortDate } from '@/lib/format'
import type { DashboardSummary, FindingStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

// Fixed colour per entity from the console chart palette; colour follows the kind, never its rank.
const KIND_COLOR: Record<string, string> = { RESIZE_DOWN: 'var(--chart-1)', STOP: 'var(--chart-3)', TERMINATE: 'var(--chart-4)' }
const RANGES = [['30d', '30 days'], ['90d', '90 days'], ['12m', '12 months'], ['all', 'All']] as const
const TOOLTIP_STYLE = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--foreground)' }

function useCountUp(target: number, ms = 900): number {
  const [v, setV] = useState(0)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setV(target); return }
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms)
      setV(target * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

function Hero({ label, value, sub, icon: Icon, accent, children }: {
  label: string; value: number; sub?: React.ReactNode; icon: typeof Wallet; accent?: boolean; children?: React.ReactNode
}) {
  return (
    <Card className={cn(accent && 'border-primary/40')}>
      <CardContent className="pt-5">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Icon className="size-4" aria-hidden="true" />{label}</p>
        <p className={cn('mt-2 text-3xl font-semibold tabular-nums', accent && 'text-success')}>{money(value, { whole: true })}</p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
        {children}
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const { connectionId, current, isLoading: connLoading } = useConnectionCtx()
  const [range, setRange] = useState('90d')
  const { data, error, isLoading, refetch } = useDashboard(connectionId, range)
  const saved = useCountUp(data?.realized.cumulative ?? 0)

  if (!connLoading && !current) {
    return <EmptyState icon={<Cloud className="size-8" />} title="Connect your AWS account to start"
      body="We analyse EC2 and CloudWatch data with a read-only role — no access keys needed."
      action={<Button asChild><Link to="/connect">Connect AWS</Link></Button>} />
  }
  return (
    <div>
      <PageHeader title="Savings dashboard" description={`Last scan ${relativeTime(data?.last_scan_at)}`}
        actions={<>
          <div role="group" aria-label="Range" className="inline-flex rounded-md border bg-card p-0.5">
            {RANGES.map(([v, l]) => (
              <button key={v} type="button" aria-pressed={range === v} onClick={() => setRange(v)}
                className={cn('rounded px-2.5 py-1 text-xs cursor-pointer', range === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>{l}</button>
            ))}
          </div>
          <RunScanButton size="default" />
        </>} />
      {error ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading || !data ? <DashSkeleton /> : (
        <DashBody d={data} saved={saved} />
      )}
    </div>
  )
}

function DashSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32" />)}</div>
      <Skeleton className="h-72" />
    </div>
  )
}

function DashBody({ d, saved }: { d: DashboardSummary; saved: number }) {
  const [view, setView] = useState<'cumulative' | 'daily'>('cumulative')
  const noActions = d.actions.applied === 0
  const pctLess = d.spend.before_monthly > 0 ? Math.round((1 - d.spend.current_monthly / d.spend.before_monthly) * 100) : 0
  const pie = d.by_action.filter((x) => x.kind !== 'RESIZE_UP' && x.amount > 0)
  const pieTotal = pie.reduce((s, x) => s + x.amount, 0)
  const health: FindingStatus[] = ['IDLE', 'OVER_PROVISIONED', 'UNDER_PROVISIONED', 'NEEDS_REVIEW', 'ACTIVE', 'STOPPED', 'INSUFFICIENT_DATA', 'ERROR']

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Hero label="Saved so far" value={saved} icon={PiggyBank} accent sub={`${money(d.realized.this_month)} this month`} />
        <Hero label="Monthly run-rate" value={d.realized.monthly_run_rate} icon={TrendingUp} sub={`${d.actions.applied} applied · ${d.actions.undone} undone · ${d.actions.failed} failed`} />
        <Hero label="Potential savings" value={d.potential.monthly} icon={Wallet} sub="per month, open recommendations">
          <Button asChild size="sm" variant="outline" className="mt-3"><Link to="/recommendations">Review {d.potential.open_findings} recommendations<ArrowRight /></Link></Button>
        </Hero>
        <Card><CardContent className="pt-5">
          <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Rocket className="size-4" aria-hidden="true" />Invested in performance</p>
          <p className="mt-2 text-xl font-semibold tabular-nums text-info">{money(d.invested.monthly)}<span className="text-xs font-normal text-muted-foreground">/mo</span></p>
          <p className="mt-1 text-xs text-muted-foreground">Upsizes; not subtracted from savings.</p>
        </CardContent></Card>
      </div>

      {/* Before / after strip */}
      <Card><CardContent className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-5 text-sm">
        <span className="text-muted-foreground">Your EC2 spend estimate:</span>
        <span>before <strong className="tabular-nums">{money(d.spend.before_monthly, { whole: true })}/mo</strong></span>
        <ArrowRight className="size-4 text-muted-foreground" aria-hidden="true" />
        <span>now <strong className="tabular-nums">{money(d.spend.current_monthly, { whole: true })}/mo</strong></span>
        {pctLess > 0 && <span className="rounded bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">−{pctLess} %</span>}
        <Tip content="Σ hourly list price of running instances × 730. Before = now + realized run-rate − invested. Not your AWS bill.">
          <button type="button" aria-label="How this is calculated" className="ml-auto text-muted-foreground cursor-pointer"><Info className="size-4" /></button>
        </Tip>
      </CardContent></Card>

      {noActions && (
        <EmptyState icon={<PiggyBank className="size-8" />} title="Apply your first recommendation to start saving"
          body={<>You could save <strong className="text-success">{money(d.potential.monthly)}/mo</strong> right now.</>}
          action={<Button asChild><Link to="/recommendations">See recommendations</Link></Button>} />
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-start justify-between">
            <div><CardTitle>Savings over time</CardTitle><CardDescription>{view === 'cumulative' ? 'Cumulative realized savings (USD)' : 'Savings per day (USD)'}</CardDescription></div>
            <div role="group" aria-label="Chart view" className="inline-flex rounded-md border p-0.5">
              {(['cumulative', 'daily'] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                  className={cn('rounded px-2 py-0.5 text-xs capitalize cursor-pointer', view === v ? 'bg-muted font-medium' : 'text-muted-foreground')}>{v}</button>
              ))}
            </div>
          </CardHeader>
          <CardContent>
            {d.timeseries.length === 0 ? <p className="py-16 text-center text-sm text-muted-foreground">No realized savings yet</p> : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  {view === 'cumulative' ? (
                    <AreaChart data={d.timeseries} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => shortDate(v).replace(/, \d{4}$/, '')} minTickGap={40} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                      <YAxis tickFormatter={(v: number) => `$${v}`} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" width={56} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(l) => shortDate(String(l))} formatter={(v) => [money(Number(v)), 'Saved so far']} />
                      <Area type="monotone" dataKey="cumulative" stroke="var(--chart-1)" strokeWidth={2} fill="var(--chart-1)" fillOpacity={0.15} isAnimationActive={false} />
                    </AreaChart>
                  ) : (
                    <BarChart data={d.timeseries} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => shortDate(v).replace(/, \d{4}$/, '')} minTickGap={40} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                      <YAxis tickFormatter={(v: number) => `$${v}`} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" width={56} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--muted)' }} labelFormatter={(l) => shortDate(String(l))} formatter={(v) => [money(Number(v)), 'Saved that day']} />
                      <Bar dataKey="daily" fill="var(--chart-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  )}
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Savings by action type</CardTitle><CardDescription>Cumulative, all time</CardDescription></CardHeader>
          <CardContent>
            {pie.length === 0 ? <p className="py-16 text-center text-sm text-muted-foreground">No data yet</p> : (
              <>
                <div className="h-44">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pie} dataKey="amount" nameKey="kind" innerRadius="60%" outerRadius="90%" stroke="var(--card)" strokeWidth={2} isAnimationActive={false}>
                        {pie.map((x) => <Cell key={x.kind} fill={KIND_COLOR[x.kind]} />)}
                      </Pie>
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [money(Number(v)), KIND_LABEL[String(n)]]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="mt-3 space-y-1.5 text-sm" aria-label="Legend">
                  {pie.map((x) => (
                    <li key={x.kind} className="flex items-center gap-2">
                      <span className="size-2.5 rounded-sm" style={{ background: KIND_COLOR[x.kind] }} aria-hidden="true" />
                      <span>{KIND_LABEL[x.kind]}</span>
                      <span className="ml-auto tabular-nums">{money(x.amount, { whole: true })}</span>
                      <span className="w-10 text-right text-xs text-muted-foreground tabular-nums">{Math.round((x.amount / pieTotal) * 100)} %</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Top saved instances</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            {d.top_instances.length === 0 ? <p className="text-sm text-muted-foreground">Nothing yet.</p> : (
              <table className="w-full text-sm">
                <caption className="sr-only">Top saved instances</caption>
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th scope="col" className="py-2">Instance</th><th scope="col">Change</th><th scope="col">Since</th><th scope="col" className="text-right">Run-rate</th><th scope="col" className="text-right">Saved</th></tr>
                </thead>
                <tbody>
                  {d.top_instances.map((t) => (
                    <tr key={t.action_id} className="border-t">
                      <td className="py-2"><p className="font-medium">{t.name || t.instance_id}</p><p className="font-mono text-xs text-muted-foreground">{t.instance_id}</p></td>
                      <td className="font-mono text-xs">{t.kind === 'STOP' ? 'stopped' : t.kind === 'TERMINATE' ? 'terminated' : `${t.from} → ${t.to}`}</td>
                      <td className="text-xs">{shortDate(t.since)}{!t.active && <span className="block text-muted-foreground">ended</span>}</td>
                      <td className="text-right tabular-nums">{money(t.monthly_run_rate)}/mo</td>
                      <td className="text-right font-medium text-success tabular-nums">{money(t.cumulative)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Findings health</CardTitle><CardDescription>Latest scan · click to filter</CardDescription></CardHeader>
          <CardContent className="grid grid-cols-2 gap-2">
            {health.map((s) => (
              <Link key={s} to={`/recommendations?status=${s}`} className="rounded-md border p-2 hover:bg-muted">
                <StatusBadge status={s} className="max-w-full" />
                <p className="mt-1 text-lg font-semibold tabular-nums">{d.counts[s.toLowerCase()] ?? 0}</p>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>
      <EstimateFootnote />
    </div>
  )
}
