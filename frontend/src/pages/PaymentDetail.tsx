import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  Fingerprint,
  Layers,
  Lock,
  Undo2,
  XCircle,
} from 'lucide-react'
import { capturePayment, getPaymentDetail, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApiQuery } from '../lib/useApiQuery'
import { GlassCard, StatusBadge, Timeline, ErrorState, useToast, type TimelineItem } from '../components/ui'
import { RefundModal } from '../components/RefundModal'
import { formatAmount, formatDateTime } from '../lib/format'
import type { PaymentAttempt, PaymentDetail as PaymentDetailType, Refund } from '../lib/types'

const REFUNDABLE_STATUSES = new Set(['SUCCEEDED', 'REFUND_FAILED', 'REFUND_PENDING'])

const LIFECYCLE_STEPS = ['CREATED', 'PROCESSING', 'SUCCEEDED'] as const

export function PaymentDetail() {
  const { paymentId } = useParams<{ paymentId: string }>()
  const { apiKey } = useAuth()
  const { push } = useToast()
  const {
    data: payment,
    error,
    loading,
    refetch,
  } = useApiQuery(() => getPaymentDetail(apiKey!, paymentId!), [apiKey, paymentId])
  const [showRefund, setShowRefund] = useState(false)
  const [capturing, setCapturing] = useState(false)

  async function handleCapture() {
    setCapturing(true)
    try {
      await capturePayment(apiKey!, paymentId!)
      push('Payment captured', 'success')
      refetch()
    } catch (err) {
      push(err instanceof ApiError ? err.message : 'Failed to capture payment.', 'error')
    } finally {
      setCapturing(false)
    }
  }

  if (loading) return <DetailSkeleton />
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!payment) return null

  const reservedRefunds = payment.refunds
    .filter((r) => r.status === 'PENDING' || r.status === 'SUCCEEDED')
    .reduce((sum, r) => sum + r.amount, 0)
  const remainingRefundable = payment.amount - reservedRefunds

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link
          to="/payments"
          className="inline-flex items-center gap-1.5 text-sm text-text-muted transition-colors hover:text-text"
        >
          <ArrowLeft size={14} /> All payments
        </Link>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-mono text-xs text-text-faint">{payment.id}</p>
            <div className="mt-2 flex items-center gap-3">
              <span className="text-3xl font-semibold tabular-nums tracking-tight text-text">
                {formatAmount(payment.amount, payment.currency)}
              </span>
              <StatusBadge status={payment.status} />
            </div>
          </div>
          <div className="flex gap-2">
            {payment.status === 'PROCESSING' && (
              <button
                onClick={handleCapture}
                disabled={capturing}
                className="rounded-lg bg-gradient-to-r from-primary to-secondary px-4 py-2 text-sm font-medium text-white shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              >
                {capturing ? 'Capturing…' : 'Capture'}
              </button>
            )}
            {REFUNDABLE_STATUSES.has(payment.status) && remainingRefundable > 0 && (
              <button
                onClick={() => setShowRefund(true)}
                className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium text-text transition-colors hover:border-border-strong hover:bg-white/5"
              >
                <Undo2 size={14} /> Refund
              </button>
            )}
          </div>
        </div>
      </div>

      <LifecycleStepper status={payment.status} />

      <IdempotencyInspector payment={payment} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GlassCard padding="lg">
          <h2 className="mb-4 text-sm font-semibold text-text">Event timeline</h2>
          <Timeline items={eventsToTimeline(payment.events)} />
        </GlassCard>

        <GlassCard padding="lg">
          <h2 className="mb-4 text-sm font-semibold text-text">Provider attempts</h2>
          <AttemptsTable attempts={payment.attempts} />
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GlassCard padding="lg">
          <h2 className="mb-4 text-sm font-semibold text-text">Refunds</h2>
          <RefundsTable refunds={payment.refunds} currency={payment.currency} />
        </GlassCard>

        <GlassCard padding="lg">
          <h2 className="mb-4 text-sm font-semibold text-text">Ledger entries</h2>
          <LedgerTable entries={payment.ledger_entries} currency={payment.currency} />
        </GlassCard>
      </div>

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

function LifecycleStepper({ status }: { status: string }) {
  const failed = status === 'FAILED' || status === 'UNKNOWN'
  const currentIndex = LIFECYCLE_STEPS.indexOf(status as (typeof LIFECYCLE_STEPS)[number])

  return (
    <GlassCard padding="lg">
      <div className="flex items-center">
        {LIFECYCLE_STEPS.map((step, i) => {
          const reached = !failed && currentIndex >= i
          const isCurrent = !failed && currentIndex === i
          return (
            <div key={step} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-2">
                <motion.span
                  animate={isCurrent ? { scale: [1, 1.12, 1] } : {}}
                  transition={{ duration: 1.6, repeat: isCurrent ? Infinity : 0 }}
                  className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${
                    reached ? 'border-primary bg-primary-soft text-primary' : 'border-border text-text-faint'
                  }`}
                >
                  {reached ? <CheckCircle2 size={16} /> : <Circle size={14} />}
                </motion.span>
                <span className={`text-[11px] ${reached ? 'text-text' : 'text-text-faint'}`}>{step}</span>
              </div>
              {i < LIFECYCLE_STEPS.length - 1 && (
                <div className="mx-2 h-px flex-1 bg-border">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: currentIndex > i ? '100%' : 0 }}
                    className="h-px bg-primary"
                  />
                </div>
              )}
            </div>
          )
        })}
        {failed && (
          <div className="ml-4 flex items-center gap-2 text-danger">
            <XCircle size={16} />
            <span className="text-xs font-medium">{status}</span>
          </div>
        )}
      </div>
    </GlassCard>
  )
}

/** Uses the payment's real attempt/ledger data to demonstrate the
 * idempotency guarantee (Phase 2/3): exactly one provider attempt and a
 * balanced ledger regardless of retries. Does not simulate live requests
 * -- that would mean fabricating numbers this specific payment never
 * actually saw. The concurrent-retry proof this panel describes is real
 * and lives in tests/concurrency/test_payment_api_race.py (100 identical
 * concurrent requests -> exactly 1 payment, exactly 1 provider attempt). */
function IdempotencyInspector({ payment }: { payment: PaymentDetailType }) {
  const attemptCount = payment.attempts.length
  const debitTotal = payment.ledger_entries.filter((e) => e.direction === 'DEBIT').reduce((s, e) => s + e.amount, 0)
  const creditTotal = payment.ledger_entries.filter((e) => e.direction === 'CREDIT').reduce((s, e) => s + e.amount, 0)
  const balanced = payment.ledger_entries.length === 0 || debitTotal === creditTotal

  return (
    <GlassCard padding="lg" className="relative overflow-hidden">
      <div className="mb-5 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-secondary-soft text-secondary">
          <Fingerprint size={16} />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-text">Idempotency inspector</h2>
          <p className="text-xs text-text-muted">
            A single database constraint guarantees this outcome, not application-level checking
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 items-center gap-6 md:grid-cols-[1fr_auto_1fr]">
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06 }}
              className="flex items-center gap-2 rounded-lg border border-border bg-white/[0.02] px-3 py-1.5 text-xs text-text-muted"
            >
              <Layers size={12} className="text-text-faint" />
              POST /v1/payments{' '}
              <span className="text-text-faint">(retry {i + 1})</span>
            </motion.div>
          ))}
        </div>

        <div className="flex flex-col items-center gap-2 text-text-faint">
          <div className="hidden h-px w-10 bg-gradient-to-r from-transparent to-border-strong md:block" />
          <div className="flex flex-col items-center gap-1 rounded-xl border border-primary/25 bg-primary-soft px-4 py-3 text-primary">
            <Lock size={16} />
            <span className="text-[10px] font-medium uppercase tracking-wide">Idempotency engine</span>
          </div>
          <div className="hidden h-px w-10 bg-gradient-to-r from-border-strong to-transparent md:block" />
        </div>

        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-success/20 bg-success-soft/40 p-5 text-center">
          <CheckCircle2 size={22} className="text-success" />
          <div>
            <p className="text-lg font-semibold tabular-nums text-text">1 payment</p>
            <p className="text-xs text-text-muted">
              {attemptCount} provider attempt{attemptCount === 1 ? '' : 's'} · ledger{' '}
              {balanced ? 'balanced' : 'unbalanced'}
            </p>
          </div>
        </div>
      </div>

      <p className="mt-5 text-xs text-text-faint">
        Proven under real concurrency, not just this single request:{' '}
        <code className="rounded bg-white/5 px-1 py-0.5">tests/concurrency/test_payment_api_race.py</code>{' '}
        fires 100 identical requests at the real HTTP boundary and verifies exactly one{' '}
        <code className="rounded bg-white/5 px-1 py-0.5">payment_intents</code> row and one provider
        authorization result — via a single unique database constraint, never a check-then-act race.
      </p>
    </GlassCard>
  )
}

function eventsToTimeline(events: PaymentDetailType['events']): TimelineItem[] {
  return events.map((e) => ({
    id: e.id,
    icon: <CheckCircle2 size={13} />,
    title: `${e.from_status ?? 'start'} → ${e.to_status}`,
    subtitle: `via ${e.actor}`,
    meta: formatDateTime(e.created_at),
    tone: e.to_status === 'SUCCEEDED' ? 'success' : e.to_status === 'FAILED' ? 'danger' : 'default',
  }))
}

function AttemptsTable({ attempts }: { attempts: PaymentAttempt[] }) {
  if (attempts.length === 0) return <p className="text-sm text-text-muted">No provider attempts.</p>
  return (
    <div className="flex flex-col gap-2">
      {attempts.map((a) => (
        <div key={a.id} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-text-faint">#{a.attempt_number}</span>
            <span className="text-text">{a.provider_name}</span>
          </div>
          <div className="flex items-center gap-2">
            {a.failure_classification && (
              <span className="text-xs text-text-faint">{a.failure_classification}</span>
            )}
            <StatusBadge status={a.status} />
          </div>
        </div>
      ))}
    </div>
  )
}

function RefundsTable({ refunds, currency }: { refunds: Refund[]; currency: string }) {
  if (refunds.length === 0) return <p className="text-sm text-text-muted">No refunds.</p>
  return (
    <div className="flex flex-col gap-2">
      {refunds.map((r) => (
        <div key={r.id} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-sm">
          <span className="font-mono text-xs text-text-faint">{r.id.slice(0, 8)}…</span>
          <span className="tabular-nums text-text">{formatAmount(r.amount, currency)}</span>
          <StatusBadge status={r.status} />
        </div>
      ))}
    </div>
  )
}

function LedgerTable({ entries, currency }: { entries: PaymentDetailType['ledger_entries']; currency: string }) {
  if (entries.length === 0)
    return (
      <p className="text-sm text-text-muted">
        No ledger entries yet — entries are written when a payment or refund settles.
      </p>
    )
  return (
    <div className="flex flex-col gap-2">
      {entries.map((entry) => (
        <div key={entry.id} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-sm">
          <span className="text-text">{entry.account}</span>
          <span className={entry.direction === 'DEBIT' ? 'text-primary' : 'text-secondary'}>
            {entry.direction}
          </span>
          <span className="tabular-nums text-text-muted">{formatAmount(entry.amount, currency)}</span>
        </div>
      ))}
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="h-20 animate-pulse rounded-2xl bg-white/[0.03]" />
      <div className="h-24 animate-pulse rounded-2xl bg-white/[0.03]" />
      <div className="h-48 animate-pulse rounded-2xl bg-white/[0.03]" />
    </div>
  )
}
