import { Link } from 'react-router-dom'
import type { Topic } from '../api/types'
import { backToState, type BackTarget } from '../utils/backTo'

interface TopicCardProps {
  topic: Topic
  backTo?: BackTarget
}

export default function TopicCard({ topic, backTo }: TopicCardProps) {
  return (
    <Link
      to={`/topics/${topic.slug}`}
      state={backToState(backTo)}
      className="group glass rounded-2xl p-4 block hover:shadow-lg transition-all"
    >
      <h3 className="text-[17px] font-medium text-[var(--ink)] mb-1 leading-snug group-hover:text-[var(--accent)] transition-colors">{topic.name}</h3>
      <p className="text-sm text-[var(--muted)] mb-2 line-clamp-2">{topic.description}</p>
      {topic.count !== undefined && (
        <span className="text-xs font-medium text-[var(--accent)]">{topic.count} 条新闻</span>
      )}
    </Link>
  )
}
