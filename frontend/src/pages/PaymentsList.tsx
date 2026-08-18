import { useState } from 'react'
import { Link } from 'react-router-dom'
import { listPayments } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { StatusBadge } from '../components/StatusBadge'
import { NewPaymentModal } from '../components/NewPaymentModal'
import { formatAmount, formatDateTime } from '../lib/format'

const STATUSES = [
  'CREATED',
  'PROCESSING',
  'SUCCEEDED',
  'FAILED',
  'UNKNOWN',
  'REFUND_PENDING',
  'REFUND_FAILED',
  'REFUNDED',
]

const PAGE_SIZE = 10

export function PaymentsList() {
  const { apiKey } = useAuth()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [showNewPayment, setShowNewPayment] = useState(false)

  const { data, error, loading, refetch } = useApiQuery(
    () => listPayments(apiKey!, { status: status || undefined, limit: PAGE_SIZE, offset }),
    [apiKey, status, offset],
  )

  function handleStatusChange(next: string) {
    setStatus(next)
    setOffset(0)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Payments</h1>
        <button
          type="button"
          onClick={() => setShowNewPayment(true)}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:opacity-90 dark:bg-white dark:text-slate-900"
        >
          New payment
        </button>
      </div>

      <select
        value={status}
        onChange={(e) => handleStatusChange(e.target.value)}
        className="w-fit rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
      >
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
              <th className="px-4 py-3 font-medium">ID</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Reference</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            )}
            {data && data.items.length === 0 && !loading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                  No payments match this filter.
                </td>
              </tr>
            )}
            {data?.items.map((payment) => (
              <tr key={payment.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800/60">
                <td className="px-4 py-3">
                  <Link to={`/payments/${payment.id}`} className="hover:underline">
                    {payment.id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="px-4 py-3">{formatAmount(payment.amount, payment.currency)}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={payment.status} />
                </td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                  {payment.merchant_reference ?? '—'}
                </td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                  {formatDateTime(payment.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-slate-500 dark:text-slate-400">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40 dark:border-slate-700"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40 dark:border-slate-700"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {showNewPayment && (
        <NewPaymentModal onClose={() => setShowNewPayment(false)} onCreated={refetch} />
      )}
    </div>
  )
}
