const STORAGE_KEY = 'horizon_user_id'

/** A per-browser anonymous id used to scope favorites/topic preferences.
 *
 * There is no login system — this is generated once and persisted in
 * localStorage. It identifies this browser, not a person: clearing site
 * data, switching browsers, or using a different device starts fresh. */
export function getOrCreateUserId(): string {
  const existing = localStorage.getItem(STORAGE_KEY)
  if (existing) return existing
  const id = crypto.randomUUID()
  localStorage.setItem(STORAGE_KEY, id)
  return id
}
