import { Link } from 'react-router-dom'
import { useBackTarget } from '../hooks/useBackTarget'
import type { BackTarget } from '../utils/backTo'

interface BackLinkProps {
  fallback: BackTarget
  className?: string
}

function BackArrow() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
    >
      <path d="M9 3L5 7L9 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const DEFAULT_CLASS_NAME = 'inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80 mb-2 transition-opacity'

/** Renders the resolved back target (state.backTo, or fallback when the
 * page was opened directly with no in-app navigation history). */
export default function BackLink({ fallback, className }: BackLinkProps) {
  const backTo = useBackTarget(fallback)
  return (
    <Link to={backTo.path} className={className ?? DEFAULT_CLASS_NAME}>
      <BackArrow />
      {backTo.label}
    </Link>
  )
}
