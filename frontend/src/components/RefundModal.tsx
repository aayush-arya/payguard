import { useState, type FormEvent } from 'react'
import { refundPayment, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Modal, useToast } from './ui'

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
  const { push } = useToast()
  const [amount, setAmount] = useState(String(remaining))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await refundPayment(apiKey!, paymentId, Number(amount))
      push('Refund created', 'success')
      onRefunded()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create refund.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Refund payment">
      <p className="-mt-2 mb-4 text-sm text-text-muted">
        Up to {remaining} {currency} remains refundable.
      </p>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm text-text-muted">
          Amount (minor units)
          <input
            type="number"
            min={1}
            max={remaining}
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="rounded-lg border border-border bg-white/[0.03] px-3 py-2 text-sm text-text outline-none transition-colors focus:border-primary/50"
          />
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-2 text-sm text-text-muted transition-colors hover:bg-white/5"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-gradient-to-r from-primary to-secondary px-4 py-2 text-sm font-medium text-white transition-transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
          >
            {submitting ? 'Refunding…' : 'Refund'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
