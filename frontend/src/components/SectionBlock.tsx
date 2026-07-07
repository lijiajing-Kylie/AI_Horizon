import type { NewsItem } from '../api/types'
import ItemCard from './ItemCard'

interface SectionBlockProps {
  title: string
  items: NewsItem[]
}

export default function SectionBlock({ title, items }: SectionBlockProps) {
  if (items.length === 0) return null

  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-gray-800 mb-4 pb-2 border-b-2 border-blue-400">
        {title} <span className="text-sm font-normal text-gray-400 ml-2">{items.length} 条</span>
      </h2>
      <div className="space-y-3">
        {items.map(item => (
          <ItemCard key={item.id} item={item} showTopics={false} />
        ))}
      </div>
    </section>
  )
}
