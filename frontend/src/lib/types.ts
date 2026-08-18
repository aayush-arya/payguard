export type PaymentStatus =
  | 'CREATED'
  | 'PROCESSING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'UNKNOWN'
  | 'REFUND_PENDING'
  | 'REFUND_FAILED'
  | 'REFUNDED'

export interface Payment {
  id: string
  status: PaymentStatus
  amount: number
  currency: string
  merchant_reference: string | null
  created_at: string
  updated_at: string
}

export interface PaymentListResponse {
  items: Payment[]
  total: number
  limit: number
  offset: number
}

export interface PaymentEvent {
  id: string
  from_status: string | null
  to_status: string
  actor: string
  created_at: string
}

export interface PaymentAttempt {
  id: string
  provider_name: string
  status: string
  failure_classification: string | null
  attempt_number: number
  created_at: string
}

export interface Refund {
  id: string
  payment_id: string
  amount: number
  status: string
  created_at: string
}

export interface LedgerEntry {
  id: string
  ledger_transaction_id: string
  account: string
  direction: 'DEBIT' | 'CREDIT'
  amount: number
  created_at: string
}

export interface PaymentDetail extends Payment {
  events: PaymentEvent[]
  attempts: PaymentAttempt[]
  refunds: Refund[]
  ledger_entries: LedgerEntry[]
}

export interface DashboardSummary {
  counts_by_status: Record<string, number>
  total_payments: number
  total_succeeded_amount: number
  total_refunded_amount: number
}

export interface ReconciliationReport {
  id: string
  payment_id: string
  result: string
  internal_status: string
  provider_status: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    request_id: string
  }
}
