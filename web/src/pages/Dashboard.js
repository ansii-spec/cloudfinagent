import { useState } from 'react'
import { Link } from 'react-router'
import { ArrowRight, TrendingUp } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { cn } from 'cn'
import { Button } from '@/components/ui/button'
import { DataTable, PageHeader, SectionCard, StatCard, StatusBadge } from '@/components/common'
import { accounts, kpis, recentActions, savingsTrend, serviceBreakdown } from '@/mock/data'
import { formatUsd } from '@/lib/format'

const ranges = [30, 60, 90]

function SavingsTrend() {
  const [days, setDays] = useState(30)
  const data = savingsTrend.slice(-days)
  return (
    <SectionCard
      title="Savings trend"
      className="lg:col-span-3"
      actions={
        <div role="group" aria-label="Date range" className="inline-flex overflow-hidden rounded-md border">
          {ranges.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={days === r}
              onClick={() => setDays(r)}
              className={cn('border-l px-3 py-1 text-xs font-bold first:border-l-0', days === r ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}
            >
              {r}d
            </button>
          ))}
        </div>
      }
    >
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 12, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={{ stroke: 'var(--border)' }} minTickGap={24} />
            <YAxis tickFormatter={(v) => `$${v.toLocaleString()}`} tick={{ fontSize: 12, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} width={64} />
            <Tooltip formatter={(v) => formatUsd(v)} contentStyle={{ borderRadius: 6, borderColor: 'var(--border)', fontSize: 12 }} />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            <Line type="monotone" dataKey="realized" name="Realized" stroke="var(--chart-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="potential" name="Potential" stroke="var(--chart-2)" strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </SectionCard>
  )
}

export default function Dashboard() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Spend, savings and recent optimization activity."
        actions={
          <>
            <label htmlFor="account" className="sr-only">Account</label>
            <select id="account" className="h-8 rounded-md border border-input bg-card px-2 text-sm">
              <option>All accounts</option>
              {accounts.map((a) => <option key={a.id}>{a.name}</option>)}
            </select>
            <Button>Run analysis now</Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total monthly spend"
          value={formatUsd(kpis.totalSpend)}
          footer={<span className="inline-flex items-center gap-1"><TrendingUp className="size-3.5 text-destructive" aria-hidden="true" />{kpis.spendChangePct}% vs last month</span>}
        />
        <StatCard
          label="Potential monthly savings"
          value={formatUsd(kpis.potentialSavings)}
          footer={<Link to="/suggestions" className="inline-flex items-center gap-1 text-primary hover:underline">{kpis.openSuggestions} suggestions <ArrowRight className="size-3.5" aria-hidden="true" /></Link>}
        />
        <StatCard label="Realized savings (month)" value={formatUsd(kpis.realizedSavings)} footer={`from ${kpis.appliedActions} applied actions`} />
        <StatCard label="Optimization coverage" value={`${kpis.coveragePct}%`} footer="of resources analyzed & optimized" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <SavingsTrend />
        <SectionCard title="Service breakdown" className="lg:col-span-2" bodyClassName="p-0">
          <DataTable
            rowKey="service"
            rows={serviceBreakdown}
            columns={[
              { key: 'service', header: 'Service', render: (r) => <span className="font-bold">{r.service}</span> },
              { key: 'resources', header: 'Count', align: 'right' },
              { key: 'waste', header: 'Waste', wrap: true },
              { key: 'savings', header: 'Savings/mo', align: 'right', render: (r) => formatUsd(r.savings) },
            ]}
          />
        </SectionCard>
      </div>

      <SectionCard
        title="Recent actions"
        className="mt-4"
        bodyClassName="p-0"
        actions={<Link to="/actions" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">View all <ArrowRight className="size-3.5" aria-hidden="true" /></Link>}
      >
        <DataTable
          rowKey="id"
          rows={recentActions}
          columns={[
            { key: 'timestamp', header: 'Timestamp', render: (r) => <span className="tabular-nums">{r.timestamp}</span> },
            { key: 'resource', header: 'Resource', render: (r) => <span className="font-mono text-xs">{r.resource}</span> },
            { key: 'action', header: 'Action' },
            { key: 'savings', header: 'Savings/mo', align: 'right', render: (r) => formatUsd(r.savings) },
            { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      </SectionCard>
    </>
  )
}
