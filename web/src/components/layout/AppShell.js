import { NavLink, Outlet } from 'react-router'
import { ChevronDown, CircleUser, Cloud } from 'lucide-react'
import { cn } from 'cn'
import { accounts, kpis } from '@/mock/data'

const nav = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/suggestions', label: 'Suggestions', count: kpis.openSuggestions },
  { to: '/resources', label: 'Resources' },
  { to: '/actions', label: 'Actions' },
  { to: '/settings', label: 'Settings' },
]

export function Logo({ className }) {
  return (
    <span className={cn('inline-flex items-center gap-2 font-bold', className)}>
      <Cloud className="size-5" aria-hidden="true" />
      CloudFinAgent
    </span>
  )
}

export default function AppShell() {
  const account = accounts[0]
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-12 items-center justify-between bg-header px-4 text-header-foreground">
        <Logo />
        <button type="button" className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-sm hover:bg-white/10">
          <CircleUser className="size-4" aria-hidden="true" />
          User
          <ChevronDown className="size-3.5" aria-hidden="true" />
        </button>
      </header>

      <div className="flex flex-1">
        <aside className="hidden w-60 shrink-0 flex-col border-r bg-sidebar md:flex">
          <nav aria-label="Main" className="flex-1 py-4">
            <ul>
              {nav.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center justify-between border-l-4 py-2 pr-4 pl-5 text-sm',
                        isActive
                          ? 'border-primary bg-sidebar-accent font-bold text-sidebar-accent-foreground'
                          : 'border-transparent hover:bg-muted',
                      )
                    }
                  >
                    {item.label}
                    {item.count != null && (
                      <span className="rounded-full bg-primary px-2 text-xs font-bold text-primary-foreground">
                        {item.count}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="border-t px-5 py-4 text-xs text-muted-foreground">
            <button type="button" className="inline-flex items-center gap-1 font-bold text-foreground">
              {account.name}
              <ChevronDown className="size-3" aria-hidden="true" />
            </button>
            <p className="mt-1">Last sync {account.lastSync}</p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-4 md:p-8">
          <nav aria-label="Main" className="mb-4 flex gap-4 overflow-x-auto border-b pb-2 text-sm md:hidden">
            {nav.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => cn('whitespace-nowrap', isActive && 'font-bold text-primary')}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
