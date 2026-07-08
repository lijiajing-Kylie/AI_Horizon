import { useState, useEffect, useCallback, useRef } from 'react'

interface UseApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiState<T> & { refetch: () => void } {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null })
  const initialRef = useRef(true)

  const fetchData = useCallback(() => {
    // Preserve previous data during refetch so the UI doesn't flash empty
    setState(prev => ({
      data: initialRef.current ? null : prev.data,
      loading: true,
      error: null,
    }))
    fetcher()
      .then(data => {
        initialRef.current = false
        setState({ data, loading: false, error: null })
      })
      .catch(err => {
        initialRef.current = false
        setState({ data: null, loading: false, error: err.message })
      })
  }, deps)

  useEffect(() => { fetchData() }, [fetchData])

  return { ...state, refetch: fetchData }
}
