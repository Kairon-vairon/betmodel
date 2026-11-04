import { useCallback, useEffect, useState } from 'react'

type Result<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Fetch on mount and every `refreshMs`. Keeps the last good data if a refresh fails. */
export function useApi<T>(load: () => Promise<T>, refreshMs?: number): Result<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let cancelled = false
    load()
      .then((value) => {
        if (cancelled) return
        setData(value)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [load, tick])

  useEffect(() => {
    if (!refreshMs) return
    const timer = window.setInterval(reload, refreshMs)
    return () => window.clearInterval(timer)
  }, [refreshMs, reload])

  return { data, error, loading, reload }
}
