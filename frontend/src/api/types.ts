// ---- Items ----

export interface SourceAttribution {
  count: number
  labels: string[]
  detail: { label: string; title: string; url: string }[]
}

export interface SourceProvenanceEntry {
  source_name: string
  source_url: string
  source_type: string
  role: string
  title: string
  published_at: string | null
  is_primary: boolean
  discovered_via: string
  confidence: number
}

export interface SourceProvenance {
  primary_source_name: string
  primary_source_url: string
  primary_source_type: string
  source_count: number
  sources: SourceProvenanceEntry[]
}

export interface ContentLangBlock {
  title: string
  summary: string
  reason: string
  community_discussion: string
}

export interface ContentBlock {
  original_language: string
  default_language: string
  is_ai_translated: boolean
  content: Record<string, ContentLangBlock>
  enrichment_sources: EnrichmentSource[]
  discussion_url?: string
  source_provenance?: SourceProvenance
  source_attribution?: SourceAttribution
}

export interface EnrichmentSource {
  url: string
  title: string
}

export interface Topic {
  id: number
  name: string
  slug: string
  group_name: string
  description: string
  confidence?: number
  reason?: string
  count?: number
}

export interface ArticleImage {
  url: string
  alt: string
  caption: string
  source: string
}

export interface NewsItem {
  id: string
  source_type: string
  title: string
  url: string
  content: string | null
  raw_content: string | null
  clean_content: string | null
  raw_html: string | null
  display_html: string | null
  display_html_zh: string | null
  cover_image: string | null
  images: ArticleImage[]
  author: string | null
  published_at: string
  fetched_at: string
  ai_relevant: boolean | null
  ai_score: number | null
  ai_reason: string | null
  ai_summary: string | null
  ai_tags: string[]
  metadata: Record<string, any>
  topics: Topic[]
  run_date: string
  content_block?: ContentBlock
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

// ---- Tags & Categories ----

export interface TagCount {
  tag: string
  count: number
}

export interface CategoryCount {
  category: string
  count: number
}

// ---- Topics ----

export interface TopicGroup {
  group_name: string
  topics: Topic[]
}

export interface TopicsResponse {
  groups: TopicGroup[]
}

export interface TopicDetail {
  id: number
  name: string
  slug: string
  group_name: string
  description: string
}

export interface TopicNewsResponse {
  topic: TopicDetail | null
  items: NewsItem[]
  total: number
  page: number
  per_page: number
  pages: number
}

// ---- Daily ----

export interface DailyReport {
  date: string
  total_fetched: number
  total_selected: number
  languages: string[]
}

export interface DailyListResponse {
  reports: DailyReport[]
}

export interface DailyDetailResponse {
  date: string
  stats: Stats
  tags: TagCount[]
  topics: TopicsResponse
  items: NewsItem[]
  total: number
}

// ---- Stats ----

export interface Stats {
  total_items: number
  avg_score: number | null
  max_score: number | null
  source_types: number
}

// ---- Runs ----

export interface Run {
  date: string
  total_fetched: number
  total_selected: number
  languages: string[]
  created_at: string
}
