import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { checkApiHealth, getDashboardSummary, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

// Public by design -- packages/../scripts/seed_demo_merchant.py seeds a
// merchant with exactly this key so anyone opening the dashboard can try
// it immediately. It only ever touches MockProvider and fake money; never
// reuse this pattern for a real merchant's key, which is a secret shown
// once (scripts/seed_merchant.py) and never displayed in source again.
const DEMO_API_KEY = 'sk_test_demo_public_9f3a7c2e1b6d4f8a0c5e9b2d7f1a4c6e'

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

  async function attemptConnect(key: string) {
    setError(null)
    setChecking(true)
    try {
      // Not just format validation -- prove the key actually authenticates
      // before storing it, so a typo doesn't get "connected" only to 401 on
      // every subsequent call.
      await getDashboardSummary(key)
      connect(key)
      navigate('/', { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError
          ? 'That API key was rejected. Double-check it and try again.'
          : "Couldn't reach the API. Is it running?",
      )
    } finally {
      setChecking(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void attemptConnect(apiKey.trim())
  }

  function handleTryDemo() {
    setApiKey(DEMO_API_KEY)
    void attemptConnect(DEMO_API_KEY)
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

        <button
          type="button"
          onClick={handleTryDemo}
          disabled={checking}
          className="mt-6 w-full rounded-md border border-dashed border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          {checking ? 'Connecting…' : 'Try the demo'}
        </button>
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
          Public demo key, connected to fake data and MockProvider only:{' '}
          <code className="break-all rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">{DEMO_API_KEY}</code>
        </p>

        <div className="mt-6 flex items-center gap-3 text-xs text-slate-400 dark:text-slate-500">
          <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
          or use your own key
          <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
        </div>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <input
            type="password"
            required
            placeholder="sk_test_..."
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
          create your own test merchant and print its API key.
        </p>
      </div>
    </div>
  )
}
