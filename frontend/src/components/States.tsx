import { AlertCircle, Inbox, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function EmptyState({ title, body, action, icon }: { title: string; body?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-card px-6 py-12 text-center">
      <div className="text-muted-foreground">{icon ?? <Inbox className="size-8" aria-hidden="true" />}</div>
      <h3 className="font-semibold">{title}</h3>
      {body && <div className="max-w-md text-sm text-muted-foreground">{body}</div>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong'
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-card px-6 py-10 text-center">
      <AlertCircle className="size-7 text-destructive" aria-hidden="true" />
      <p className="text-sm">{msg}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}><RotateCw />Retry</Button>}
    </div>
  )
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EstimateFootnote() {
  return (
    <p className="mt-8 text-xs text-muted-foreground">
      All amounts are <strong>estimates</strong> based on Linux on-demand list prices in each instance's region (730 h/month).
      Reserved Instances, Savings Plans, Spot, data transfer and EBS storage are not modelled. Windows / BYOL pricing is not supported.
    </p>
  )
}
