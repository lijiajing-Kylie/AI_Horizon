import { Link } from 'react-router-dom'
import { useBackTarget } from '../hooks/useBackTarget'
import type { BackTarget } from '../utils/backTo'

interface BackLinkProps {
  fallback: BackTarget
  className?: string
}

const DEFAULT_CLASS_NAME = 'text-sm text-blue-600 hover:text-blue-700 mb-2 inline-block'

/** Renders the resolved back target (state.backTo, or fallback when the
 * page was opened directly with no in-app navigation history). */
export default function BackLink({ fallback, className }: BackLinkProps) {
  const backTo = useBackTarget(fallback)
  return (
    <Link to={backTo.path} className={className ?? DEFAULT_CLASS_NAME}>
      {backTo.label}
    </Link>
  )
}
