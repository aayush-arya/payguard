import { useState, type ReactNode } from 'react'
import { useParams, Link } from 'react-router-dom'
import { capturePayment, getPaymentDetail, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { StatusBadge } from '../components/StatusBadge'
import { RefundModal } from '../components/RefundModal'
import { formatAmount, formatDateTime } from '../lib/format'

const REFUNDABLE_STATUSES = new Set(['SUCCEEDED', 'REFUND_FAILED', 'REFUND_PENDING'])

export function PaymentDetail() {
  const { paymentId } = useParams<{ paymentId: string }>()
  const { apiKey } = useAuth()
  const { data: payment, error, loading, refetch } = useApiQuery(
    () => getPaymentDetail(apiKey!, paymentId!),
    [apiKey, paymentId],
  )
  const [showRefund, setShowRefund] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function handleCapture() {
    setCapturing(true)
    setActionError(null)
    try {
      await capturePayment(apiKey!, paymentId!)
      refetch()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to capture payment.')
    } finally {
      setCapturing(false)
    }
  }

  if (loading) return <p className="text-sm text-slate-400">Loading…</p>
  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
  if (!payment) return null

  const reservedRefunds = payment.refunds
    .filter((r) => r.status === 'PENDING' || r.status === 'SUCCEEDED')
    .reduce((sum, r) => sum + r.amount, 0)
  const remainingRefundable = payment.amount - reservedRefunds

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link to="/payments" className="text-sm text-slate-500 hover:underline dark:text-slate-400">
          ← All payments
        </Link>
        <div className="mt-2 flex items-center justify-between">
          <div>
            <h1 className="font-mono text-lg text-slate-900 dark:text-slate-100">{payment.id}</h1>
            <div className="mt-2 flex items-center gap-3">
              <StatusBadge status={payment.status} />
              <span className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {formatAmount(payment.amount, payment.currency)}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            {payment.status === 'PROCESSING' && (
              <button
                type="button"
                onClick={handleCapture}
                disabled={capturing}
                className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50 dark:bg-white dark:text-slate-900"
              >
                {capturing ? 'Capturing…' : 'Capture'}
              </button>
            )}
            {REFUNDABLE_STATUSES.has(payment.status) && remainingRefundable > 0 && (
              <button
                type="button"
                onClick={() => setShowRefund(true)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                Refund
              </button>
            )}
          </div>
        </div>
        {actionError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{actionError}</p>}
      </div>

      <Section title="Timeline">
        <ol className="flex flex-col gap-3">
          {payment.events.map((event) => (
            <li key={event.id} className="flex items-center gap-3 text-sm">
              <span className="w-40 shrink-0 text-slate-400">{formatDateTime(event.created_at)}</span>
              <span className="text-slate-600 dark:text-slate-300">
                {event.from_status ?? 'start'} → <strong>{event.to_status}</strong>
              </span>
              <span className="text-xs text-slate-400">({event.actor})</span>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Provider attempts">
        <Table
          columns={['#', 'Provider', 'Status', 'Failure', 'Created']}
          rows={payment.attempts.map((a) => [
            String(a.attempt_number),
            a.provider_name,
            <StatusBadge key="s" status={a.status} />,
            a.failure_classification ?? '—',
            formatDateTime(a.created_at),
          ])}
          empty="No provider attempts."
        />
      </Section>

      <Section title="Refunds">
        <Table
          columns={['ID', 'Amount', 'Status', 'Created']}
          rows={payment.refunds.map((r) => [
            r.id.slice(0, 8) + '…',
            formatAmount(r.amount, payment.currency),
            <StatusBadge key="s" status={r.status} />,
            formatDateTime(r.created_at),
          ])}
          empty="No refunds."
        />
      </Section>

      <Section title="Ledger entries">
        <Table
          columns={['Account', 'Direction', 'Amount', 'Created']}
          rows={payment.ledger_entries.map((entry) => [
            entry.account,
            entry.direction,
            formatAmount(entry.amount, payment.currency),
            formatDateTime(entry.created_at),
          ])}
          empty="No ledger entries yet -- entries are written when a payment or refund settles."
        />
      </Section>

      {showRefund && (
        <RefundModal
          paymentId={payment.id}
          remaining={remainingRefundable}
          currency={payment.currency}
          onClose={() => setShowRefund(false)}
          onRefunded={refetch}
        />
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
      {children}
    </div>
  )
}

function Table({
  columns,
  rows,
  empty,
}: {
  columns: string[]
  rows: ReactNode[][]
  empty: string
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{empty}</p>
  }
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
            {columns.map((c) => (
              <th key={c} className="px-4 py-3 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0 dark:border-slate-800/60">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
