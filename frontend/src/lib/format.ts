import type { ActionCode, AnyActionCode, FindingStatus } from './types'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export function money(v: number | null | undefined, opts: { whole?: boolean } = {}): string {
  if (v == null || Number.isNaN(v)) return '—'
  return (opts.whole ? usd0 : usd).format(v)
}

/** Signed monthly delta: savings are negative deltas, shown as "−$210.24". */
export function signedMoney(delta: number | null | undefined): string {
  if (delta == null) return '—'
  if (delta === 0) return usd.format(0)
  return `${delta < 0 ? '−' : '+'}${usd.format(Math.abs(delta))}`
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v == null) return '—'
  return `${v.toFixed(digits)} %`
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return v.toLocaleString('en-US', { maximumFractionDigits: digits })
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return 'never'
  const s = Math.round((now.getTime() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export const STATUS_LABEL: Record<FindingStatus, string> = {
  IDLE: 'Idle',
  OVER_PROVISIONED: 'Over-provisioned',
  UNDER_PROVISIONED: 'Under-provisioned',
  NEEDS_REVIEW: 'Needs review',
  ACTIVE: 'Active',
  STOPPED: 'Stopped',
  INSUFFICIENT_DATA: 'Insufficient data',
  ERROR: 'Error',
}

export const ACTION_LABEL: Record<AnyActionCode, string> = {
  STOP_INSTANCE: 'Stop instance',
  TERMINATE_INSTANCE: 'Terminate instance',
  RESIZE: 'Resize',
  ENABLE_UNLIMITED_CREDITS: 'Enable unlimited credits',
  UNDO_STOP: 'Undo: start instance',
  UNDO_RESIZE: 'Undo: resize back',
  UNDO_CREDITS: 'Undo: standard credits',
}

export const ACTION_SHORT: Record<ActionCode, string> = {
  STOP_INSTANCE: 'Stop',
  TERMINATE_INSTANCE: 'Terminate',
  RESIZE: 'Resize',
  ENABLE_UNLIMITED_CREDITS: 'Unlimited credits',
}

export const KIND_LABEL: Record<string, string> = {
  STOP: 'Stop', TERMINATE: 'Terminate', RESIZE_DOWN: 'Resize down', RESIZE_UP: 'Resize up',
}
