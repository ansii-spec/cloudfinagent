import * as React from 'react'
import { cn } from '@/lib/utils'

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...p }, ref) => (
    <input
      ref={ref}
      className={cn('h-9 w-full rounded-md border bg-card px-3 text-sm placeholder:text-muted-foreground disabled:opacity-50 aria-invalid:border-destructive', className)}
      {...p}
    />
  ),
)
Input.displayName = 'Input'

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn('text-sm font-medium', className)} {...p} />
}

export function Select({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn('h-9 rounded-md border bg-card px-2 text-sm', className)} {...p} />
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null
  return <p role="alert" className="text-xs text-destructive">{children}</p>
}
