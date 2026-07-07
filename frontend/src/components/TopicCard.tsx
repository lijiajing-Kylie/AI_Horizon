import { Link } from 'react-router-dom'
import type { Topic } from '../api/types'

interface TopicCardProps {
  topic: Topic
  from?: string
}

export default function TopicCard({ topic, from }: TopicCardProps) {
  const to = from ? `/topics/${topic.slug}?from=${encodeURIComponent(from)}` : `/topics/${topic.slug}`
  return (
    <Link
      to={to}
      className="block border border-gray-200 rounded-lg p-4 hover:shadow-md hover:border-blue-300 transition-all"
    >
      <h3 className="font-medium text-gray-900 mb-1">{topic.name}</h3>
      <p className="text-sm text-gray-500 mb-2 line-clamp-2">{topic.description}</p>
      {topic.count !== undefined && (
        <span className="text-xs font-medium text-blue-600">{topic.count} 条新闻</span>
      )}
    </Link>
  )
}
