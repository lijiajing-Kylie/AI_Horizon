/**
 * API client — transparently switches between live API and static JSON.
 *
 * When ``VITE_STATIC_MODE=true`` (build-time env var, used on GitHub Pages),
 * all read operations fetch from pre-generated JSON files in ``docs/data/``
 * and write operations (favorites, prefs) fall back to ``localStorage``.
 *
 * When ``VITE_STATIC_MODE`` is unset (local dev), the original live API
 * client is used against the FastAPI backend.
 */

import { getOrCreateUserId } from '../utils/userId'

const STATIC_MODE = import.meta.env.VITE_STATIC_MODE === 'true'

// ── Live API client (original) ──────────────────────────────────────────────

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

async function liveGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    headers: { 'X-User-Id': getOrCreateUserId() },
  })
  return handle<T>(res, path)
}

async function liveMutate<T>(method: 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
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

// ── Static client ───────────────────────────────────────────────────────────

import * as staticClient from './staticClient'

// ── Types ───────────────────────────────────────────────────────────────────

import type {
  NewsItem, PaginatedResponse, TagCount, CategoryCount,
  TopicsResponse, TopicNewsResponse,
  DailyListResponse, DailyDetailResponse,
  Stats, Run, TopicPrefs, TopicPrefState, Paper, Report,
  GlobalSearchResponse,
} from './types'

// ── Exported API ────────────────────────────────────────────────────────────

export function getItems(params?: {
  run_date?: string; category?: string; tag?: string;
  source_type?: string; search?: string; min_score?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<PaginatedResponse<NewsItem>> {
  return STATIC_MODE
    ? staticClient.getItems(params)
    : liveGet('/api/items', params as Record<string, string | number | undefined>)
}

export function getItem(id: string): Promise<NewsItem> {
  return STATIC_MODE
    ? staticClient.getItem(id) as Promise<NewsItem>
    : liveGet<NewsItem>(`/api/items/${id}`, {
        include_debug: import.meta.env.DEV ? 'true' : undefined,
      })
}

export function getTags(runDate?: string): Promise<TagCount[]> {
  return STATIC_MODE
    ? staticClient.getTags(runDate)
    : liveGet<TagCount[]>('/api/tags', { run_date: runDate })
}

export function getCategories(runDate?: string): Promise<CategoryCount[]> {
  return STATIC_MODE
    ? staticClient.getCategories(runDate)
    : liveGet<CategoryCount[]>('/api/categories', { run_date: runDate })
}

export function getTopics(params?: { include_blocked?: boolean }): Promise<TopicsResponse> {
  return STATIC_MODE
    ? staticClient.getTopics(params)
    : liveGet<TopicsResponse>('/api/topics', params as Record<string, string | number | undefined>)
}

export function getTopicNews(slug: string, params?: {
  page?: number; per_page?: number; sort?: string; order?: string;
}): Promise<TopicNewsResponse> {
  return STATIC_MODE
    ? staticClient.getTopicNews(slug, params)
    : liveGet<TopicNewsResponse>(`/api/topics/${slug}/news`, params as Record<string, string | number | undefined>)
}

export function getDailyList(limit?: number): Promise<DailyListResponse> {
  return STATIC_MODE
    ? staticClient.getDailyList(limit)
    : liveGet<DailyListResponse>('/api/daily', { limit })
}

export function getDailyDetail(date: string): Promise<DailyDetailResponse> {
  return STATIC_MODE
    ? staticClient.getDailyDetail(date)
    : liveGet<DailyDetailResponse>(`/api/daily/${date}`)
}

export function getRunDates(limit?: number): Promise<string[]> {
  return STATIC_MODE
    ? staticClient.getRunDates(limit)
    : liveGet<string[]>('/api/runs/dates', { limit })
}

export function getStats(runDate?: string): Promise<Stats> {
  return STATIC_MODE
    ? staticClient.getStats(runDate)
    : liveGet<Stats>('/api/stats', { run_date: runDate })
}

export function getRuns(limit?: number): Promise<Run[]> {
  return STATIC_MODE
    ? staticClient.getRuns(limit)
    : liveGet<Run[]>('/api/runs', { limit })
}

export function searchItems(q: string, limit?: number): Promise<NewsItem[]> {
  return STATIC_MODE
    ? staticClient.searchItems(q, limit)
    : liveGet<NewsItem[]>('/api/search', { q, limit })
}

export function globalSearch(params: {
  q: string; per_page?: number; news_page?: number; papers_page?: number;
  reports_page?: number; sort?: string; order?: string;
}): Promise<GlobalSearchResponse> {
  return STATIC_MODE
    ? staticClient.globalSearch(params)
    : liveGet<GlobalSearchResponse>('/api/global-search', params as Record<string, string | number | undefined>)
}

// Favorites

export function putFavorite(itemId: string): Promise<{ item_id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.putFavorite(itemId)
    : liveMutate('PUT', `/api/favorites/${itemId}`)
}

export function deleteFavorite(itemId: string): Promise<{ item_id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.deleteFavorite(itemId)
    : liveMutate('DELETE', `/api/favorites/${itemId}`)
}

export function getFavorites(params?: { page?: number; per_page?: number }): Promise<PaginatedResponse<NewsItem>> {
  return STATIC_MODE
    ? staticClient.getFavorites(params)
    : liveGet<PaginatedResponse<NewsItem>>('/api/favorites', params as Record<string, string | number | undefined>)
}

export function putPaperFavorite(paperId: string): Promise<{ id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.putPaperFavorite(paperId)
    : liveMutate('PUT', `/api/favorites/papers/${paperId}`)
}

export function deletePaperFavorite(paperId: string): Promise<{ id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.deletePaperFavorite(paperId)
    : liveMutate('DELETE', `/api/favorites/papers/${paperId}`)
}

export function getPaperFavorites(params?: { page?: number; per_page?: number; source?: string }): Promise<PaginatedResponse<Paper>> {
  return STATIC_MODE
    ? staticClient.getPaperFavorites(params)
    : liveGet<PaginatedResponse<Paper>>('/api/favorites/papers', params as Record<string, string | number | undefined>)
}

export function putReportFavorite(reportId: string): Promise<{ id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.putReportFavorite(reportId)
    : liveMutate('PUT', `/api/favorites/reports/${reportId}`)
}

export function deleteReportFavorite(reportId: string): Promise<{ id: string; is_favorited: boolean }> {
  return STATIC_MODE
    ? staticClient.deleteReportFavorite(reportId)
    : liveMutate('DELETE', `/api/favorites/reports/${reportId}`)
}

export function getReportFavorites(params?: { page?: number; per_page?: number }): Promise<PaginatedResponse<Report>> {
  return STATIC_MODE
    ? staticClient.getReportFavorites(params)
    : liveGet<PaginatedResponse<Report>>('/api/favorites/reports', params as Record<string, string | number | undefined>)
}

// Papers & Reports

export function getPapers(params?: {
  category?: string; source?: string; search?: string;
  topic_slug?: string; month?: string; sort?: string; order?: string;
  page?: number; per_page?: number;
}): Promise<PaginatedResponse<Paper>> {
  return STATIC_MODE
    ? staticClient.getPapers(params)
    : liveGet<PaginatedResponse<Paper>>('/api/papers', params as Record<string, string | number | undefined>)
}

export function getPaperMonthCounts(): Promise<{ ym: string; cnt: number }[]> {
  return STATIC_MODE
    ? staticClient.getPaperMonthCounts()
    : liveGet<{ ym: string; cnt: number }[]>('/api/papers/month-counts')
}

export function getPaper(id: string): Promise<Paper | null> {
  return STATIC_MODE
    ? staticClient.getPaper(id)
    : liveGet<Paper>(`/api/papers/${id}`)
}

export function getPaperTopics(): Promise<{ groups: { group_name: string; topics: any[] }[] }> {
  return STATIC_MODE
    ? staticClient.getPaperTopics()
    : liveGet('/api/paper-topics')
}

export function getTopicPapers(slug: string, params?: {
  search?: string; source?: string; year?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<{ topic: object; papers: Paper[]; total: number; page: number; per_page: number; pages: number }> {
  return STATIC_MODE
    ? staticClient.getTopicPapers(slug, params)
    : liveGet(`/api/paper-topics/${slug}/papers`, params as Record<string, string | number | undefined>)
}

export function getReports(params?: {
  source?: string; institution?: string; category?: string; search?: string;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<PaginatedResponse<Report>> {
  return STATIC_MODE
    ? staticClient.getReports(params)
    : liveGet<PaginatedResponse<Report>>('/api/reports', params as Record<string, string | number | undefined>)
}

export function getReport(id: string): Promise<Report | null> {
  return STATIC_MODE
    ? staticClient.getReport(id)
    : liveGet<Report>(`/api/reports/${id}`)
}

export function getReportInstitutions(source?: string): Promise<{ institution: string; source: string; count: number }[]> {
  return STATIC_MODE
    ? staticClient.getReportInstitutions(source)
    : liveGet<{ institution: string; source: string; count: number }[]>('/api/reports/institutions', { source } as Record<string, string | undefined>)
}

// Topic preferences

export function getTopicPrefs(): Promise<TopicPrefs> {
  return STATIC_MODE
    ? staticClient.getTopicPrefs()
    : liveGet<TopicPrefs>('/api/topic-prefs')
}

export function putTopicPref(slug: string, state: TopicPrefState | null): Promise<{ slug: string; state: TopicPrefState | null }> {
  return STATIC_MODE
    ? staticClient.putTopicPref(slug, state)
    : liveMutate('PUT', `/api/topic-prefs/${slug}`, { state })
}
