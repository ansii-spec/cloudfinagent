import type { ReactNode } from 'react'
import { Logo } from '@/components/AppShell'

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-12 items-center bg-header px-4 text-header-foreground">
        <Logo />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-12 md:py-20">
        <div className="w-full max-w-md rounded-md border bg-card p-8 shadow-sm">
          <h1 className="text-xl font-bold">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
      <footer className="py-6 text-center text-xs text-muted-foreground">© 2026 CloudFinAgent</footer>
    </div>
  )
}
