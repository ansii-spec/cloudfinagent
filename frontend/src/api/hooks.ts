import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  ActionCode, ActionPreview, Connection, DashboardSummary, FindingDetail, FindingsResponse, Page,
  PublicConfig, RegionCount, RemediationAction, Scan, User, VerifyResult, WizardPayload,
} from '@/lib/types'
import { ApiError, del, get, patch, post } from './client'

const ACTIVE_SCAN = new Set(['queued', 'running'])
const ACTIVE_ACTION = new Set(['pending', 'running'])

// ---------------------------------------------------------------- config & auth
export const usePublicConfig = () =>
  useQuery({ queryKey: ['config'], queryFn: () => get<PublicConfig>('/config/public'), staleTime: Infinity })

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await get<User>('/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { email: string; password: string }) => post<User>('/auth/login', b),
    onSuccess: (u) => { qc.clear(); qc.setQueryData(['me'], u) },
  })
}

export function useRegister() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { name: string; email: string; password: string }) => post<User>('/auth/register', b),
    onSuccess: (u) => { qc.clear(); qc.setQueryData(['me'], u) },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<void>('/auth/logout'),
    onSuccess: () => { qc.clear(); qc.setQueryData(['me'], null) },
  })
}

export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { name?: string; current_password?: string; new_password?: string }) => patch<User>('/auth/me', b),
    onSuccess: (u) => qc.setQueryData(['me'], u),
  })
}

export function useDeleteAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (password: string) => del<void>('/auth/me', { password }),
    onSuccess: () => { qc.clear(); qc.setQueryData(['me'], null) },
  })
}

// ---------------------------------------------------------------- connections
export const useConnections = (enabled = true) =>
  useQuery({ queryKey: ['connections'], queryFn: () => get<Connection[]>('/connections'), enabled })

export const useConnection = (id: string | null | undefined) =>
  useQuery({ queryKey: ['connection', id], queryFn: () => get<Connection>(`/connections/${id}`), enabled: !!id })

export function useCreateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { label: string; enable_actions: boolean }) => post<WizardPayload>('/connections', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

export function useCreateDemoConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<Connection & { scan_id: string | null }>('/connections/demo'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

export function useVerifyConnection(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (role_arn: string) => post<VerifyResult>(`/connections/${id}/verify`, { role_arn }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections'] })
      qc.invalidateQueries({ queryKey: ['connection', id] })
    },
  })
}

export function useUpdateConnection(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: Partial<Pick<Connection, 'label' | 'regions' | 'scan_schedule' | 'enable_actions'>>) =>
      patch<Connection & { cloudformation_quick_create_url?: string }>(`/connections/${id}`, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections'] })
      qc.invalidateQueries({ queryKey: ['connection', id] })
    },
  })
}

export function useDeleteConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => del<void>(`/connections/${id}`),
    onSuccess: () => qc.invalidateQueries(),
  })
}

export const useRegions = (id: string | null | undefined, enabled = true) =>
  useQuery({
    queryKey: ['regions', id],
    queryFn: () => get<RegionCount[]>(`/connections/${id}/regions`),
    enabled: !!id && enabled,
    staleTime: 5 * 60_000,
  })

// ---------------------------------------------------------------- scans
export function useStartScan(connectionId: string | null | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (regions?: string[]) =>
      post<{ scan_id: string }>(`/connections/${connectionId}/scans`, regions?.length ? { regions } : {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans', connectionId] }),
  })
}

export const useScan = (id: string | null | undefined) =>
  useQuery({
    queryKey: ['scan', id],
    queryFn: () => get<Scan>(`/scans/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && !ACTIVE_SCAN.has(q.state.data.status) ? false : 2000),
  })

export const useScans = (connectionId: string | null | undefined) =>
  useQuery({
    queryKey: ['scans', connectionId],
    queryFn: () => get<Page<Scan>>(`/connections/${connectionId}/scans`, { page_size: 5 }),
    enabled: !!connectionId,
    refetchInterval: (q) => (q.state.data?.items.some((s) => ACTIVE_SCAN.has(s.status)) ? 2000 : false),
  })

// ---------------------------------------------------------------- findings
export interface FindingFilters {
  status?: string[]
  region?: string[]
  band?: string[]
  q?: string
  sort?: string
  only_dismissed?: boolean
  page?: number
  page_size?: number
}

export const useFindings = (connectionId: string | null | undefined, f: FindingFilters) =>
  useQuery({
    queryKey: ['findings', connectionId, f],
    queryFn: () => get<FindingsResponse>('/findings', { connection_id: connectionId, ...f }),
    enabled: !!connectionId,
    placeholderData: (prev) => prev,
  })

export const useFinding = (id: string | null | undefined) =>
  useQuery({ queryKey: ['finding', id], queryFn: () => get<FindingDetail>(`/findings/${id}`), enabled: !!id })

export function useDismiss() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...b }: { id: string; forever?: boolean; until?: string; reason?: string }) =>
      post(`/findings/${id}/dismiss`, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['findings'] })
      qc.invalidateQueries({ queryKey: ['finding'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export function useUndismiss() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => post(`/findings/${id}/undismiss`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['findings'] })
      qc.invalidateQueries({ queryKey: ['finding'] })
    },
  })
}

// ---------------------------------------------------------------- actions
export const useActionPreview = (findingId: string | null, action: ActionCode | null) =>
  useQuery({
    queryKey: ['preview', findingId, action],
    queryFn: () => post<ActionPreview>(`/findings/${findingId}/actions/preview`, { action }),
    enabled: !!findingId && !!action,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })

export function useApplyAction(findingId: string) {
  return useMutation({
    mutationFn: (b: { action: ActionCode; options: Record<string, boolean>; typed_confirmation?: string }) =>
      post<{ action_id: string }>(`/findings/${findingId}/actions`, b),
  })
}

export function useAction(id: string | null | undefined) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: ['action', id],
    queryFn: async () => {
      const a = await get<RemediationAction>(`/actions/${id}`)
      if (!ACTIVE_ACTION.has(a.status)) {
        qc.invalidateQueries({ queryKey: ['findings'] })
        qc.invalidateQueries({ queryKey: ['finding'] })
        qc.invalidateQueries({ queryKey: ['actions'] })
        qc.invalidateQueries({ queryKey: ['dashboard'] })
      }
      return a
    },
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && !ACTIVE_ACTION.has(q.state.data.status) ? false : 2000),
  })
}

export const useActions = (connectionId: string | null | undefined, page: number) =>
  useQuery({
    queryKey: ['actions', connectionId, page],
    queryFn: () => get<Page<RemediationAction>>('/actions', { connection_id: connectionId, page, page_size: 20 }),
    enabled: !!connectionId,
    refetchInterval: (q) => (q.state.data?.items.some((a) => ACTIVE_ACTION.has(a.status)) ? 2000 : false),
  })

export function useUndo() {
  return useMutation({ mutationFn: (actionId: string) => post<{ action_id: string }>(`/actions/${actionId}/undo`) })
}

// ---------------------------------------------------------------- dashboard
export const useDashboard = (connectionId: string | null | undefined, range: string) =>
  useQuery({
    queryKey: ['dashboard', connectionId, range],
    queryFn: () => get<DashboardSummary>('/dashboard/summary', { connection_id: connectionId, range }),
    enabled: !!connectionId,
    placeholderData: (prev) => prev,
  })
