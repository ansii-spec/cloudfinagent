import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ConnectionProvider } from '@/context/ConnectionProvider'
import Recommendations from '@/pages/Recommendations'
import { connection, finding } from './fixtures'
import { mockApi, renderWithProviders } from './utils'

const ALL = [
  finding(),
  finding({ id: 'f2', name: 'dev-sandbox', status: 'IDLE', instance_id: 'i-0000000000000002', suggestion: { ...finding().suggestion!, action: 'STOP_INSTANCE', headline: 'Stop this idle instance' } }),
]

describe('Recommendations', () => {
  it('filters by status via the summary strip', async () => {
    const calls: string[] = []
    mockApi((_m, p) => {
      if (p === '/connections') return { json: [connection] }
      if (p.startsWith('/findings?')) {
        calls.push(p)
        const items = p.includes('status=IDLE') ? ALL.filter((f) => f.status === 'IDLE') : ALL
        return { json: { items, total: items.length, page: 1, page_size: 25,
          summary: { counts: { IDLE: 1, OVER_PROVISIONED: 1 }, potential_monthly_saving: 350, regions: ['ap-south-1'], dismissed: 0 } } }
      }
      if (p.startsWith('/scans') || p.includes('/scans')) return { json: { items: [], total: 0, page: 1, page_size: 5 } }
      return undefined
    })
    renderWithProviders(<ConnectionProvider><Routes><Route path="/recommendations" element={<Recommendations />} /></Routes></ConnectionProvider>, { route: '/recommendations' })
    expect((await screen.findAllByText('reporting-worker')).length).toBeGreaterThan(0)
    await userEvent.click(screen.getAllByRole('button', { pressed: false }).find((b) => b.querySelector('[data-status=IDLE]') != null)!)
    await waitFor(() => expect(screen.queryAllByText('reporting-worker')).toHaveLength(0))
    expect(calls.some((c) => c.includes('status=IDLE'))).toBe(true)
  })
})
