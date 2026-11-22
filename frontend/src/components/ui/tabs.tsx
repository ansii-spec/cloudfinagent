import { Tabs as T } from 'radix-ui'
import { cn } from '@/lib/utils'

export const Tabs = T.Root
export function TabsList({ className, ...p }: React.ComponentProps<typeof T.List>) {
  return <T.List className={cn('inline-flex flex-wrap gap-1 rounded-md bg-muted p-1', className)} {...p} />
}
export function TabsTrigger({ className, ...p }: React.ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn('rounded px-3 py-1.5 text-sm font-medium text-muted-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-xs cursor-pointer', className)}
      {...p}
    />
  )
}
export function TabsContent({ className, ...p }: React.ComponentProps<typeof T.Content>) {
  return <T.Content className={cn('mt-4', className)} {...p} />
}
