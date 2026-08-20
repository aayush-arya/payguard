import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Activity, ArrowUpRight, CheckCircle2, Plus, Wallet, XCircle } from 'lucide-react'
import { getDashboardSummary, listPayments } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { GlassCard, MetricCard, StatusBadge, SkeletonCard, SkeletonRow, ErrorState } from '../components/ui'
import { formatAmount, formatDateTime } from '../lib/format'

export function DashboardHome() {
  const { apiKey } = useAuth()
  const summary = useApiQuery(() => getDashboardSummary(apiKey!), [apiKey])
  const recent = useApiQuery(() => listPayments(apiKey!, { limit: 6 }), [apiKey])

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="flex flex-col gap-8">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-wrap items-end justify-between gap-4"
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">{greeting}, Admin</h1>
          <p className="mt-1 text-sm text-text-muted">
            Here's what's happening with your payment infrastructure today.
          </p>
        </div>
        <Link
          to="/payments?new=1"
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-primary to-secondary px-4 py-2.5 text-sm font-medium text-white shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.02] active:scale-[0.98]"
        >
          <Plus size={15} /> New Payment
        </Link>
      </motion.div>

      {summary.error && <ErrorState message={summary.error} onRetry={summary.refetch} />}

      {summary.loading && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {summary.data && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Total payments"
            value={summary.data.total_payments.toLocaleString()}
            icon={<Wallet size={16} />}
            accent="primary"
            sparkline={[3, 5, 4, 7, 6, 8, 9]}
          />
          <MetricCard
            label="Succeeded volume"
            value={formatAmount(summary.data.total_succeeded_amount, 'USD')}
            icon={<CheckCircle2 size={16} />}
            accent="success"
            sparkline={[2, 3, 3, 5, 6, 5, 7]}
          />
          <MetricCard
            label="Refunded volume"
            value={formatAmount(summary.data.total_refunded_amount, 'USD')}
            icon={<ArrowUpRight size={16} />}
            accent="secondary"
          />
          <MetricCard
            label="Needs reconciliation"
            value={String(summary.data.counts_by_status.UNKNOWN ?? 0)}
            icon={<Activity size={16} />}
            accent={summary.data.counts_by_status.UNKNOWN ? 'warning' : 'primary'}
            context="Payments in UNKNOWN status"
          />
        </div>
      )}

      <GlassCard padding="lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">Recent transactions</h2>
          <Link to="/payments" className="text-xs text-text-muted transition-colors hover:text-primary">
            View all →
          </Link>
        </div>

        {recent.error && <ErrorState message={recent.error} onRetry={recent.refetch} />}

        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <tbody>
            {recent.loading &&
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} columns={4} />)}

            {recent.data?.items.length === 0 && !recent.loading && (
              <tr>
                <td className="py-8 text-center text-sm text-text-muted">No payments yet.</td>
              </tr>
            )}

            {recent.data?.items.map((payment, i) => (
              <motion.tr
                key={payment.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.03 }}
                className="border-b border-border/60 last:border-0"
              >
                <td className="py-3 pr-4">
                  <Link to={`/payments/${payment.id}`} className="font-mono text-xs text-text-muted hover:text-primary">
                    {payment.id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="py-3 pr-4 tabular-nums text-text">{formatAmount(payment.amount, payment.currency)}</td>
                <td className="py-3 pr-4">
                  <StatusBadge status={payment.status} />
                </td>
                <td className="py-3 text-right text-xs text-text-faint">{formatDateTime(payment.created_at)}</td>
              </motion.tr>
            ))}
          </tbody>
        </table>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SystemHealthCard />
        <ActivityCard payments={recent.data?.items ?? []} declinedCount={summary.data?.counts_by_status.FAILED ?? 0} />
      </div>
    </div>
  )
}

function SystemHealthCard() {
  const services = [
    { name: 'API', uptime: 99.99 },
    { name: 'Database', uptime: 99.98 },
    { name: 'Payment providers', uptime: 99.97 },
    { name: 'Webhook processing', uptime: 99.99 },
  ]
  return (
    <GlassCard padding="lg">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text">System status</h2>
        <span className="flex items-center gap-1.5 text-xs text-success">
          <span className="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_6px_var(--color-success)]" />
          All systems operational
        </span>
      </div>
      <div className="flex flex-col gap-3">
        {services.map((s) => (
          <div key={s.name} className="flex items-center justify-between text-sm">
            <span className="text-text-muted">{s.name}</span>
            <div className="flex items-center gap-2">
              <div className="h-1 w-24 overflow-hidden rounded-full bg-white/5">
                <div className="h-full rounded-full bg-success" style={{ width: `${s.uptime}%` }} />
              </div>
              <span className="w-12 text-right tabular-nums text-text-faint">{s.uptime}%</span>
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  )
}

function ActivityCard({
  payments,
  declinedCount,
}: {
  payments: { id: string; status: string; amount: number; currency: string }[]
  declinedCount: number
}) {
  return (
    <GlassCard padding="lg">
      <h2 className="mb-4 text-sm font-semibold text-text">Activity</h2>
      <div className="flex flex-col gap-4">
        {payments.slice(0, 4).map((p) => (
          <div key={p.id} className="flex items-start gap-3">
            <span
              className={`mt-0.5 flex h-6 w-6 items-center justify-center rounded-full ${
                p.status === 'SUCCEEDED' ? 'bg-success-soft text-success' : p.status === 'FAILED' ? 'bg-danger-soft text-danger' : 'bg-primary-soft text-primary'
              }`}
            >
              {p.status === 'SUCCEEDED' ? <CheckCircle2 size={12} /> : p.status === 'FAILED' ? <XCircle size={12} /> : <Activity size={12} />}
            </span>
            <div className="text-sm">
              <p className="text-text">
                Payment {p.status === 'SUCCEEDED' ? 'succeeded' : p.status === 'FAILED' ? 'declined' : p.status.toLowerCase()}
              </p>
              <p className="text-xs text-text-faint">
                {p.id.slice(0, 8)}… · {formatAmount(p.amount, p.currency)}
              </p>
            </div>
          </div>
        ))}
        {payments.length === 0 && <p className="text-sm text-text-muted">No recent activity.</p>}
        {declinedCount > 0 && (
          <p className="mt-1 text-xs text-text-faint">{declinedCount} declined payment(s) total.</p>
        )}
      </div>
    </GlassCard>
  )
}
