import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ConfirmActionModal } from '@/components/ConfirmActionModal'
import { preview } from './fixtures'
import { mockApi, renderWithProviders } from './utils'

describe('ConfirmActionModal', () => {
  it('blockers disable confirm', async () => {
    mockApi((_m, p) => (p.includes('/preview') ? { json: preview({ blockers: ['Managed by Auto Scaling group web'] }) } : undefined))
    renderWithProviders(<ConfirmActionModal findingId="f1" action="RESIZE" onClose={() => {}} />)
    expect(await screen.findByText('Managed by Auto Scaling group web')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'I understand' }))
    expect(screen.getByRole('button', { name: /confirm resize/i })).toBeDisabled()
  })

  it('requires "I understand" before confirming', async () => {
    mockApi((_m, p) => (p.includes('/preview') ? { json: preview() } : undefined))
    renderWithProviders(<ConfirmActionModal findingId="f1" action="RESIZE" onClose={() => {}} />)
    const btn = await screen.findByRole('button', { name: /confirm resize/i })
    expect(btn).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: 'I understand' }))
    expect(btn).toBeEnabled()
  })

  it('terminate requires typing the instance ID', async () => {
    mockApi((_m, p) => (p.includes('/preview')
      ? { json: preview({ action: 'TERMINATE_INSTANCE', requires_typed_confirmation: true, change: { from: 'm5.large', to: 'terminated' } }) }
      : undefined))
    renderWithProviders(<ConfirmActionModal findingId="f1" action="TERMINATE_INSTANCE" onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'I understand' }))
    const btn = screen.getByRole('button', { name: /confirm terminate/i })
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/to confirm termination/), 'i-wrong')
    expect(btn).toBeDisabled()
    await userEvent.clear(screen.getByLabelText(/to confirm termination/))
    await userEvent.type(screen.getByLabelText(/to confirm termination/), 'i-0a1b2c3d4e5f60004')
    expect(btn).toBeEnabled()
  })

  it('switches to live progress after confirming', async () => {
    mockApi((m, p) => {
      if (p.includes('/preview')) return { json: preview() }
      if (m === 'POST' && p.endsWith('/actions')) return { status: 202, json: { action_id: 'a1' } }
      if (p.startsWith('/actions/a1')) return { json: {
        id: 'a1', action: 'RESIZE', status: 'succeeded', instance_id: 'i-1', instance_name: 'reporting-worker', can_undo: true,
        steps_log: [{ ts: '', step: 'Stop instance', status: 'ok', message: '' }], before: {}, after: {}, options: {},
        monthly_saving_usd: 210.24, error: null,
      } }
      return undefined
    })
    renderWithProviders(<ConfirmActionModal findingId="f1" action="RESIZE" onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: 'I understand' }))
    await userEvent.click(screen.getByRole('button', { name: /confirm resize/i }))
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /undo/i })).toBeInTheDocument()
  })
})
