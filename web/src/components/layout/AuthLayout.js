import { Outlet } from 'react-router'
import { Logo } from './AppShell'

export default function AuthLayout() {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-12 items-center bg-header px-4 text-header-foreground">
        <Logo />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-12 md:py-20">
        <div className="w-full max-w-md rounded-md border bg-card p-8 shadow-sm">
          <Outlet />
        </div>
      </main>
      <footer className="py-6 text-center text-xs text-muted-foreground">© 2026 CloudFinAgent</footer>
    </div>
  )
}
