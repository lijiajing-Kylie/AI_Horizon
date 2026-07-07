const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText} for ${path}`)
  }
  return res.json()
}

import type {
  NewsItem, PaginatedResponse, TagCount, CategoryCount,
  TopicsResponse, TopicNewsResponse,
  DailyListResponse, DailyDetailResponse,
  Stats, Run
} from './types'

// Items
export function getItems(params?: {
  run_date?: string; category?: string; tag?: string;
  source_type?: string; search?: string; min_score?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}) {
  return get<PaginatedResponse<NewsItem>>('/api/items', params as Record<string, string | number | undefined>)
}

export function getItem(id: string) {
  return get<NewsItem>(`/api/items/${id}`)
}

// Tags & Categories
export function getTags(runDate?: string) {
  return get<TagCount[]>('/api/tags', { run_date: runDate })
}

export function getCategories(runDate?: string) {
  return get<CategoryCount[]>('/api/categories', { run_date: runDate })
}

// Topics
export function getTopics() {
  return get<TopicsResponse>('/api/topics')
}

export function getTopicNews(slug: string, params?: {
  page?: number; per_page?: number; sort?: string; order?: string;
}) {
  return get<TopicNewsResponse>(`/api/topics/${slug}/news`, params as Record<string, string | number | undefined>)
}

// Daily
export function getDailyList(limit?: number) {
  return get<DailyListResponse>('/api/daily', { limit })
}

export function getDailyDetail(date: string) {
  return get<DailyDetailResponse>(`/api/daily/${date}`)
}

// Stats
export function getStats(runDate?: string) {
  return get<Stats>('/api/stats', { run_date: runDate })
}

// Runs
export function getRuns(limit?: number) {
  return get<Run[]>('/api/runs', { limit })
}

// Search
export function searchItems(q: string, limit?: number) {
  return get<NewsItem[]>('/api/search', { q, limit })
}
