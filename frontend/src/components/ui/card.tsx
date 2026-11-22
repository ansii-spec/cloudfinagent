import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('min-w-0 rounded-md border bg-card text-card-foreground shadow-sm', className)} {...p} />
}
export function CardHeader({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-0.5 border-b px-5 py-3', className)} {...p} />
}
export function CardTitle({ className, ...p }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-base font-bold', className)} {...p} />
}
export function CardDescription({ className, ...p }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-xs text-muted-foreground', className)} {...p} />
}
export function CardContent({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...p} />
}
