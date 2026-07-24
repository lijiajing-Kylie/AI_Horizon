const STORAGE_KEY = 'horizon_user_id'

/** Fallback UUID v4 generator for non-secure contexts (e.g. LAN IPs like
 *  http://10.x.x.x where crypto.randomUUID() is unavailable). */
function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // crypto.getRandomValues fallback for non-secure contexts
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = typeof crypto !== 'undefined' && crypto.getRandomValues
      ? (crypto.getRandomValues(new Uint8Array(1))[0] & 15) | (c === 'x' ? 0 : 8)
      : (Math.random() * 16) | 0
    return r.toString(16)
  })
}

/** A per-browser anonymous id used to scope favorites/topic preferences.
 *
 * There is no login system — this is generated once and persisted in
 * localStorage. It identifies this browser, not a person: clearing site
 * data, switching browsers, or using a different device starts fresh. */
export function getOrCreateUserId(): string {
  const existing = localStorage.getItem(STORAGE_KEY)
  if (existing) return existing
  const id = generateUUID()
  localStorage.setItem(STORAGE_KEY, id)
  return id
}
