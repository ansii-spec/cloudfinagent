import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import { useMe } from '@/api/hooks'
import AppShell from '@/components/AppShell'
import { Skeleton } from '@/components/ui/skeleton'
import { ConnectionProvider, useConnectionCtx } from '@/context/ConnectionProvider'
import Actions from '@/pages/Actions'
import CloudWatchAgentHelp from '@/pages/CloudWatchAgentHelp'
import Connect from '@/pages/Connect'
import Dashboard from '@/pages/Dashboard'
import Login from '@/pages/Login'
import NotFound from '@/pages/NotFound'
import Recommendations from '@/pages/Recommendations'
import Register from '@/pages/Register'
import Settings from '@/pages/Settings'

function FullPageLoading() {
  return <div className="p-8"><Skeleton className="h-8 w-48" /><Skeleton className="mt-6 h-64 w-full" /></div>
}

/** Redirects unauthenticated users to /login?next=… */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()
  const loc = useLocation()
  if (isLoading) return <FullPageLoading />
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return <>{children}</>
}

/** Logged-in users don't need the login / register pages. */
export function PublicOnly({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()
  if (isLoading) return <FullPageLoading />
  if (me) return <Navigate to="/" replace />
  return <>{children}</>
}

function HomeRedirect() {
  const { connections, isLoading } = useConnectionCtx()
  if (isLoading) return <FullPageLoading />
  return <Navigate to={connections.some((c) => c.status !== 'pending') ? '/dashboard' : '/connect'} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
      <Route element={<RequireAuth><ConnectionProvider><AppShell /></ConnectionProvider></RequireAuth>}>
        <Route index element={<HomeRedirect />} />
        <Route path="/connect" element={<Connect />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/recommendations" element={<Recommendations />} />
        <Route path="/recommendations/:id" element={<Recommendations />} />
        <Route path="/actions" element={<Actions />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/help/cloudwatch-agent" element={<CloudWatchAgentHelp />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
