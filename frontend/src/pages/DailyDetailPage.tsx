import { useParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getDailyDetail } from '../api/client'
import { formatDate } from '../utils/date'
import SectionBlock from '../components/SectionBlock'
import BackLink from '../components/BackLink'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { NewsItem } from '../api/types'
import type { BackTarget } from '../utils/backTo'
import { SECTION_MAP, SECTION_ORDER, groupBySection } from '../utils/sections'

export default function DailyDetailPage() {
  const { date } = useParams<{ date: string }>()
  const { data, loading, error } = useApi(() => getDailyDetail(date!), [date])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!data) return <EmptyState title="暂无数据" />

  const { items } = data
  const sections = groupBySection(items)
  const backTo: BackTarget = { path: `/daily/${date}`, label: '返回当日日报' }

  // Render sections in a defined order
  const orderedSections: [string, NewsItem[]][] = []
  const usedSections = new Set<string>()
  for (const slug of SECTION_ORDER) {
    const name = SECTION_MAP[slug]
    const sectionItems = sections.get(name)
    if (sectionItems && sectionItems.length > 0 && !usedSections.has(name)) {
      orderedSections.push([name, sectionItems])
      usedSections.add(name)
    }
  }
  // Add any remaining sections not in the order
  for (const [name, sectionItems] of sections.entries()) {
    if (!usedSections.has(name)) {
      orderedSections.push([name, sectionItems])
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <BackLink
          fallback={{ path: '/daily', label: '返回' }}
          className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80 mb-2"
        />
        <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">DAILY REPORT</p>
        <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide">{formatDate(date!)} 日报</h1>

      </div>

      {/* Sections */}
      {items.length > 0 ? (
        orderedSections.map(([name, sectionItems]) => (
          <SectionBlock key={name} title={name} items={sectionItems} backTo={backTo} />
        ))
      ) : (
        <EmptyState title="该日暂无内容" />
      )}
    </div>
  )
}
