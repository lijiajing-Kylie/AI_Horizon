import { useEffect, useRef } from 'react'

const SCROLL_PREFIX = 'scrollPos:'

/**
 * Persists scroll position (keyed on `key`) in sessionStorage and restores
 * it when the page content is tall enough to support the saved position.
 *
 * Unlike the previous approach, this does NOT depend on a `ready` signal
 * from the component — it polls via requestAnimationFrame until the scroll
 * target is valid, so it works regardless of when/how data loads.
 *
 * @param key  Unique identifier for this page+state (pathname + search).
 */
export function useScrollRestoration(key: string): void {
  const keyRef = useRef(key)
  const savedRef = useRef<number | null>(null)
  const restoredRef = useRef(false)

  keyRef.current = key

  // ── Read saved position on mount / key change ──────────────────────────
  useEffect(() => {
    savedRef.current = null
    restoredRef.current = false
    try {
      const raw = sessionStorage.getItem(SCROLL_PREFIX + key)
      if (raw !== null) {
        savedRef.current = parseInt(raw, 10)
      }
    } catch {
      // sessionStorage unavailable — silently skip
    }
  }, [key])

  // ── Restore via animation-frame polling ────────────────────────────────
  // Instead of relying on a `ready` boolean from the caller, we keep trying
  // each frame until the page is tall enough to accommodate the saved scroll
  // position.  This handles async data loading, layout shifts, and images
  // that load progressively.
  useEffect(() => {
    const pos = savedRef.current
    if (pos === null || pos <= 0) return

    let raf: number

    const poll = () => {
      // Already restored in a previous tick — stop.
      if (restoredRef.current) return
      // Wait until the document is tall enough.
      if (document.documentElement.scrollHeight > pos) {
        window.scrollTo({ top: pos, behavior: 'instant' as ScrollBehavior })
        restoredRef.current = true
        return
      }
      raf = requestAnimationFrame(poll)
    }

    raf = requestAnimationFrame(poll)
    return () => cancelAnimationFrame(raf)
  }, [key])

  // ── Persist scroll position on every scroll event ──────────────────────
  useEffect(() => {
    const handleScroll = () => {
      // Don't overwrite the saved position with 0 while we're still
      // attempting restoration on the current key.
      if (!restoredRef.current) return
      try {
        sessionStorage.setItem(SCROLL_PREFIX + keyRef.current, String(window.scrollY))
      } catch {
        // silently skip
      }
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])
}