import { useParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getDailyDetail } from '../api/client'
import { formatDate } from '../utils/date'
import SectionBlock from '../components/SectionBlock'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { NewsItem } from '../api/types'

// Map content-type topic slugs to section names
const SECTION_MAP: Record<string, string> = {
  'model-release': '模型发布/更新',
  'product-update': '产品发布/更新',
  'industry-news': '行业动态',
  'paper-research': '论文研究',
  'tutorial-practice': '技巧与观点',
  'expert-opinion': '技巧与观点',
  'phenomenon-trend': '现象与趋势',
  'policy-regulation': '政策监管',
  'benchmark-evaluation': '评测基准',
}

const SECTION_ORDER = [
  'model-release', 'product-update', 'industry-news',
  'paper-research', 'tutorial-practice', 'expert-opinion',
  'phenomenon-trend', 'policy-regulation', 'benchmark-evaluation',
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
      // Fallback: put items without content-type topic in 行业动态
      if (!map.has('行业动态')) map.set('行业动态', [])
      map.get('行业动态')!.push(item)
    }
  }

  return map
}

export default function DailyDetailPage() {
  const { date } = useParams<{ date: string }>()
  const { data, loading, error } = useApi(() => getDailyDetail(date!), [date])

  if (loading) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!data) return <EmptyState icon="📭" title="暂无数据" />

  const { stats, items } = data
  const sections = groupBySection(items)

  // Render sections in a defined order
  const orderedSections: [string, NewsItem[]][] = []
  const usedSections = new Set<string>()
  for (const slug of SECTION_ORDER) {
    const name = SECTION_MAP[slug]
    const sectionItems = sections.get(name)
    if (sectionItems && sectionItems.length > 0) {
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
        <Link to="/daily" className="text-sm text-blue-600 hover:text-blue-700 mb-2 inline-block">← 返回日报列表</Link>
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
          <SectionBlock key={name} title={name} items={sectionItems} />
        ))
      ) : (
        <EmptyState icon="📭" title="该日暂无内容" />
      )}
    </div>
  )
}
