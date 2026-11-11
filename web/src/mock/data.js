// Mock data shaped like the planned API. Replace with real calls later.

export const accounts = [
  { id: 'prod', name: 'AWS: Production', lastSync: '10 min ago' },
  { id: 'staging', name: 'AWS: Staging', lastSync: '1 h ago' },
]

export const kpis = {
  totalSpend: 48210,
  spendChangePct: 3,
  potentialSavings: 6940,
  openSuggestions: 14,
  realizedSavings: 2310,
  appliedActions: 9,
  coveragePct: 72,
}

export const serviceBreakdown = [
  { service: 'EC2', resources: 148, waste: '23 idle/oversized', savings: 4120 },
  { service: 'RDS', resources: 22, waste: '4 oversized', savings: 1860 },
  { service: 'DynamoDB', resources: 61, waste: '7 over-provisioned', savings: 540 },
  { service: 'VPC', resources: 81, waste: '5 unused NAT/EIP', savings: 420 },
]

export const recentActions = [
  { id: 'a1', timestamp: '2026-10-08 09:12', resource: 'i-0a1b2c (api-worker-3)', action: 'Resize m5.2xlarge → m5.large', savings: 210, status: 'applied' },
  { id: 'a2', timestamp: '2026-10-12 02:00', resource: 'db-reporting', action: 'Resize db.r5.2xlarge → db.r5.xlarge', savings: 480, status: 'scheduled' },
  { id: 'a3', timestamp: '2026-10-07 16:40', resource: 'i-09f8e7 (batch-1)', action: 'Stop idle instance', savings: 95, status: 'rolled_back' },
  { id: 'a4', timestamp: '2026-10-07 11:05', resource: 'eipalloc-3c4d', action: 'Release unused Elastic IP', savings: 3.6, status: 'failed' },
]

// Daily cumulative savings for the last 90 days.
export const savingsTrend = Array.from({ length: 90 }, (_, i) => {
  const date = new Date(2026, 7, 13 + i)
  const realized = Math.round(i * 24 + Math.sin(i / 5) * 40)
  return {
    date: date.toISOString().slice(5, 10),
    realized: Math.max(0, realized),
    potential: Math.round(2400 + i * 50 + Math.cos(i / 7) * 60),
  }
})
