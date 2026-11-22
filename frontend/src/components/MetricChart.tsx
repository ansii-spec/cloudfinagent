import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export interface SeriesDef { key: string; label: string; color: string }
export interface RefLine { y: number; label: string }

const fmtTs = (ts: string) => new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

export function MetricChart({ title, data, series, unit, refs = [], height = 180 }: {
  title: string
  data: Record<string, string | number | null>[]
  series: SeriesDef[]
  unit: string
  refs?: RefLine[]
  height?: number
}) {
  return (
    <figure className="rounded-md border bg-card p-3">
      <figcaption className="mb-2 text-xs font-medium text-muted-foreground">{title}</figcaption>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No data</p>
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={fmtTs} minTickGap={40} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" width={48} />
              <Tooltip
                contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                labelFormatter={(l) => new Date(String(l)).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}
                formatter={(v) => [`${Number(v).toFixed(2)} ${unit}`]}
              />
              {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {refs.map((r) => (
                <ReferenceLine key={r.label} y={r.y} stroke="var(--muted-foreground)" strokeDasharray="4 4"
                  label={{ value: r.label, fontSize: 10, fill: 'var(--muted-foreground)', position: 'insideTopRight' }} />
              ))}
              {series.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  )
}
