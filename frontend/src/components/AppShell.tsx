import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CircleUser, Cloud, History, LayoutDashboard, ListChecks, LogOut, Menu, Moon, Settings, Sun, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useLogout, useMe, usePublicConfig, useScans, useStartScan } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { useConnectionCtx } from '@/context/ConnectionProvider'
import { applyTheme, initialTheme, type Theme } from '@/context/theme'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/recommendations', label: 'Recommendations', icon: ListChecks },
  { to: '/actions', label: 'Actions', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2 font-bold', className)}>
      <Cloud className="size-5" aria-hidden="true" />
      CloudFinAgent
    </span>
  )
}

export function ScanProgressBanner() {
  const { connectionId } = useConnectionCtx()
  const { data } = useScans(connectionId)
  const qc = useQueryClient()
  const latest = data?.items[0]
  const running = latest && (latest.status === 'queued' || latest.status === 'running')
  const wasRunning = useRef(false)
  useEffect(() => {
    if (running) wasRunning.current = true
    else if (wasRunning.current && latest) {
      wasRunning.current = false
      qc.invalidateQueries({ queryKey: ['findings'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      if (latest.status === 'failed') toast.error(`Scan failed: ${latest.error ?? 'unknown error'}`)
      else toast.success(`Scan finished: ${latest.progress.processed} instances analysed`)
    }
  }, [running, latest, qc])
  if (!running || !latest) return null
  const { processed, total } = latest.progress
  const pct = total ? Math.round((processed / total) * 100) : 0
  return (
    <div role="status" className="mb-4 rounded-lg border bg-accent px-4 py-3 text-sm text-accent-foreground">
      <div className="flex items-center justify-between gap-2">
        <span>Scanning… {total ? `${processed} / ${total} instances analysed` : 'discovering instances'}</span>
        <span className="tabular-nums">{pct} %</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-card">
        <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function RunScanButton({ size = 'sm' }: { size?: 'sm' | 'default' }) {
  const { current, connectionId } = useConnectionCtx()
  const scans = useScans(connectionId)
  const start = useStartScan(connectionId)
  const latest = scans.data?.items[0]
  const running = latest && (latest.status === 'queued' || latest.status === 'running')
  const disabled = !current || current.status !== 'connected' || !!running || start.isPending
  const last = scans.data?.items.find((s) => s.finished_at)
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs text-muted-foreground lg:inline">Scanned {relativeTime(last?.finished_at)}</span>
      <Button size={size} disabled={disabled} onClick={() => start.mutate(undefined, {
        onSuccess: () => toast.success('Scan started'),
        onError: (e) => toast.error(e.message),
      })}>
        {running ? 'Scanning…' : 'Run scan'}
      </Button>
    </div>
  )
}

export default function AppShell() {
  const { data: me } = useMe()
  const { data: config } = usePublicConfig()
  const { connections, current, setConnectionId } = useConnectionCtx()
  const logout = useLogout()
  const navigate = useNavigate()
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [menuOpen, setMenuOpen] = useState(false)
  const [demoDismissed, setDemoDismissed] = useState(() => {
    try { return sessionStorage.getItem('ec2opt.demoBanner') === '1' } catch { return false }
  })
  useEffect(() => applyTheme(theme), [theme])
  const usable = connections.filter((c) => c.status !== 'pending')

  const renderNav = (mini: boolean) => (
    <nav aria-label="Main" className="flex-1 py-4">
      <ul>
        {NAV.map((n) => {
          const link = (
            <NavLink to={n.to} onClick={() => setMenuOpen(false)} aria-label={mini ? n.label : undefined}
              className={({ isActive }) => cn('flex items-center gap-3 border-l-4 py-2 text-sm',
                mini ? 'h-10 justify-center pr-1 pl-0' : 'pr-4 pl-5',
                isActive ? 'border-primary bg-accent font-bold text-accent-foreground' : 'border-transparent hover:bg-muted')}>
              <n.icon className="size-4 shrink-0" aria-hidden="true" />{!mini && n.label}
            </NavLink>
          )
          // Tooltip gets its own wrapper: merging into NavLink would clobber its function className
          return <li key={n.to}>{mini ? <Tip content={n.label} side="right"><div>{link}</div></Tip> : link}</li>
        })}
      </ul>
    </nav>
  )
  const nav = renderNav(false)

  const headerBtn = 'text-header-foreground hover:bg-white/10 hover:text-header-foreground'
  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-30 flex h-12 items-center gap-2 bg-header px-4 text-header-foreground">
        <Button variant="ghost" size="icon" className={cn('md:hidden', headerBtn)} aria-label="Open menu" onClick={() => setMenuOpen(true)}><Menu /></Button>
        <Link to="/dashboard"><Logo /></Link>
        {usable.length > 0 && (
          <Select aria-label="AWS connection" value={current?.id ?? ''} onChange={(e) => setConnectionId(e.target.value)}
            className="ml-4 hidden h-8 max-w-60 border-white/30 bg-transparent text-header-foreground sm:block [&>option]:text-foreground">
            {usable.map((c) => (
              <option key={c.id} value={c.id}>{c.label}{c.aws_account_id ? ` · ${c.aws_account_id}` : ''}</option>
            ))}
          </Select>
        )}
        <div className="ml-auto flex items-center gap-1">
          <Tip content={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
            <Button variant="ghost" size="icon" className={headerBtn} aria-label="Toggle dark mode" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? <Sun /> : <Moon />}
            </Button>
          </Tip>
          <span className="hidden items-center gap-1.5 px-2 text-sm sm:inline-flex"><CircleUser className="size-4" aria-hidden="true" />{me?.name}</span>
          <Tip content="Log out">
            <Button variant="ghost" size="icon" className={headerBtn} aria-label="Log out" onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login') })}>
              <LogOut />
            </Button>
          </Tip>
        </div>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-sidebar shadow-xl">
            <div className="flex h-12 items-center justify-between bg-header px-4 text-header-foreground"><Logo />
              <Button variant="ghost" size="icon" className={headerBtn} aria-label="Close menu" onClick={() => setMenuOpen(false)}><X /></Button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex flex-1">
        {/* Always collapsed: icons only, the page name shows on hover / keyboard focus */}
        <aside className="sticky top-12 hidden h-[calc(100svh-3rem)] w-14 shrink-0 flex-col border-r bg-sidebar md:flex">
          {renderNav(true)}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
        <main className="w-full min-w-0 flex-1 p-4 md:p-8">
          {config?.demo_mode && !demoDismissed && (
            <div className="mb-6 flex items-center justify-between gap-3 border-b pb-2 text-xs text-muted-foreground">
              <span>Demo mode: sample data, no AWS account is used.</span>
              <Button variant="ghost" size="icon" className="size-6" aria-label="Dismiss demo notice" onClick={() => {
                setDemoDismissed(true)
                try { sessionStorage.setItem('ec2opt.demoBanner', '1') } catch { /* ignore */ }
              }}><X /></Button>
            </div>
          )}
          {current?.status === 'broken' && (
            <div role="alert" className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
              <AlertTriangle className="size-4 text-destructive" aria-hidden="true" />
              <span className="flex-1"><strong>Connection broken:</strong> {current.last_error ?? 'AWS refused AssumeRole.'}</span>
              <Button size="sm" variant="outline" asChild><Link to={`/connect?id=${current.id}`}>Re-verify</Link></Button>
            </div>
          )}
          <ScanProgressBanner />
          <Outlet />
        </main>
        </div>
      </div>
    </div>
  )
}
