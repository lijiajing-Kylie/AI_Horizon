import { useState, useEffect, useCallback } from 'react'

interface UseApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiState<T> & { refetch: () => void } {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null })

  const fetchData = useCallback(() => {
    setState({ data: null, loading: true, error: null })
    fetcher()
      .then(data => setState({ data, loading: false, error: null }))
      .catch(err => setState({ data: null, loading: false, error: err.message }))
  }, deps)

  useEffect(() => { fetchData() }, [fetchData])

  return { ...state, refetch: fetchData }
}
