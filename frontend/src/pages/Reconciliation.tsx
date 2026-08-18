import { useState } from 'react'
import { Link } from 'react-router-dom'
import { runReconciliation, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { StatusBadge } from '../components/StatusBadge'
import { formatDateTime } from '../lib/format'
import type { ReconciliationReport } from '../lib/types'

export function Reconciliation() {
  const { apiKey } = useAuth()
  const [running, setRunning] = useState(false)
  const [reports, setReports] = useState<ReconciliationReport[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    setRunning(true)
    setError(null)
    try {
      const result = await runReconciliation(apiKey!)
      setReports(result.reports)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Reconciliation run failed.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Reconciliation</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500 dark:text-slate-400">
          Resolves any of this merchant's payments stuck in <StatusBadge status="UNKNOWN" /> by asking the
          provider directly what actually happened, rather than guessing or blindly retrying.
        </p>
      </div>

      <button
        type="button"
        onClick={handleRun}
        disabled={running}
        className="w-fit rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50 dark:bg-white dark:text-slate-900"
      >
        {running ? 'Running…' : 'Run reconciliation now'}
      </button>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {reports && reports.length === 0 && (
        <p className="text-sm text-slate-400">No payments needed reconciliation.</p>
      )}

      {reports && reports.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
                <th className="px-4 py-3 font-medium">Payment</th>
                <th className="px-4 py-3 font-medium">Result</th>
                <th className="px-4 py-3 font-medium">Provider status</th>
                <th className="px-4 py-3 font-medium">Resolved</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr
                  key={report.id}
                  className="border-b border-slate-100 last:border-0 dark:border-slate-800/60"
                >
                  <td className="px-4 py-3">
                    <Link to={`/payments/${report.payment_id}`} className="hover:underline">
                      {report.payment_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={report.result} />
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {report.provider_status ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {formatDateTime(report.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
