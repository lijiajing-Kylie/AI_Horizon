// ---- Items ----

export interface SourceAttribution {
  count: number
  labels: string[]
  detail: { label: string; title: string; url: string }[]
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

export interface NewsItem {
  id: string
  source_type: string
  title: string
  url: string
  content: string | null
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
