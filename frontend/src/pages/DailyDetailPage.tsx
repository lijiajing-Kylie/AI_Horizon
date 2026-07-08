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

// Map content-type topic slugs to 4 merged sections
const SECTION_MAP: Record<string, string> = {
  'model-release': '模型与产品',
  'product-update': '模型与产品',
  'benchmark-evaluation': '模型与产品',
  'industry-news': '行业与趋势',
  'phenomenon-trend': '行业与趋势',
  'policy-regulation': '行业与趋势',
  'paper-research': '论文与研究',
  'tutorial-practice': '技巧与观点',
  'expert-opinion': '技巧与观点',
}

const SECTION_ORDER = [
  'model-release', 'industry-news', 'paper-research', 'tutorial-practice',
]

function groupBySection(items: NewsItem[]): Map<string, NewsItem[]> {
  const map = new Map<string, NewsItem[]>()

  for (const item of items) {
    const contentTopics = (item.topics || []).filter(t => t.group_name === '内容形态')
    if (contentTopics.length > 0) {
      // Use the first content-type topic as primary section
      const slug = contentTopics[0].slug
      const section = SECTION_MAP[slug] || contentTopics[0].name
      if (!map.has(section)) map.set(section, [])
      map.get(section)!.push(item)
    } else {
      // Fallback: put items without content-type topic in 行业与趋势
      if (!map.has('行业与趋势')) map.set('行业与趋势', [])
      map.get('行业与趋势')!.push(item)
    }
  }

  return map
}

export default function DailyDetailPage() {
  const { date } = useParams<{ date: string }>()
  const { data, loading, error } = useApi(() => getDailyDetail(date!), [date])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!data) return <EmptyState icon="📭" title="暂无数据" />

  const { stats, items } = data
  const sections = groupBySection(items)
  const backTo: BackTarget = { path: `/daily/${date}`, label: '← 返回当日日报' }

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
      <div className="mb-6">
        <BackLink fallback={{ path: '/daily', label: '← 返回日报列表' }} />
        <h1 className="text-2xl font-bold text-gray-900">{formatDate(date!)} 日报</h1>

        {/* Overview stats */}
        {stats && (
          <div className="flex flex-wrap gap-4 mt-3 text-sm text-gray-500">
            <span>📊 精选 {stats.total_items} 条</span>
            {stats.avg_score !== null && <span>⭐ 均分 {stats.avg_score}</span>}
            <span>📂 {stats.source_types} 个来源类型</span>
          </div>
        )}
      </div>

      {/* Sections */}
      {items.length > 0 ? (
        orderedSections.map(([name, sectionItems]) => (
          <SectionBlock key={name} title={name} items={sectionItems} backTo={backTo} />
        ))
      ) : (
        <EmptyState icon="📭" title="该日暂无内容" />
      )}
    </div>
  )
}
