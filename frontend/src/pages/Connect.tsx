import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { checkApiHealth, getDashboardSummary } from '../lib/api'
import { useAuth } from '../lib/auth'

export function Connect() {
  const { connect } = useAuth()
  const navigate = useNavigate()
  const [apiKey, setApiKey] = useState('')
  const [apiReachable, setApiReachable] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    checkApiHealth().then(setApiReachable)
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setChecking(true)
    try {
      // Not just format validation -- prove the key actually authenticates
      // before storing it, so a typo doesn't get "connected" only to 401 on
      // every subsequent call.
      await getDashboardSummary(apiKey.trim())
      connect(apiKey.trim())
      navigate('/', { replace: true })
    } catch {
      setError('That API key was rejected. Double-check it and try again.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 dark:bg-slate-950">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">PayGuard Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Enter a merchant API key to connect.
        </p>

        {apiReachable === false && (
          <p className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
            Can't reach the PayGuard API. Is it running?
          </p>
        )}

        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-3">
          <input
            type="password"
            required
            placeholder="pk_test_..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={checking || !apiKey.trim()}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50 dark:bg-white dark:text-slate-900"
          >
            {checking ? 'Connecting…' : 'Connect'}
          </button>
        </form>

        <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
          Run <code className="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">python scripts/seed_merchant.py</code> to
          create a test merchant and print its API key.
        </p>
      </div>
    </div>
  )
}
