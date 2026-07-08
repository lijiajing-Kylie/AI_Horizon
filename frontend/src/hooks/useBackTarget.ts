import { useLocation } from 'react-router-dom'
import type { BackTarget } from '../utils/backTo'

/** Resolves the active back target: state.backTo if the user navigated in
 * from another page in this app, otherwise the page's own logical-parent
 * fallback (e.g. a directly-opened/shared link has no state). */
export function useBackTarget(fallback: BackTarget): BackTarget {
  const location = useLocation()
  const state = location.state as { backTo?: BackTarget } | null
  return state?.backTo ?? fallback
}
