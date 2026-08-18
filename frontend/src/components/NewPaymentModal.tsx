import { useState, type FormEvent } from 'react'
import { createPayment, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

const DEMO_TOKENS = [
  { value: 'pm_demo_ok', label: 'Succeeds' },
  { value: 'pm_demo_declined', label: 'Declined' },
  { value: 'pm_demo_temp_fail', label: 'Temporary failure' },
  { value: 'pm_demo_timeout', label: 'Timeout (resolves via reconciliation)' },
]

export function NewPaymentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { apiKey } = useAuth()
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
      onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create payment.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-lg dark:bg-slate-900">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">New payment</h2>
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
            Amount (minor units, e.g. cents)
            <input
              type="number"
              min={1}
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
            Currency
            <input
              required
              maxLength={3}
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm uppercase outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
            Demo scenario
            <select
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              {DEMO_TOKENS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
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
              {submitting ? 'Creating…' : 'Create payment'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
