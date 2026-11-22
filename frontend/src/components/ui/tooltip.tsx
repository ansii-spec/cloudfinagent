import { Tooltip as T } from 'radix-ui'
import type { ReactNode } from 'react'

export const TooltipProvider = T.Provider

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  if (!content) return <>{children}</>
  return (
    <T.Root delayDuration={150}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}
