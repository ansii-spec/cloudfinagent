import { Eye, EyeOff } from 'lucide-react'
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

/** Password field with a show / hide toggle. */
export const PasswordInput = React.forwardRef<HTMLInputElement, Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>>(
  ({ className, ...p }, ref) => {
    const [show, setShow] = React.useState(false)
    return (
      <div className="relative">
        <Input ref={ref} type={show ? 'text' : 'password'} className={cn('pr-10', className)} {...p} />
        <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide password' : 'Show password'}
          aria-pressed={show} title={show ? 'Hide password' : 'Show password'}
          className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
          {show ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
        </button>
      </div>
    )
  },
)
PasswordInput.displayName = 'PasswordInput'

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
