import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useConnections } from '@/api/hooks'
import type { Connection } from '@/lib/types'

interface Ctx {
  connections: Connection[]
  current: Connection | null
  connectionId: string | null
  setConnectionId: (id: string) => void
  isLoading: boolean
}

const ConnectionCtx = createContext<Ctx | null>(null)
const KEY = 'ec2opt.connectionId'

function readStored(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const { data = [], isLoading } = useConnections()
  const [selected, setSelected] = useState<string | null>(readStored)

  const current = useMemo(() => {
    const usable = data.filter((c) => c.status !== 'pending')
    return usable.find((c) => c.id === selected) ?? usable[0] ?? null
  }, [data, selected])

  useEffect(() => {
    if (current) try { localStorage.setItem(KEY, current.id) } catch { /* private mode */ }
  }, [current])

  const value = useMemo<Ctx>(() => ({
    connections: data, current, connectionId: current?.id ?? null, setConnectionId: setSelected, isLoading,
  }), [data, current, isLoading])
  return <ConnectionCtx.Provider value={value}>{children}</ConnectionCtx.Provider>
}

export function useConnectionCtx(): Ctx {
  const c = useContext(ConnectionCtx)
  if (!c) throw new Error('useConnectionCtx outside ConnectionProvider')
  return c
}
