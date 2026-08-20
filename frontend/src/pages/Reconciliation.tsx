import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { GitCompareArrows, RefreshCw, ShieldCheck } from 'lucide-react'
import { runReconciliation, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { GlassCard, StatusBadge, EmptyState, useToast } from '../components/ui'
import { formatDateTime } from '../lib/format'
import type { ReconciliationReport } from '../lib/types'

export function Reconciliation() {
  const { apiKey } = useAuth()
  const { push } = useToast()
  const [running, setRunning] = useState(false)
  const [reports, setReports] = useState<ReconciliationReport[] | null>(null)

  async function handleRun() {
    setRunning(true)
    try {
      const result = await runReconciliation(apiKey!)
      setReports(result.reports)
      push(
        result.reports.length === 0 ? 'No payments needed reconciliation' : `Resolved ${result.reports.length} payment(s)`,
        'success',
      )
    } catch (err) {
      push(err instanceof ApiError ? err.message : 'Reconciliation run failed.', 'error')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">Reconciliation</h1>
          <p className="mt-1 max-w-xl text-sm text-text-muted">
            Resolves payments stuck in <StatusBadge status="UNKNOWN" /> by asking the provider directly what
            actually happened, rather than guessing or blindly retrying.
          </p>
        </div>
        <button
          onClick={handleRun}
          disabled={running}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-primary to-secondary px-4 py-2.5 text-sm font-medium text-white shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60"
        >
          <motion.span animate={running ? { rotate: 360 } : {}} transition={{ repeat: running ? Infinity : 0, duration: 0.8, ease: 'linear' }}>
            <RefreshCw size={15} />
          </motion.span>
          {running ? 'Running…' : 'Run reconciliation now'}
        </button>
      </div>

      {reports && reports.length === 0 && (
        <GlassCard padding="lg">
          <EmptyState
            icon={<ShieldCheck size={20} />}
            title="Everything is perfectly in sync"
            description="No payments needed reconciliation — nothing is stuck in UNKNOWN right now."
          />
        </GlassCard>
      )}

      {reports && reports.length > 0 && (
        <GlassCard padding="none">
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-faint">
                <th className="px-5 py-3 font-medium">Payment</th>
                <th className="px-5 py-3 font-medium">Result</th>
                <th className="px-5 py-3 font-medium">Provider status</th>
                <th className="px-5 py-3 font-medium text-right">Resolved</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report, i) => {
                const mismatch = report.result.includes('MISMATCH')
                return (
                  <motion.tr
                    key={report.id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className={`border-b border-border/60 last:border-0 ${mismatch ? 'bg-danger-soft/30' : ''}`}
                  >
                    <td className="px-5 py-3">
                      <Link to={`/payments/${report.payment_id}`} className="font-mono text-xs text-text-muted hover:text-primary">
                        {report.payment_id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={report.result} />
                    </td>
                    <td className="px-5 py-3 text-text-muted">{report.provider_status ?? '—'}</td>
                    <td className="px-5 py-3 text-right text-xs text-text-faint">{formatDateTime(report.created_at)}</td>
                  </motion.tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </GlassCard>
      )}

      {!reports && (
        <GlassCard padding="lg">
          <EmptyState
            icon={<GitCompareArrows size={20} />}
            title="Ready to reconcile"
            description="Run reconciliation to resolve any payments stuck in UNKNOWN status."
          />
        </GlassCard>
      )}
    </div>
  )
}
