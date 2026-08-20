import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ShieldCheck, Sparkles } from 'lucide-react'
import { checkApiHealth, getDashboardSummary, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AmbientBackground } from '../components/ui'

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
    <div className="relative flex min-h-screen items-center justify-center px-4 text-text">
      <AmbientBackground />
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="w-full max-w-sm rounded-2xl border border-border bg-surface p-8 shadow-2xl backdrop-blur-xl"
      >
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary text-white shadow-[0_0_20px_-4px_var(--color-primary)]">
            <ShieldCheck size={18} strokeWidth={2.25} />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-text">PayGuard</p>
            <p className="text-[10px] uppercase tracking-wider text-text-faint">Payment Infrastructure</p>
          </div>
        </div>

        <p className="mt-5 text-sm text-text-muted">Enter a merchant API key to connect.</p>

        {apiReachable === false && (
          <p className="mt-4 rounded-lg border border-warning/20 bg-warning-soft px-3 py-2 text-xs text-warning">
            Can't reach the PayGuard API. Is it running?
          </p>
        )}

        <button
          type="button"
          onClick={handleTryDemo}
          disabled={checking}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-secondary px-3 py-2.5 text-sm font-medium text-white shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50"
        >
          <Sparkles size={14} />
          {checking ? 'Connecting…' : 'Try the demo'}
        </button>
        <p className="mt-2 text-[11px] text-text-faint">
          Public demo key, connected to fake data and MockProvider only:{' '}
          <code className="break-all rounded bg-white/5 px-1 py-0.5">{DEMO_API_KEY}</code>
        </p>

        <div className="mt-6 flex items-center gap-3 text-[11px] text-text-faint">
          <div className="h-px flex-1 bg-border" />
          or use your own key
          <div className="h-px flex-1 bg-border" />
        </div>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <input
            type="password"
            required
            placeholder="sk_test_..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="rounded-lg border border-border bg-white/[0.03] px-3 py-2 text-sm text-text outline-none transition-colors focus:border-primary/50"
          />
          {error && <p className="text-sm text-danger">{error}</p>}
          <button
            type="submit"
            disabled={checking || !apiKey.trim()}
            className="rounded-lg border border-border-strong px-3 py-2 text-sm font-medium text-text transition-colors hover:bg-white/5 disabled:opacity-50"
          >
            {checking ? 'Connecting…' : 'Connect'}
          </button>
        </form>

        <p className="mt-4 text-[11px] text-text-faint">
          Run <code className="rounded bg-white/5 px-1 py-0.5">python scripts/seed_merchant.py</code> to create
          your own test merchant and print its API key.
        </p>
      </motion.div>
    </div>
  )
}
