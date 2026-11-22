import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { applyBlockReason } from '@/components/ApplyButton'
import { MonthlyDelta } from '@/components/Money'
import { StatusBadge } from '@/components/StatusBadge'
import { money, relativeTime, signedMoney, STATUS_LABEL } from '@/lib/format'
import type { FindingStatus } from '@/lib/types'
import { finding } from './fixtures'

describe('StatusBadge', () => {
  it.each(Object.keys(STATUS_LABEL) as FindingStatus[])('renders %s as dot + text label', (s) => {
    const { container } = render(<StatusBadge status={s} />)
    expect(screen.getByText(STATUS_LABEL[s])).toBeInTheDocument()
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull() // dot; the label means colour is never alone
  })
})

describe('money formatting', () => {
  it('formats USD', () => {
    expect(money(1234.5)).toBe('$1,234.50')
    expect(money(1234.5, { whole: true })).toBe('$1,235')
    expect(money(null)).toBe('—')
  })
  it('signs deltas: savings negative, cost increase positive', () => {
    expect(signedMoney(-210.24)).toBe('−$210.24')
    expect(signedMoney(30)).toBe('+$30.00')
  })
  it('shows savings green and cost increases blue (never red)', () => {
    render(<><MonthlyDelta delta={-210} /><MonthlyDelta delta={30} /></>)
    expect(screen.getByText('−$210.00').className).toContain('text-success')
    expect(screen.getByText('+$30.00').className).toContain('text-info')
  })
  it('relative time', () => {
    const now = new Date('2026-11-21T10:00:00Z')
    expect(relativeTime('2026-11-21T08:00:00Z', now)).toBe('2 h ago')
    expect(relativeTime(null, now)).toBe('never')
  })
})

describe('apply rules', () => {
  it('no Apply for NEEDS_REVIEW / INSUFFICIENT_DATA', () => {
    expect(applyBlockReason(finding({ status: 'NEEDS_REVIEW', suggestion: { ...finding().suggestion!, action: 'NONE' } }), false)).not.toBeNull()
    expect(applyBlockReason(finding({ status: 'INSUFFICIENT_DATA' }), false)).not.toBeNull()
  })
  it('read-only connection blocks apply', () => {
    expect(applyBlockReason(finding(), true)).toBe('This connection is read-only')
  })
  it('in-progress and cool-down block apply', () => {
    expect(applyBlockReason(finding({ action_state: 'in_progress' }), false)).toMatch(/already running/)
    expect(applyBlockReason(finding({ cooldown_until: '2026-12-01T00:00:00Z' }), false)).toMatch(/Recently changed/)
    expect(applyBlockReason(finding(), false)).toBeNull()
  })
})
