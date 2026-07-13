import { useState, useCallback, useEffect, useRef } from 'react'
import { getTopicPrefs, putTopicPref } from '../api/client'
import type { TopicPrefState } from '../api/types'

function toMap(data: { subscribed: string[]; blocked: string[] }): Record<string, TopicPrefState> {
  const map: Record<string, TopicPrefState> = {}
  data.subscribed.forEach(slug => { map[slug] = 'subscribed' })
  data.blocked.forEach(slug => { map[slug] = 'blocked' })
  return map
}

/** Single source of truth for the current user's topic preferences.
 *
 * Every TopicPrefButtons instance on a page (e.g. the same topic can show
 * up both in a "subscribed/blocked" summary and in the full topic list) reads
 * from and writes through this shared map, so toggling one instance is
 * immediately reflected in every other instance of the same topic. */
export function useTopicPrefsState() {
  const [prefs, setPrefs] = useState<Record<string, TopicPrefState> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    getTopicPrefs()
      .then(data => {
        if (!mounted.current) return
        setPrefs(toMap(data))
        setLoading(false)
      })
      .catch(err => {
        if (!mounted.current) return
        setError(err.message)
        setLoading(false)
      })
    return () => { mounted.current = false }
  }, [])

  const setPref = useCallback(async (slug: string, next: TopicPrefState | null) => {
    setPrefs(prev => {
      const updated = { ...(prev || {}) }
      if (next === null) delete updated[slug]
      else updated[slug] = next
      return updated
    })
    try {
      await putTopicPref(slug, next)
    } catch {
      // Revert to server truth on failure rather than guessing the prior state.
      const data = await getTopicPrefs()
      if (mounted.current) setPrefs(toMap(data))
    }
  }, [])

  return { prefs, loading, error, setPref }
}
