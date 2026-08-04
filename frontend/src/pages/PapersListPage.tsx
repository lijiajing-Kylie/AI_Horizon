import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getPapers, getPaperFavorites } from '../api/client'
import PaperCard from '../components/PaperCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import CategoryFilterMenu from '../components/CategoryFilterMenu'
import { ArrowDown, Search } from 'lucide-react'
import type { Paper } from '../api/types'

type PaperSource = 'openalex' | 'arxiv' | 'arxiv_fin'

// 板块顺序：AI+金融 → 最新论文(arXiv 每周精选) → 经典论文
const PAPER_SOURCES: PaperSource[] = ['arxiv_fin', 'arxiv', 'openalex']

/** Merge partial updates into the current URLSearchParams, deleting keys set to null/undefined. */
function mergeParams(
  prev: URLSearchParams,
  updates: Record<string, string | null | undefined>,
): URLSearchParams {
  const next = new URLSearchParams(prev)
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === undefined || value === '') {
      next.delete(key)
    } else {
      next.set(key, value)
    }
  }
  return next
}

export default function PapersListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  // ── Derive state from URL search params ────────────────────────────────
  const page = Number(searchParams.get('page') ?? '1')
  // 默认进入第一个板块（AI+金融）；陈旧链接里的未知 source 也回退到默认。
  const rawSource = searchParams.get('source') as PaperSource | null
  const source: PaperSource =
    rawSource !== null && PAPER_SOURCES.includes(rawSource)
      ? rawSource
      : PAPER_SOURCES[0]
  const selectedCategories = searchParams.get('topic')?.split(',').filter(Boolean) ?? []
  const favoritesOnly = searchParams.has('fav')
  const sortField = searchParams.get('sort') ?? 'published_at'
  const sortOrder = searchParams.get('order') ?? 'desc'
  // 与 SearchPage「查看全部」共用 search 参数；跨板块保留关键词。
  const searchQ = searchParams.get('search') ?? ''

  // ── UI-only state (not persisted to URL) ───────────────────────────────
  // Featured sources（AI+金融 / arXiv 最新论文）：固定 featured 视图。
  const isFeaturedSource = source === 'arxiv' || source === 'arxiv_fin'

  // ── URL param helpers ──────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  // ── Search box（与 SearchPage 共用 search 参数，防抖写回 URL）────────────
  const [searchInput, setSearchInput] = useState(searchQ)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    setSearchInput(searchQ)
  }, [searchQ])

  useEffect(() => () => clearTimeout(searchDebounceRef.current), [])

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setSearchInput(v)
    clearTimeout(searchDebounceRef.current)
    searchDebounceRef.current = setTimeout(() => {
      updateParams({ search: v.trim() || null, page: null })
    }, 300)
  }

  // ── Topic filter → API param ────────────────────────────────────────────
  // 主题过滤直接走后端 paper_topics 表：unified category id 与 paper_topic
  // slug 一一对应（见 utils/paperCategories.ts），选中的主题 id 逗号拼接后
  // 作为 topic_slug 传给 /api/papers（服务端多值 OR 精确过滤、分页准确）。
  // nlp-llm 与 llm 是两个独立主题，互不合并。
  const topicSlug = selectedCategories.length > 0 ? selectedCategories.join(',') : undefined

  // ── API call ────────────────────────────────────────────────────────────
  const hfPerPage = 15

  const { data, loading, error } = useApi(
    () => {
      if (favoritesOnly) {
        return getPaperFavorites({ page, per_page: hfPerPage, source })
      }
      if (isFeaturedSource) {
        return getPapers({
          source,
          featured: true,
          search: searchQ || undefined,
          sort: 'featured_date',
          order: 'desc',
          page,
          per_page: hfPerPage,
        })
      }
      return getPapers({
        source,
        topic_slug: topicSlug,
        search: searchQ || undefined,
        page,
        per_page: hfPerPage,
        sort: sortField,
        order: sortOrder,
      })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [page, topicSlug, source, searchQ, sortField, sortOrder, favoritesOnly, isFeaturedSource],
  )

  // 服务端已按 topic_slug（paper_topics）精确过滤并正确分页，无需客户端二次过滤。
  const filteredItems: Paper[] = data?.items ?? []

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleCategoryChange = (ids: string[]) => {
    updateParams({ topic: ids.length > 0 ? ids.join(',') : null, page: null })
  }

  const clearAllFilters = () => {
    updateParams({ topic: null, fav: null, search: null, page: null })
  }

  const handleSourceChange = (s: PaperSource) => {
    updateParams({
      source: s,
      topic: null,
      fav: null,
      sort: null,
      order: null,
      page: null,
    })
  }

  const toggleFavoritesOnly = () => {
    updateParams({
      fav: favoritesOnly ? null : '1',
      page: null,
    })
  }

  // Sort options（经典论文库）
  const sortOptions = [
    { sort: 'published_at', order: 'desc', label: '时间' },
    { sort: 'citation_count', order: 'desc', label: '被引' },
  ]

  const cycleSort = () => {
    const current = sortOptions.findIndex(o => o.sort === sortField && o.order === sortOrder)
    const next = sortOptions[(current + 1) % sortOptions.length]
    updateParams({
      sort: next.sort === 'published_at' ? null : next.sort,
      order: next.order === 'desc' ? null : next.order,
      page: null,
    })
  }

  const sortLabels: Record<string, string> = {
    published_at: '时间',
    citation_count: '被引',
    upvote_count: '赞数',
  }

  // 排序激活态：非默认（时间降序）即高亮，与「全部论文 / 主题 / 时间」激活规则对齐。
  const isActiveSort = sortField !== 'published_at' || sortOrder !== 'desc'

  const hasAnyFilter = selectedCategories.length > 0 || favoritesOnly || searchQ !== ''

  // ── Dynamic backTo carrying current URL state ──────────────────────────
  const backTo = {
    path: '/papers' + location.search,
    label: '返回论文库',
  }

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  const title = favoritesOnly
    ? '收藏论文'
    : source === 'arxiv_fin'
      ? 'AI+金融'
      : source === 'arxiv'
        ? '最新论文'
        : '经典论文库'

  // 精选板块最近一次更新时间（featured 列表按 featured_date 降序，第一条即最近）。
  // 后端返回 UTC ISO 时间戳（如 2026-08-03T00:00:00+00:00），取前 10 位即为 YYYY-MM-DD。
  const latestFeaturedDate = isFeaturedSource
    ? ((data?.items?.[0]?.featured_date ?? null)?.slice(0, 10) ?? null)
    : null

  // Refetch 中（如切换板块）旧列表仍保留显示——用半透明提示正在加载，避免内容跳变。
  const refreshing = loading && !!data

  return (
    <div>
      <PageEyebrow>PAPERS</PageEyebrow>
      <h1
        className={`text-[28px] font-normal text-[var(--ink)] tracking-wide ${
          isFeaturedSource ? 'mb-2' : 'mb-6'
        }`}
      >
        {title}
      </h1>

      {/* 精选板块更新说明（AI+金融 / 最新论文） */}
      {isFeaturedSource && (
        <p className="text-sm text-[var(--muted)] mb-6">
          每周一更新
          {latestFeaturedDate ? ` 最近更新时间：${latestFeaturedDate}` : ''}
        </p>
      )}

      {/* Source tabs */}
      <div className="relative mb-4">
        <div className="flex gap-6 border-b border-[var(--line)]/30">
          {PAPER_SOURCES.map(s => {
            const active = source === s
            const label = s === 'openalex' ? '经典论文' : s === 'arxiv' ? '最新论文' : 'AI+金融'
            return (
              <button
                key={s}
                onClick={() => handleSourceChange(s)}
                className={`relative pb-2 text-sm font-medium transition-colors cursor-pointer ${
                  active ? 'text-[var(--accent)]' : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {label}
                {active && (
                  <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-[var(--accent)] rounded-full" />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Filter toolbar (single row) */}
      <div className="flex items-center gap-2 sm:gap-0.5 mb-3 flex-wrap">
        {/* 全部论文 — resets all filters */}
        <button
          onClick={clearAllFilters}
          className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 min-h-[44px] sm:min-h-0 inline-flex items-center ${
            !hasAnyFilter
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
        >
          全部论文
        </button>

        {!favoritesOnly && !isFeaturedSource && (
          <>
            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            {/* 主题⌄ — two-level cascading menu (shared across both tabs) */}
            <CategoryFilterMenu
              selectedIds={selectedCategories}
              onSelectionChange={handleCategoryChange}
              onClear={() => updateParams({ topic: null, page: null })}
              multiSelect
            />

          </>
        )}

        <div className="flex-1" />

        {/* 搜索（与 SearchPage「查看全部」共用 search 参数） */}
        <div className="relative shrink-0">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" strokeWidth={1.8} />
          <input
            type="search"
            value={searchInput}
            onChange={handleSearchChange}
            placeholder="搜索标题或摘要"
            aria-label="搜索论文"
            className="h-[34px] w-[150px] sm:w-[200px] pl-8 pr-2 rounded-full border border-[var(--line)] bg-white/60 text-xs text-[var(--ink)] placeholder:text-[var(--muted)] outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent transition-all"
          />
        </div>

        {/* Sort toggle（隐藏于 featured 板块，其按 featured_date 固定排序） */}
        {!isFeaturedSource && (
          <button
            onClick={cycleSort}
            className={`shrink-0 inline-flex items-center gap-1 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 min-h-[44px] sm:min-h-0 ${
              isActiveSort
                ? 'text-[var(--accent)]'
                : 'text-[var(--muted)] hover:text-[var(--ink)]'
            }`}
          >
            {sortLabels[sortField] || '时间'}
            <ArrowDown size={13} strokeWidth={1.5} />
          </button>
        )}

        {/* 仅看收藏 */}
        <button
          onClick={toggleFavoritesOnly}
          className={`shrink-0 inline-flex items-center gap-1.5 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 min-h-[44px] sm:min-h-0 ${
            favoritesOnly
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
          role="switch"
          aria-checked={favoritesOnly}
        >
          <span
            className={`relative inline-block w-7 h-4 rounded-full transition-colors ${
              favoritesOnly ? 'bg-[var(--accent)]' : 'bg-[var(--line)]'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                favoritesOnly ? 'translate-x-3' : 'translate-x-0'
              }`}
            />
          </span>
          仅看收藏
        </button>
      </div>

      {/* Loading / Error / Empty / List */}
      {loading && !data && <LoadingSkeleton />}
      {error && <EmptyState title="加载失败" description={error} />}
      {data && filteredItems.length === 0 && !loading && (
        <EmptyState
          title={
            favoritesOnly
              ? '还没有收藏论文'
              : searchQ
                ? `没有找到匹配 "${searchQ}" 的论文`
                : isFeaturedSource
                  ? '该板块暂无内容，敬请期待'
                  : '当前暂无内容'
          }
          description={
            favoritesOnly
              ? '你收藏的论文会显示在这里'
              : searchQ
                ? '试试更短的关键词，或检查拼写'
                : isFeaturedSource
                  ? undefined
                  : '我们正在整理这部分论文，稍后再来看'
          }
        >
          {favoritesOnly && (
            <Link
              to="/papers"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
            >
              浏览论文
            </Link>
          )}
        </EmptyState>
      )}
      {data && filteredItems.length > 0 && (
        <>
          <div className={`space-y-3 transition-opacity duration-200 ${refreshing ? 'opacity-60' : ''}`}>
            {filteredItems.map(paper => (
              <PaperCard key={paper.id} paper={paper} backTo={backTo} showCategories={!isFeaturedSource} />
            ))}
          </div>
          {/* Pagination: server-side (topic_slug filtered by the API) */}
          {!favoritesOnly && (
            <Pagination page={page} pages={data.pages} onPageChange={p => updateParams({ page: p === 1 ? null : String(p) })} />
          )}
        </>
      )}
    </div>
  )
}
