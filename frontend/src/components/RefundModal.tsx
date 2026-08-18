import { useState, type FormEvent } from 'react'
import { refundPayment, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export function RefundModal({
  paymentId,
  remaining,
  currency,
  onClose,
  onRefunded,
}: {
  paymentId: string
  remaining: number
  currency: string
  onClose: () => void
  onRefunded: () => void
}) {
  const { apiKey } = useAuth()
  const [amount, setAmount] = useState(String(remaining))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await refundPayment(apiKey!, paymentId, Number(amount))
      onRefunded()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create refund.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg dark:bg-slate-900">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Refund payment</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Up to {remaining} {currency} remains refundable.
        </p>
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
            Amount (minor units)
            <input
              type="number"
              min={1}
              max={remaining}
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50 dark:bg-white dark:text-slate-900"
            >
              {submitting ? 'Refunding…' : 'Refund'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
