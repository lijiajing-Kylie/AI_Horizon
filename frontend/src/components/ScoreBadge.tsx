interface ScoreBadgeProps {
  score: number | null
  size?: 'sm' | 'md'
}

export default function ScoreBadge({ score, size = 'md' }: ScoreBadgeProps) {
  if (score === null || score === undefined) {
    return <span className={`inline-block rounded font-bold text-white bg-gray-400 ${size === 'sm' ? 'px-1.5 py-0 text-xs' : 'px-2 py-0.5 text-sm'}`}>?</span>
  }

  const color = score >= 8 ? 'bg-emerald-500' : score >= 6 ? 'bg-amber-500' : 'bg-gray-400'

  return (
    <span className={`inline-block rounded font-bold text-white ${color} ${size === 'sm' ? 'px-1.5 py-0 text-xs' : 'px-2 py-0.5 text-sm'}`}>
      {score.toFixed(1)}
    </span>
  )
}
