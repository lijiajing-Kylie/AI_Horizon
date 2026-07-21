import type { NewsItem } from '../api/types'

// Map content-type topic slugs to 4 merged sections.
export const SECTION_MAP: Record<string, string> = {
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

export const SECTION_ORDER = [
  'model-release', 'industry-news', 'paper-research', 'tutorial-practice',
]

// The 4 section display names in canonical order (derived from SECTION_ORDER).
export const SECTION_NAMES = SECTION_ORDER.map(slug => SECTION_MAP[slug])

export function groupBySection(items: NewsItem[]): Map<string, NewsItem[]> {
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
