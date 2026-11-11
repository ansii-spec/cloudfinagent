import { cn } from 'cn'

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionCard({ title, actions, children, className, bodyClassName }) {
  return (
    <section className={cn('min-w-0 rounded-md border bg-card shadow-sm', className)}>
      {title && (
        <header className="flex items-center justify-between gap-2 border-b px-5 py-3">
          <h2 className="text-base font-bold">{title}</h2>
          {actions}
        </header>
      )}
      <div className={cn('p-5', bodyClassName)}>{children}</div>
    </section>
  )
}

export function StatCard({ label, value, footer }) {
  return (
    <div className="min-w-0 rounded-md border bg-card p-5 shadow-sm">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-bold tabular-nums">{value}</p>
      {footer && <div className="mt-2 text-sm text-muted-foreground">{footer}</div>}
    </div>
  )
}

const statusStyles = {
  open: ['Open', 'text-info', 'bg-info'],
  pending: ['Pending', 'text-muted-foreground', 'bg-muted-foreground'],
  scheduled: ['Scheduled', 'text-info', 'bg-info'],
  applied: ['Applied', 'text-success', 'bg-success'],
  completed: ['Completed', 'text-success', 'bg-success'],
  failed: ['Failed', 'text-destructive', 'bg-destructive'],
  rolled_back: ['Rolled back', 'text-warning', 'bg-warning'],
  dismissed: ['Dismissed', 'text-muted-foreground', 'bg-muted-foreground'],
  not_accurate: ['Not accurate', 'text-muted-foreground', 'bg-muted-foreground'],
}

// Console-style status: coloured dot + label, readable without colour.
export function StatusBadge({ status }) {
  const [label, text, dot] = statusStyles[status] ?? [status, 'text-foreground', 'bg-foreground']
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-sm font-medium', text)}>
      <span className={cn('size-2 rounded-full', dot)} aria-hidden="true" />
      {label}
    </span>
  )
}

export function DataTable({ columns, rows, rowKey }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted text-left">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn('px-4 py-2.5 font-bold whitespace-nowrap', c.align === 'right' && 'text-right')}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[rowKey]} className="border-b last:border-0 hover:bg-accent/60">
              {columns.map((c) => (
                <td key={c.key} className={cn('px-4 py-2.5', !c.wrap && 'whitespace-nowrap', c.align === 'right' && 'text-right tabular-nums')}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Field({ id, label, error, ...inputProps }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-bold">{label}</label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 aria-invalid:border-destructive"
        {...inputProps}
      />
      {error && <p id={`${id}-error`} className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
