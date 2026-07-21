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

// Collapsed section titles, tracked outside React state so a section stays
// collapsed across navigating to a detail page and back (which remounts
// this component and would otherwise reset a local useState to its default).
const collapsedSections = new Set<string>()

export default function SectionBlock({ title, items, backTo }: SectionBlockProps) {
  const [expanded, setExpanded] = useState(() => !collapsedSections.has(title))

  if (items.length === 0) return null

  const toggle = () => {
    setExpanded(prev => {
      const next = !prev
      if (next) collapsedSections.delete(title)
      else collapsedSections.add(title)
      return next
    })
  }

  return (
    <section className="mb-8">
      <h2
        onClick={toggle}
        className="flex items-center gap-1.5 text-sm font-semibold mb-4 pb-2 border-b-2 border-[var(--accent)] text-[var(--accent)] cursor-pointer select-none"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 shrink-0" />
        )}
        {expanded ? (
          <>
            {title} <span className="text-sm font-normal text-[var(--muted)] ml-2">{items.length} 条</span>
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
