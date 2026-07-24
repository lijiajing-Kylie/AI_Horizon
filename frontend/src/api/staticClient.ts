/// <reference types="vite/client" />

/**
 * Static-data API client — mirrors the exports of ``client.ts`` but reads
 * from pre-generated JSON files (``docs/data/``) instead of the live API.
 *
 * Activated by the build-time env var ``VITE_STATIC_MODE=true``.
 * Write operations (favorites, prefs) fall back to ``localStorage``.
 */

import type {
  NewsItem, PaginatedResponse, TagCount, CategoryCount,
  TopicsResponse, TopicNewsResponse,
  DailyListResponse, DailyDetailResponse,
  Stats, Run, TopicPrefs, TopicPrefState, Paper, Report,
  GlobalSearchResponse,
} from './types'

/**
 * The data directory lives one level above the app directory.
 * E.g. app deployed to ``https://site/repo/app/`` → data at ``https://site/repo/data/``.
 */
const DATA_PREFIX = (() => {
  // window.location is available at runtime in all modern browsers
  const baseUrl = import.meta.env.BASE_URL
  // When VITE_STATIC_MODE is used, the data directory is always at
  // "../data/" relative to the app directory.
  if (baseUrl === './') {
    const current = window.location.href.replace(/\/*$/, '/')
    return new URL('../data/', current).toString()
  }
  return `${baseUrl}data/`
})()

// ── caching ──────────────────────────────────────────────────────────────────
// Cache these once per page load to avoid re-fetching on every call.

let _dailyList: DailyListResponse | null = null
let _topics: TopicsResponse | null = null
let _categories: CategoryCount[] | null = null
let _tags: TagCount[] | null = null
let _stats: Stats | null = null
let _runs: Run[] | null = null
let _runDates: string[] | null = null
let _papers: PaginatedResponse<Paper> | null = null
let _reports: PaginatedResponse<Report> | null = null
let _paperTopics: any = null
let _reportInstitutions: any[] | null = null
let _itemsIndex: { id: string; title: string; source_type: string; url: string; published_at: string; ai_score: number | null; ai_tags: string[]; run_date: string; category: string | null; topics: { slug: string; name: string }[] }[] | null = null

// ── fetch helpers ────────────────────────────────────────────────────────────

async function fetchJson<T>(path: string): Promise<T> {
  const url = `${DATA_PREFIX}${path}`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`Static data error: ${res.status} for ${url}`)
  }
  const text = await res.text()
  return text ? JSON.parse(text) : (null as T)
}

/** Cache-friendly JSON fetch with staleness guard. */
async function fetchWithCache<T>(cache: { value: T | null }, path: string, fetchFn?: () => Promise<T>): Promise<T> {
  if (cache.value !== null && cache.value !== undefined) {
    return cache.value
  }
  const data = await (fetchFn ? fetchFn() : fetchJson<T>(path))
  cache.value = data
  return data
}

// ── localStorage helpers for favorites / prefs ───────────────────────────────

const LS_KEYS = {
  favorites: 'horizon_favorites',
  paperFavorites: 'horizon_paper_favorites',
  reportFavorites: 'horizon_report_favorites',
  topicPrefs: 'horizon_topic_prefs',
}

function getLocal<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch { return fallback }
}

function setLocal(key: string, value: any) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* quota exceeded, ignore */ }
}

// ── filter & paginate helper ─────────────────────────────────────────────────

function applyPagination<T>(items: T[], page: number = 1, per_page: number = 20): PaginatedResponse<T> {
  const total = items.length
  const start = (page - 1) * per_page
  return {
    items: items.slice(start, start + per_page),
    total,
    page,
    per_page,
    pages: Math.max(1, Math.ceil(total / per_page)),
  }
}

function filterItems(items: NewsItem[], params?: {
  category?: string; tag?: string; source_type?: string;
  search?: string; min_score?: number;
}) {
  if (!params) return items
  return items.filter(it => {
    if (params.category && (it as any).category !== params.category && it.metadata?.category !== params.category) return false
    if (params.tag && !it.ai_tags.includes(params.tag)) return false
    if (params.source_type && it.source_type !== params.source_type) return false
    if (params.search) {
      const q = params.search.toLowerCase()
      if (!it.title.toLowerCase().includes(q) && !(it.ai_summary || '').toLowerCase().includes(q)) return false
    }
    if (params.min_score !== undefined && (it.ai_score ?? 0) < params.min_score) return false
    return true
  })
}

function sortItems(items: NewsItem[], sort: string = 'ai_score', order: string = 'desc') {
  const dir = order === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    const va = (a as any)[sort] ?? 0
    const vb = (b as any)[sort] ?? 0
    return va < vb ? dir : va > vb ? -dir : 0
  })
}

// ── get all items from all daily JSONs (lazy) ────────────────────────────────

let _allItems: NewsItem[] | null = null

async function getAllItems(): Promise<NewsItem[]> {
  if (_allItems) return _allItems
  // First, load the index to know which dates exist
  const index = await getItemsIndex()
  // Load items from the most recent 7 days' daily JSONs
  const dates = [...new Set(index.map(i => i.run_date))].slice(0, 7)
  const items: NewsItem[] = []
  for (const date of dates) {
    try {
      const daily = await fetchJson<DailyDetailResponse>(`daily-${date}.json`)
      if (daily.items) items.push(...daily.items)
    } catch { /* skip missing */ }
  }
  _allItems = items
  return items
}

async function getItemsIndex() {
  return fetchWithCache(
    { value: _itemsIndex },
    'items-index.json',
  )
}

// ── Exported API (mirrors client.ts) ────────────────────────────────────────

export async function getItems(params?: {
  run_date?: string; category?: string; tag?: string;
  source_type?: string; search?: string; min_score?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<PaginatedResponse<NewsItem>> {
  let items: NewsItem[]

  if (params?.run_date) {
    // Single-date fetch
    const daily = await fetchJson<DailyDetailResponse>(`daily-${params.run_date}.json`)
    items = daily.items || []
  } else {
    items = await getAllItems()
  }

  items = filterItems(items, params)
  items = sortItems(items, params?.sort, params?.order)
  return applyPagination(items, params?.page, params?.per_page)
}

export async function getItem(id: string): Promise<NewsItem | null> {
  // Find which date this item belongs to
  const index = await getItemsIndex()
  const entry = index.find(i => i.id === id)
  if (!entry) return null
  const daily = await fetchJson<DailyDetailResponse>(`daily-${entry.run_date}.json`)
  const item = daily.items.find(i => i.id === id)
  return item ?? null
}

export async function getTags(runDate?: string): Promise<TagCount[]> {
  if (runDate) {
    const daily = await fetchJson<DailyDetailResponse>(`daily-${runDate}.json`)
    return daily.tags || []
  }
  return fetchWithCache({ value: _tags }, 'tags.json')
}

export async function getCategories(runDate?: string): Promise<CategoryCount[]> {
  if (runDate) {
    const daily = await fetchJson<DailyDetailResponse>(`daily-${runDate}.json`)
    // daily detail doesn't have categories separately, compute from items
    const counts: Record<string, number> = {}
    for (const it of daily.items) {
      const cat = it.metadata?.category || 'unknown'
      counts[cat] = (counts[cat] || 0) + 1
    }
    return Object.entries(counts)
      .map(([category, count]) => ({ category, count }))
      .sort((a, b) => b.count - a.count)
  }
  return fetchWithCache({ value: _categories }, 'categories.json')
}

export async function getTopics(_params?: { include_blocked?: boolean }): Promise<TopicsResponse> {
  return fetchWithCache({ value: _topics }, 'topics.json')
}

export async function getTopicNews(slug: string, params?: {
  page?: number; per_page?: number; sort?: string; order?: string;
}): Promise<TopicNewsResponse> {
  const all = await getAllItems()
  const items = all.filter(it => it.topics?.some(t => t.slug === slug))
  const sorted = sortItems(items, params?.sort, params?.order)
  const paginated = applyPagination(sorted, params?.page, params?.per_page)
  return {
    topic: null, // not available from static data without a separate fetch
    ...paginated,
  }
}

export async function getDailyList(_limit?: number): Promise<DailyListResponse> {
  return fetchWithCache({ value: _dailyList }, 'daily.json')
}

export async function getDailyDetail(date: string): Promise<DailyDetailResponse> {
  const daily = await fetchJson<DailyDetailResponse>(`daily-${date}.json`)
  return daily
}

export async function getRunDates(_limit?: number): Promise<string[]> {
  return fetchWithCache({ value: _runDates }, 'runs-dates.json')
}

export async function getStats(runDate?: string): Promise<Stats> {
  if (runDate) {
    const daily = await fetchJson<DailyDetailResponse>(`daily-${runDate}.json`)
    return daily.stats
  }
  return fetchWithCache({ value: _stats }, 'stats.json')
}

export async function getRuns(_limit?: number): Promise<Run[]> {
  return fetchWithCache({ value: _runs }, 'runs.json')
}

export async function searchItems(q: string, limit?: number): Promise<NewsItem[]> {
  const all = await getAllItems()
  const ql = q.toLowerCase()
  return all
    .filter(it => it.title.toLowerCase().includes(ql) || (it.ai_summary || '').toLowerCase().includes(ql))
    .slice(0, limit ?? 20)
}

export async function globalSearch(params: {
  q: string; per_page?: number;
  news_page?: number; papers_page?: number; reports_page?: number;
  sort?: string; order?: string;
}): Promise<GlobalSearchResponse> {
  const ql = params.q.toLowerCase()
  const perPage = params.per_page ?? 20

  // Search news
  const allItems = await getAllItems()
  const matchedNews = allItems.filter(it =>
    it.title.toLowerCase().includes(ql) || (it.ai_summary || '').toLowerCase().includes(ql)
  )
  const newsPage = params.news_page ?? 1
  const newsStart = (newsPage - 1) * perPage

  // Search papers
  const papers = await getPapers()
  const matchedPapers = (papers?.items || []).filter(p =>
    p.title.toLowerCase().includes(ql) || p.abstract.toLowerCase().includes(ql)
  )
  const papersPage = params.papers_page ?? 1
  const papersStart = (papersPage - 1) * perPage

  // Search reports
  const reports = await getReports()
  const matchedReports = (reports?.items || []).filter(r =>
    r.title.toLowerCase().includes(ql) || (r.summary || '').toLowerCase().includes(ql)
  )
  const reportsPage = params.reports_page ?? 1
  const reportsStart = (reportsPage - 1) * perPage

  function section<T>(items: T[], total: number, page: number): any {
    return {
      items: items.slice(0, perPage),
      total,
      page,
      per_page: perPage,
      pages: Math.max(1, Math.ceil(total / perPage)),
    }
  }

  return {
    news: section(matchedNews.slice(newsStart, newsStart + perPage), matchedNews.length, newsPage),
    papers: section(matchedPapers.slice(papersStart, papersStart + perPage), matchedPapers.length, papersPage),
    reports: section(matchedReports.slice(reportsStart, reportsStart + perPage), matchedReports.length, reportsPage),
  }
}

// ── Favorites (localStorage) ────────────────────────────────────────────────

export async function putFavorite(itemId: string): Promise<{ item_id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.favorites, [])
  if (!favs.includes(itemId)) {
    favs.push(itemId)
    setLocal(LS_KEYS.favorites, favs)
  }
  return { item_id: itemId, is_favorited: true }
}

export async function deleteFavorite(itemId: string): Promise<{ item_id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.favorites, [])
  setLocal(LS_KEYS.favorites, favs.filter(id => id !== itemId))
  return { item_id: itemId, is_favorited: false }
}

export async function getFavorites(params?: { page?: number; per_page?: number }): Promise<PaginatedResponse<NewsItem>> {
  const favIds: string[] = getLocal(LS_KEYS.favorites, [])
  const all = await getAllItems()
  const items = all.filter(it => favIds.includes(it.id))
  return applyPagination(items, params?.page, params?.per_page)
}

export async function putPaperFavorite(paperId: string): Promise<{ id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.paperFavorites, [])
  if (!favs.includes(paperId)) { favs.push(paperId); setLocal(LS_KEYS.paperFavorites, favs) }
  return { id: paperId, is_favorited: true }
}

export async function deletePaperFavorite(paperId: string): Promise<{ id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.paperFavorites, [])
  setLocal(LS_KEYS.paperFavorites, favs.filter(id => id !== paperId))
  return { id: paperId, is_favorited: false }
}

export async function getPaperFavorites(params?: { page?: number; per_page?: number; source?: string }): Promise<PaginatedResponse<Paper>> {
  const favIds: string[] = getLocal(LS_KEYS.paperFavorites, [])
  const papers = await getPapers()
  const items = (papers?.items || []).filter(p => favIds.includes(p.id))
  return applyPagination(items, params?.page, params?.per_page)
}

export async function putReportFavorite(reportId: string): Promise<{ id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.reportFavorites, [])
  if (!favs.includes(reportId)) { favs.push(reportId); setLocal(LS_KEYS.reportFavorites, favs) }
  return { id: reportId, is_favorited: true }
}

export async function deleteReportFavorite(reportId: string): Promise<{ id: string; is_favorited: boolean }> {
  const favs: string[] = getLocal(LS_KEYS.reportFavorites, [])
  setLocal(LS_KEYS.reportFavorites, favs.filter(id => id !== reportId))
  return { id: reportId, is_favorited: false }
}

export async function getReportFavorites(params?: { page?: number; per_page?: number }): Promise<PaginatedResponse<Report>> {
  const favIds: string[] = getLocal(LS_KEYS.reportFavorites, [])
  const reports = await getReports()
  const items = (reports?.items || []).filter(r => favIds.includes(r.id))
  return applyPagination(items, params?.page, params?.per_page)
}

// ── Papers & Reports (read from static JSON) ────────────────────────────────

export async function getPapers(params?: {
  category?: string; source?: string; search?: string;
  topic_slug?: string; month?: string; sort?: string; order?: string;
  page?: number; per_page?: number;
}): Promise<PaginatedResponse<Paper>> {
  const data = await fetchWithCache({ value: _papers }, 'papers.json')
  if (!data) return { items: [], total: 0, page: 1, per_page: 20, pages: 0 }

  let items = data.items
  if (params?.source) items = items.filter(p => p.source === params.source)
  if (params?.category) items = items.filter(p => p.category === params.category)
  if (params?.search) {
    const q = params.search.toLowerCase()
    items = items.filter(p => p.title.toLowerCase().includes(q) || p.abstract.toLowerCase().includes(q))
  }
  if (params?.topic_slug) items = items.filter(p => p.topics?.some(t => t.slug === params!.topic_slug))
  if (params?.month) items = items.filter(p => p.published_at?.startsWith(params!.month!))

  const order = params?.order || 'desc'
  const sort = params?.sort || 'published_at'
  const dir = order === 'asc' ? 1 : -1
  items = [...items].sort((a, b) => {
    const va = ((a as any)[sort] ?? 0) as number
    const vb = ((b as any)[sort] ?? 0) as number
    return va < vb ? dir : va > vb ? -dir : 0
  })

  return applyPagination(items, params?.page, params?.per_page)
}

export async function getPaperMonthCounts(): Promise<{ ym: string; cnt: number }[]> {
  const data = await fetchWithCache({ value: _papers }, 'papers.json')
  if (!data) return []
  const counts: Record<string, number> = {}
  for (const p of data.items) {
    if (p.published_at) {
      const ym = p.published_at.slice(0, 7)
      counts[ym] = (counts[ym] || 0) + 1
    }
  }
  return Object.entries(counts)
    .map(([ym, cnt]) => ({ ym, cnt }))
    .sort((a, b) => b.ym.localeCompare(a.ym))
}

export async function getPaper(id: string): Promise<Paper | null> {
  const data = await fetchWithCache({ value: _papers }, 'papers.json')
  return data?.items.find(p => p.id === id) ?? null
}

export async function getPaperTopics() {
  return fetchWithCache({ value: _paperTopics }, 'paper-topics.json')
}

export async function getTopicPapers(slug: string, params?: {
  search?: string; source?: string; year?: number;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<{ topic: object; papers: Paper[]; total: number; page: number; per_page: number; pages: number }> {
  const paperData = await fetchWithCache({ value: _papers }, 'papers.json')
  const topicData: any = await fetchWithCache({ value: _paperTopics }, 'paper-topics.json')

  let papers = (paperData?.items || []).filter(p => p.topics?.some(t => t.slug === slug))
  if (params?.source) papers = papers.filter(p => p.source === params.source)
  if (params?.search) {
    const q = params.search.toLowerCase()
    papers = papers.filter(p => p.title.toLowerCase().includes(q))
  }
  if (params?.year) papers = papers.filter(p => (p.publication_year ?? 0) === params.year)

  const order = params?.order || 'desc'
  const sort = params?.sort || 'published_at'
  const dir = order === 'asc' ? 1 : -1
  papers = [...papers].sort((a, b) => {
    const va = ((a as any)[sort] ?? 0) as number
    const vb = ((b as any)[sort] ?? 0) as number
    return va < vb ? dir : va > vb ? -dir : 0
  })

  const page = params?.page ?? 1
  const perPage = params?.per_page ?? 20
  const start = (page - 1) * perPage

  let topic: object = {}
  for (const group of (topicData?.groups || [])) {
    const found = group.topics.find((t: any) => t.slug === slug)
    if (found) { topic = found; break }
  }

  return {
    topic,
    papers: papers.slice(start, start + perPage),
    total: papers.length,
    page,
    per_page: perPage,
    pages: Math.max(1, Math.ceil(papers.length / perPage)),
  }
}

export async function getReports(params?: {
  source?: string; institution?: string; category?: string; search?: string;
  sort?: string; order?: string; page?: number; per_page?: number;
}): Promise<PaginatedResponse<Report>> {
  const data = await fetchWithCache({ value: _reports }, 'reports.json')
  if (!data) return { items: [], total: 0, page: 1, per_page: 20, pages: 0 }

  let items = data.items
  if (params?.source) items = items.filter(r => r.source === params.source)
  if (params?.institution) items = items.filter(r => r.institution.includes(params.institution!))
  if (params?.search) {
    const q = params.search.toLowerCase()
    items = items.filter(r => r.title.toLowerCase().includes(q))
  }
  if (params?.category) items = items.filter(r => r.categories.includes(params.category!))

  const order = params?.order || 'desc'
  const sort = params?.sort || 'published_at'
  const dir = order === 'asc' ? 1 : -1
  items = [...items].sort((a, b) => {
    const va = ((a as any)[sort] ?? 0) as number
    const vb = ((b as any)[sort] ?? 0) as number
    return va < vb ? dir : va > vb ? -dir : 0
  })

  return applyPagination(items, params?.page, params?.per_page)
}

export async function getReport(id: string): Promise<Report | null> {
  const data = await fetchWithCache({ value: _reports }, 'reports.json')
  return data?.items.find(r => r.id === id) ?? null
}

export async function getReportInstitutions(source?: string) {
  let data = await fetchWithCache({ value: _reportInstitutions }, 'report-institutions.json')
  if (source) data = data.filter((d: any) => d.source === source)
  return data
}

// ── Topic preferences (localStorage) ────────────────────────────────────────

export async function getTopicPrefs(): Promise<TopicPrefs> {
  return getLocal(LS_KEYS.topicPrefs, { subscribed: [], blocked: [] })
}

export async function putTopicPref(slug: string, state: TopicPrefState | null): Promise<{ slug: string; state: TopicPrefState | null }> {
  const prefs = await getTopicPrefs()
  prefs.subscribed = prefs.subscribed.filter(s => s !== slug)
  prefs.blocked = prefs.blocked.filter(s => s !== slug)
  if (state === 'subscribed') prefs.subscribed.push(slug)
  if (state === 'blocked') prefs.blocked.push(slug)
  setLocal(LS_KEYS.topicPrefs, prefs)
  return { slug, state }
}
