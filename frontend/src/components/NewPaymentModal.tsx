import { useState, type FormEvent } from 'react'
import { createPayment, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Modal, useToast } from './ui'

const DEMO_TOKENS = [
  { value: 'pm_demo_ok', label: 'Succeeds' },
  { value: 'pm_demo_declined', label: 'Declined' },
  { value: 'pm_demo_temp_fail', label: 'Temporary failure' },
  { value: 'pm_demo_timeout', label: 'Timeout (resolves via reconciliation)' },
]

const inputClass =
  'rounded-lg border border-border bg-white/[0.03] px-3 py-2 text-sm text-text outline-none transition-colors focus:border-primary/50'

export function NewPaymentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { apiKey } = useAuth()
  const { push } = useToast()
  const [amount, setAmount] = useState('1000')
  const [currency, setCurrency] = useState('USD')
  const [token, setToken] = useState(DEMO_TOKENS[0].value)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      // A unique suffix keeps every demo submission its own payment --
      // MockProvider's idempotency layer is keyed by the request's
      // Idempotency-Key already (set by the api client), but the token
      // itself only needs to *contain* the scenario marker, so this stays
      // readable while still being unique per submission.
      const uniqueToken = `${token}_${crypto.randomUUID().slice(0, 8)}`
      await createPayment(apiKey!, { amount: Number(amount), currency, token: uniqueToken })
      push('Payment created', 'success')
      onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create payment.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="New payment">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm text-text-muted">
          Amount (minor units, e.g. cents)
          <input
            type="number"
            min={1}
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-text-muted">
          Currency
          <input
            required
            maxLength={3}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            className={`${inputClass} uppercase`}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-text-muted">
          Demo scenario
          <select value={token} onChange={(e) => setToken(e.target.value)} className={inputClass}>
            {DEMO_TOKENS.map((opt) => (
              <option key={opt.value} value={opt.value} className="bg-surface-solid">
                {opt.label}
              </option>
            ))}
          </select>
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
            {submitting ? 'Creating…' : 'Create payment'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
