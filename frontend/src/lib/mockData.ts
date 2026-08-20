/**
 * Illustrative data for the three dashboard pages that don't have a real
 * backend yet: Risk & Fraud, Webhook Monitor, Provider Health.
 *
 * Every real page in this app (Overview, Payments, Payment Detail,
 * Reconciliation) is wired to the actual PayGuard API -- see lib/api.ts.
 * This file exists so those three pages are never scattered with inline
 * fake numbers (the anti-pattern the redesign brief explicitly calls out):
 * everything fabricated lives here, in one place, clearly named `mock*`,
 * with a comment at each function explaining exactly what real endpoint
 * would replace it.
 *
 * Backend risk signals genuinely exist server-side (packages/risk writes
 * every assessment to audit_logs, docs/risk.md) -- there is just no HTTP
 * endpoint exposing them yet. Webhook events are persisted
 * (webhook_events table, packages/webhooks) with no list endpoint either.
 * Provider health has even less to build on: only MockProvider exists
 * (docs/architecture.md ADR-004), so "provider comparison" is necessarily
 * illustrative until real adapters exist.
 *
 * To replace a mock: write the backend endpoint (same additive,
 * read-only pattern as apps/api/routers/dashboard.py), then swap the
 * mock*() call for a real fetch in lib/api.ts -- the page components
 * consume plain data shapes and don't know or care which one they got.
 */

export interface RiskDistribution {
  level: 'LOW' | 'MEDIUM' | 'HIGH' | 'BLOCKED'
  percentage: number
}

export interface RiskReason {
  label: string
  weight: number
}

export interface RiskCase {
  id: string
  paymentId: string
  score: number
  level: 'LOW' | 'MEDIUM' | 'HIGH' | 'BLOCKED'
  amount: number
  reasons: RiskReason[]
  createdAt: string
}

// Would become: GET /v1/risk/summary, aggregating audit_logs rows where
// actor='RISK_ENGINE' grouped by level (packages/risk/service.py already
// computes the level; this would just need to be persisted queryably).
export function mockRiskDistribution(): RiskDistribution[] {
  return [
    { level: 'LOW', percentage: 72 },
    { level: 'MEDIUM', percentage: 21 },
    { level: 'HIGH', percentage: 5 },
    { level: 'BLOCKED', percentage: 2 },
  ]
}

// Would become: GET /v1/risk/cases?level=HIGH,BLOCKED -- the explainable
// reasons list mirrors exactly what packages/risk/service.py's
// RiskAssessment.as_dict() already produces per-signal, just not exposed.
export function mockRiskCases(): RiskCase[] {
  return [
    {
      id: 'risk_8f3a92c1',
      paymentId: '5de67f8a-1234-4abc-9def-000000000001',
      score: 87,
      level: 'BLOCKED',
      amount: 399900,
      reasons: [
        { label: 'High transaction velocity', weight: 30 },
        { label: 'Very large amount', weight: 50 },
        { label: 'Billing/shipping country mismatch', weight: 25 },
      ],
      createdAt: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    },
    {
      id: 'risk_2b7e14d9',
      paymentId: '5de67f8a-1234-4abc-9def-000000000002',
      score: 62,
      level: 'HIGH',
      amount: 89900,
      reasons: [
        { label: 'Repeated recent declines', weight: 40 },
        { label: 'High-risk IP range', weight: 35 },
      ],
      createdAt: new Date(Date.now() - 1000 * 60 * 22).toISOString(),
    },
    {
      id: 'risk_9c4f6a0e',
      paymentId: '5de67f8a-1234-4abc-9def-000000000003',
      score: 34,
      level: 'MEDIUM',
      amount: 24900,
      reasons: [{ label: 'Large amount', weight: 20 }],
      createdAt: new Date(Date.now() - 1000 * 60 * 51).toISOString(),
    },
  ]
}

export interface WebhookEventRow {
  id: string
  eventType: string
  status: 'DELIVERED' | 'FAILED' | 'RETRIED' | 'DUPLICATE'
  attempts: number
  latencyMs: number
  signatureValid: boolean
  receivedAt: string
}

// Would become: GET /v1/webhooks -- packages/webhooks already persists
// every delivery to webhook_events with processing_status; this is that
// table's shape, projected.
export function mockWebhookEvents(): WebhookEventRow[] {
  const types = ['payment.succeeded', 'payment.failed', 'payment.unknown']
  const statuses: WebhookEventRow['status'][] = ['DELIVERED', 'DELIVERED', 'RETRIED', 'DUPLICATE', 'FAILED']
  return Array.from({ length: 12 }, (_, i) => ({
    id: `evt_${(i + 1).toString().padStart(4, '0')}`,
    eventType: types[i % types.length],
    status: statuses[i % statuses.length],
    attempts: statuses[i % statuses.length] === 'RETRIED' ? 3 : 1,
    latencyMs: Math.round(40 + Math.random() * 260),
    signatureValid: statuses[i % statuses.length] !== 'FAILED',
    receivedAt: new Date(Date.now() - i * 1000 * 60 * 7).toISOString(),
  }))
}

export interface ProviderHealthRow {
  name: string
  availability: number
  latencyMs: number
  successRate: number
  timeoutRate: number
  retryRate: number
  status: 'operational' | 'degraded'
}

// Would become: GET /v1/providers/health -- would need real provider
// adapters to measure against (docs/architecture.md ADR-004 notes real
// adapters were always out of scope for this project; MockProvider is the
// only one that actually runs today).
export function mockProviderHealth(): ProviderHealthRow[] {
  return [
    { name: 'Mock Provider', availability: 99.99, latencyMs: 42, successRate: 98.7, timeoutRate: 0.3, retryRate: 1.1, status: 'operational' },
    { name: 'Stripe', availability: 99.98, latencyMs: 210, successRate: 97.9, timeoutRate: 0.6, retryRate: 1.8, status: 'operational' },
    { name: 'Razorpay', availability: 99.9, latencyMs: 340, successRate: 96.2, timeoutRate: 1.4, retryRate: 2.9, status: 'degraded' },
    { name: 'PayPal', availability: 99.95, latencyMs: 275, successRate: 97.1, timeoutRate: 0.8, retryRate: 2.1, status: 'operational' },
  ]
}
