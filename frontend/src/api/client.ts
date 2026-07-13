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
  Stats, Run, TopicPrefs, TopicPrefState,
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

// Topic preferences (subscribe / block)
export function getTopicPrefs() {
  return get<TopicPrefs>('/api/topic-prefs')
}

export function putTopicPref(slug: string, state: TopicPrefState | null) {
  return mutate<{ slug: string; state: TopicPrefState | null }>('PUT', `/api/topic-prefs/${slug}`, { state })
}
