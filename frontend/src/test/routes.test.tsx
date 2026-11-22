import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { RequireAuth } from '@/routes'
import { mockApi, renderWithProviders } from './utils'

describe('route guard', () => {
  it('redirects unauthenticated users to /login?next=', async () => {
    mockApi((_m, p) => (p === '/auth/me' ? { status: 401, json: { error: { code: 'UNAUTHORIZED', message: 'x' } } } : undefined))
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<p>login page</p>} />
        <Route path="/dashboard" element={<RequireAuth><p>secret</p></RequireAuth>} />
      </Routes>, { route: '/dashboard' })
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('secret')).toBeNull()
  })
  it('lets logged-in users through', async () => {
    mockApi((_m, p) => (p === '/auth/me' ? { json: { id: 'u', email: 'a@b.c', name: 'A', created_at: null } } : undefined))
    renderWithProviders(
      <Routes><Route path="/dashboard" element={<RequireAuth><p>secret</p></RequireAuth>} /></Routes>, { route: '/dashboard' })
    expect(await screen.findByText('secret')).toBeInTheDocument()
  })
})
