import { getOrCreateUserId } from '../utils/userId'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    })
  }
  return url.toString()
}

async function handle<T>(res: Response, path: string): Promise<T> {
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText} for ${path}`)
  }
  const text = await res.text()
  return text ? JSON.parse(text) : (null as unknown as T)
}

// Sends X-User-Id on every request (the anonymous per-browser id — see
// utils/userId.ts) so endpoints that support personalization (is_favorited,
// blocked-topic filtering) apply it automatically. The backend treats the
// header as entirely optional, so this has no effect on endpoints that
// don't look at it.
async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    headers: { 'X-User-Id': getOrCreateUserId() },
  })
  return handle<T>(res, path)
}

/** PUT/DELETE against a caller-scoped resource. */
async function mutate<T>(method: 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const res = await fetch(buildUrl(path), {
    method,
    headers: {
      'X-User-Id': getOrCreateUserId(),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return handle<T>(res, path)
}

import type {
  NewsItem, PaginatedResponse, TagCount, CategoryCount,
  TopicsResponse, TopicNewsResponse,
  DailyListResponse, DailyDetailResponse,
  Stats, Run, TopicPrefs, TopicPrefState, Paper, Report,
  GlobalSearchResponse,
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
  // include_debug is harmless to send outside dev — the backend only ever
  // attaches the debug block when it's also running with
  // HORIZON_API_ENV=development — but we only ask for it in dev to avoid
  // bloating the response for a field the production UI never renders.
  return get<NewsItem>(`/api/items/${id}`, {
    include_debug: import.meta.env.DEV ? 'true' : undefined,
  })
}

// Tags & Categories
export function getTags(runDate?: string) {
  return get<TagCount[]>('/api/tags', { run_date: runDate })
}

export function getCategories(runDate?: string) {
  return get<CategoryCount[]>('/api/categories', { run_date: runDate })
}

// Topics
export function getTopics(params?: { include_blocked?: boolean }) {
  return get<TopicsResponse>('/api/topics', params as Record<string, string | number | undefined>)
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

/** Dates (YYYY-MM-DD) that have pipeline data, newest first. */
export function getRunDates(limit?: number) {
  return get<string[]>('/api/runs/dates', { limit })
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

// Global Search
export function globalSearch(params: {
  q: string
  per_page?: number
  news_page?: number
  papers_page?: number
  reports_page?: number
  sort?: string
  order?: string
}) {
  return get<GlobalSearchResponse>('/api/global-search', params as Record<string, string | number | undefined>)
}

// Favorites
export function putFavorite(itemId: string) {
  return mutate<{ item_id: string; is_favorited: boolean }>('PUT', `/api/favorites/${itemId}`)
}

export function deleteFavorite(itemId: string) {
  return mutate<{ item_id: string; is_favorited: boolean }>('DELETE', `/api/favorites/${itemId}`)
}

export function getFavorites(params?: { page?: number; per_page?: number }) {
  return get<PaginatedResponse<NewsItem>>('/api/favorites', params as Record<string, string | number | undefined>)
}

// Paper Favorites
export function putPaperFavorite(paperId: string) {
  return mutate<{ id: string; is_favorited: boolean }>('PUT', `/api/favorites/papers/${paperId}`)
}

export function deletePaperFavorite(paperId: string) {
  return mutate<{ id: string; is_favorited: boolean }>('DELETE', `/api/favorites/papers/${paperId}`)
}

export function getPaperFavorites(params?: { page?: number; per_page?: number; source?: string }) {
  return get<PaginatedResponse<Paper>>('/api/favorites/papers', params as Record<string, string | number | undefined>)
}

// Report Favorites
export function putReportFavorite(reportId: string) {
  return mutate<{ id: string; is_favorited: boolean }>('PUT', `/api/favorites/reports/${reportId}`)
}

export function deleteReportFavorite(reportId: string) {
  return mutate<{ id: string; is_favorited: boolean }>('DELETE', `/api/favorites/reports/${reportId}`)
}

export function getReportFavorites(params?: { page?: number; per_page?: number }) {
  return get<PaginatedResponse<Report>>('/api/favorites/reports', params as Record<string, string | number | undefined>)
}

// Papers
export function getPapers(params?: {
  category?: string; source?: string; search?: string;
  topic_slug?: string; month?: string; sort?: string; order?: string;
  page?: number; per_page?: number;
}) {
  return get<PaginatedResponse<Paper>>('/api/papers', params as Record<string, string | number | undefined>)
}

export function getPaperMonthCounts() {
  return get<{ ym: string; cnt: number }[]>('/api/papers/month-counts')
}

export function getPaper(id: string) {
  return get<Paper>(`/api/papers/${id}`)
}

export function getPaperTopics() {
  return get<{ groups: { group_name: string; topics: { id: number; name: string; slug: string; group_name: string; description: string; paper_count: number }[] }[] }>('/api/paper-topics')
}

export function getTopicPapers(slug: string, params?: {
  search?: string; source?: string; year?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}) {
  return get<{ topic: object; papers: Paper[]; total: number; page: number; per_page: number; pages: number }>(`/api/paper-topics/${slug}/papers`, params as Record<string, string | number | undefined>)
}

// Reports
export function getReports(params?: {
  source?: string; institution?: string; category?: string; search?: string;
  sort?: string; order?: string; page?: number; per_page?: number;
}) {
  return get<PaginatedResponse<Report>>('/api/reports', params as Record<string, string | number | undefined>)
}

export function getReport(id: string) {
  return get<Report>(`/api/reports/${id}`)
}

export interface InstitutionInfo {
  institution: string
  source: string
  count: number
}

export function getReportInstitutions(source?: string) {
  return get<InstitutionInfo[]>('/api/reports/institutions', { source } as Record<string, string | undefined>)
}

// Topic preferences (subscribe / block)
export function getTopicPrefs() {
  return get<TopicPrefs>('/api/topic-prefs')
}

export function putTopicPref(slug: string, state: TopicPrefState | null) {
  return mutate<{ slug: string; state: TopicPrefState | null }>('PUT', `/api/topic-prefs/${slug}`, { state })
}
