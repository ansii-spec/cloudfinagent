import type { ApiErrorBody } from '@/lib/types'

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
  get blockers(): string[] {
    const d = this.details as { blockers?: string[] } | undefined
    return d?.blockers ?? []
  }
}

type Query = Record<string, string | number | boolean | string[] | undefined | null>

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

function qs(q?: Query): string {
  if (!q) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v == null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x))
    else p.append(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function api<T>(method: string, path: string, opts: { body?: unknown; query?: Query } = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}${qs(opts.query)}`, {
    method,
    credentials: 'include',
    headers: {
      'X-Requested-With': 'ec2opt', // CSRF guard expected by the API
      ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data: unknown = text ? JSON.parse(text) : undefined
  if (!res.ok) {
    const err = (data as ApiErrorBody | undefined)?.error
    if (res.status === 401 && !path.startsWith('/auth/')) onUnauthorized?.()
    throw new ApiError(res.status, err?.code ?? 'HTTP_ERROR', err?.message ?? `Request failed (${res.status})`, err?.details)
  }
  return data as T
}

export const get = <T>(path: string, query?: Query) => api<T>('GET', path, { query })
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, { body: body ?? {} })
export const patch = <T>(path: string, body: unknown) => api<T>('PATCH', path, { body })
export const del = <T>(path: string, body?: unknown) => api<T>('DELETE', path, { body })
