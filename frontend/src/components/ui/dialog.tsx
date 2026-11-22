import { X } from 'lucide-react'
import { Dialog as D } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export const Dialog = D.Root

/** Centered modal (focus-trapped by Radix). */
export function DialogContent({ className, children, title, description }: {
  className?: string; children: ReactNode; title: ReactNode; description?: ReactNode
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <D.Content
        className={cn('fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-card p-6 shadow-xl', className)}
      >
        <D.Title className="pr-8 text-lg font-semibold">{title}</D.Title>
        {description ? <D.Description className="mt-1 text-sm text-muted-foreground">{description}</D.Description> : <D.Description className="sr-only">{String(title)}</D.Description>}
        <div className="mt-4">{children}</div>
        <D.Close aria-label="Close" className="absolute top-4 right-4 rounded p-1 text-muted-foreground hover:bg-muted cursor-pointer">
          <X className="size-4" />
        </D.Close>
      </D.Content>
    </D.Portal>
  )
}

/** Right-side sheet (drawer). */
export function SheetContent({ className, children, title }: { className?: string; children: ReactNode; title: ReactNode }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
      <D.Content className={cn('fixed inset-y-0 right-0 z-50 flex w-full max-w-3xl flex-col border-l bg-background shadow-2xl data-[state=open]:animate-in data-[state=open]:slide-in-from-right', className)}>
        <D.Title className="sr-only">{title}</D.Title>
        <D.Description className="sr-only">Details for {String(title)}</D.Description>
        <D.Close aria-label="Close details" className="absolute top-4 right-4 z-10 rounded p-1 text-muted-foreground hover:bg-muted cursor-pointer">
          <X className="size-5" />
        </D.Close>
        {children}
      </D.Content>
    </D.Portal>
  )
}
