import { Check } from 'lucide-react'
import { Checkbox as C } from 'radix-ui'
import { cn } from '@/lib/utils'

export function Checkbox({ className, ...p }: React.ComponentProps<typeof C.Root>) {
  return (
    <C.Root
      className={cn('peer size-4 shrink-0 rounded border border-muted-foreground/50 bg-card data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground', className)}
      {...p}
    >
      <C.Indicator className="flex items-center justify-center"><Check className="size-3" /></C.Indicator>
    </C.Root>
  )
}
