import { useCallback, useEffect, useState } from 'react'
import { ApiError } from './api'

interface QueryState<T> {
  data: T | null
  error: string | null
  loading: boolean
  refetch: () => void
}

// A minimal fetch-on-mount-and-deps-change hook -- this dashboard has no
// need for React Query's caching/retry/invalidation machinery, every page
// here just wants "load this once, show a spinner, let me refetch."
export function useApiQuery<T>(fn: () => Promise<T>, deps: unknown[]): QueryState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fn()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Something went wrong.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  useEffect(() => load(), [load])

  return { data, error, loading, refetch: () => setNonce((n) => n + 1) }
}
