import type {
  ApiErrorBody,
  DashboardSummary,
  Payment,
  PaymentDetail,
  PaymentListResponse,
  ReconciliationReport,
  Refund,
} from './types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  code: string
  requestId: string
  status: number

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message)
    this.status = status
    this.code = body.error.code
    this.requestId = body.error.request_id
  }
}

function randomIdempotencyKey(): string {
  return crypto.randomUUID()
}

async function request<T>(
  apiKey: string,
  path: string,
  init: RequestInit & { idempotent?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${apiKey}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.idempotent) headers.set('Idempotency-Key', randomIdempotencyKey())

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  const body = await response.json()
  if (!response.ok) throw new ApiError(response.status, body as ApiErrorBody)
  return body as T
}

// A GET /v1/health call needs no API key -- used by the connect screen to
// verify the API is even reachable before asking the user to authenticate.
export async function checkApiHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/v1/health`)
    return response.ok
  } catch {
    return false
  }
}

export async function listPayments(
  apiKey: string,
  params: { status?: string; limit?: number; offset?: number } = {},
): Promise<PaymentListResponse> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  query.set('limit', String(params.limit ?? 20))
  query.set('offset', String(params.offset ?? 0))
  return request(apiKey, `/v1/payments?${query.toString()}`)
}

export async function getPaymentDetail(apiKey: string, paymentId: string): Promise<PaymentDetail> {
  return request(apiKey, `/v1/payments/${paymentId}/detail`)
}

export async function createPayment(
  apiKey: string,
  input: { amount: number; currency: string; token: string; merchant_reference?: string },
): Promise<Payment> {
  return request(apiKey, '/v1/payments', {
    method: 'POST',
    idempotent: true,
    body: JSON.stringify({
      amount: input.amount,
      currency: input.currency,
      merchant_reference: input.merchant_reference || null,
      payment_method: { type: 'token', token: input.token },
    }),
  })
}

export async function capturePayment(apiKey: string, paymentId: string): Promise<Payment> {
  return request(apiKey, `/v1/payments/${paymentId}/capture`, { method: 'POST', idempotent: true })
}

export async function refundPayment(apiKey: string, paymentId: string, amount: number): Promise<Refund> {
  return request(apiKey, `/v1/payments/${paymentId}/refunds`, {
    method: 'POST',
    idempotent: true,
    body: JSON.stringify({ amount }),
  })
}

export async function getDashboardSummary(apiKey: string): Promise<DashboardSummary> {
  return request(apiKey, '/v1/dashboard/summary')
}

export async function runReconciliation(apiKey: string): Promise<{ reports: ReconciliationReport[] }> {
  return request(apiKey, '/v1/dashboard/reconciliation/run', { method: 'POST' })
}
