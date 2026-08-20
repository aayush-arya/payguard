import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Plus, Receipt } from 'lucide-react'
import { listPayments } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { GlassCard, StatusBadge, SkeletonRow, ErrorState, EmptyState } from '../components/ui'
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
  const [searchParams, setSearchParams] = useSearchParams()
  const [showNewPayment, setShowNewPayment] = useState(searchParams.get('new') === '1')

  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setShowNewPayment(true)
      searchParams.delete('new')
      setSearchParams(searchParams, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">Payments</h1>
          <p className="mt-1 text-sm text-text-muted">{data ? `${data.total} total` : 'Loading…'}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowNewPayment(true)}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-text shadow-[0_4px_12px_-4px_rgba(27,23,18,0.25)] transition-transform hover:scale-[1.02] active:scale-[0.98]"
        >
          <Plus size={15} /> New payment
        </button>
      </div>

      <div className="flex gap-2 overflow-x-auto">
        <FilterChip label="All" active={status === ''} onClick={() => handleStatusChange('')} />
        {STATUSES.map((s) => (
          <FilterChip key={s} label={s} active={status === s} onClick={() => handleStatusChange(s)} />
        ))}
      </div>

      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <GlassCard padding="none">
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-faint">
                <th className="px-5 py-3 font-medium">Payment</th>
                <th className="px-5 py-3 font-medium">Amount</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium">Reference</th>
                <th className="px-5 py-3 font-medium text-right">Created</th>
              </tr>
            </thead>
            <tbody>
              {loading && Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} columns={5} />)}

              {data && data.items.length === 0 && !loading && (
                <tr>
                  <td colSpan={5}>
                    <EmptyState
                      icon={<Receipt size={18} />}
                      title="No payments match this filter"
                      description="Try a different status, or create a new payment to get started."
                    />
                  </td>
                </tr>
              )}

              {data?.items.map((payment, i) => (
                <motion.tr
                  key={payment.id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.02, duration: 0.2 }}
                  className="border-b border-border/60 transition-colors last:border-0 hover:bg-black/[0.02]"
                >
                  <td className="px-5 py-3">
                    <Link to={`/payments/${payment.id}`} className="font-mono text-xs text-text-muted hover:text-primary">
                      {payment.id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-5 py-3 tabular-nums text-text">{formatAmount(payment.amount, payment.currency)}</td>
                  <td className="px-5 py-3">
                    <StatusBadge status={payment.status} />
                  </td>
                  <td className="px-5 py-3 text-text-muted">{payment.merchant_reference ?? '—'}</td>
                  <td className="px-5 py-3 text-right text-xs text-text-faint">{formatDateTime(payment.created_at)}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
          </div>
        </GlassCard>
      )}

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-text-muted">
          <span className="tabular-nums">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded-lg border border-border px-3 py-1.5 transition-colors hover:border-border-strong disabled:opacity-30"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded-lg border border-border px-3 py-1.5 transition-colors hover:border-border-strong disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {showNewPayment && <NewPaymentModal onClose={() => setShowNewPayment(false)} onCreated={refetch} />}
    </div>
  )
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'border-primary/30 bg-primary-soft text-primary'
          : 'border-border text-text-muted hover:border-border-strong hover:text-text'
      }`}
    >
      {label.replace(/_/g, ' ')}
    </button>
  )
}
