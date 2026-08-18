import { Link } from 'react-router-dom'
import { getDashboardSummary, listPayments } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { SummaryCard } from '../components/SummaryCard'
import { StatusBadge } from '../components/StatusBadge'
import { formatAmount, formatDateTime } from '../lib/format'

export function DashboardHome() {
  const { apiKey } = useAuth()
  const summary = useApiQuery(() => getDashboardSummary(apiKey!), [apiKey])
  const recent = useApiQuery(() => listPayments(apiKey!, { limit: 5 }), [apiKey])

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Overview</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          A snapshot of this merchant's payment activity.
        </p>
      </div>

      {summary.error && <p className="text-sm text-red-600 dark:text-red-400">{summary.error}</p>}
      {summary.data && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <SummaryCard label="Total payments" value={String(summary.data.total_payments)} />
          <SummaryCard
            label="Succeeded volume"
            value={formatAmount(summary.data.total_succeeded_amount, 'USD')}
          />
          <SummaryCard
            label="Refunded volume"
            value={formatAmount(summary.data.total_refunded_amount, 'USD')}
          />
          <SummaryCard label="Unknown (needs reconciliation)" value={String(summary.data.counts_by_status.UNKNOWN ?? 0)} />
        </div>
      )}

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Recent payments</h2>
          <Link to="/payments" className="text-sm text-slate-500 hover:underline dark:text-slate-400">
            View all
          </Link>
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
          {recent.error && (
            <p className="p-4 text-sm text-red-600 dark:text-red-400">{recent.error}</p>
          )}
          {recent.data && recent.data.items.length === 0 && (
            <p className="p-4 text-sm text-slate-500 dark:text-slate-400">No payments yet.</p>
          )}
          {recent.data && recent.data.items.length > 0 && (
            <table className="w-full text-sm">
              <tbody>
                {recent.data.items.map((payment) => (
                  <tr
                    key={payment.id}
                    className="border-t border-slate-200 first:border-t-0 dark:border-slate-800"
                  >
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
                      {formatDateTime(payment.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
