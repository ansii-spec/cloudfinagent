import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'

export type Handler = (method: string, path: string, body: unknown) => { status?: number; json?: unknown } | undefined

/** Mocks fetch for /api/v1/* with a route handler. */
export function mockApi(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace('/api/v1', '') + url.search
    const r = handler(init?.method ?? 'GET', path, init?.body ? JSON.parse(String(init.body)) : undefined)
    const status = r?.status ?? (r ? 200 : 404)
    const body = r?.json ?? (r ? {} : { error: { code: 'NOT_FOUND', message: 'not found' } })
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export function renderWithProviders(ui: ReactNode, { route = '/' }: { route?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}
