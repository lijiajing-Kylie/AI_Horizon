import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { NewsItem } from '../api/types'
import ItemCard from './ItemCard'
import type { BackTarget } from '../utils/backTo'

interface SectionBlockProps {
  title: string
  items: NewsItem[]
  backTo?: BackTarget
}

export default function SectionBlock({ title, items, backTo }: SectionBlockProps) {
  const [expanded, setExpanded] = useState(true)

  if (items.length === 0) return null

  return (
    <section className="mb-8">
      <h2
        onClick={() => setExpanded(prev => !prev)}
        className="flex items-center gap-1.5 text-lg font-semibold text-gray-800 mb-4 pb-2 border-b-2 border-blue-400 cursor-pointer select-none"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
        )}
        {expanded ? (
          <>
            {title} <span className="text-sm font-normal text-gray-400 ml-2">{items.length} 条</span>
          </>
        ) : (
          <span>{title}（{items.length}）</span>
        )}
      </h2>
      {expanded && (
        <div className="space-y-3">
          {items.map(item => (
            <ItemCard key={item.id} item={item} showTopics={false} backTo={backTo} />
          ))}
        </div>
      )}
    </section>
  )
}
