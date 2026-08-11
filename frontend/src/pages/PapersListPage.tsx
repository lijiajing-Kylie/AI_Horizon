import { useState, useRef, useEffect, useCallback } from 'react'
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

  // ── UI-only state (not persisted to URL) ───────────────────────────────
  // Featured sources（AI+金融 / arXiv 最新论文）：精选内容（featured 过滤），
  // 排序可选「综合（AI 打分）/ 时间」，默认时间。
  const isFeaturedSource = source === 'arxiv' || source === 'arxiv_fin'
  const [sortMenuOpen, setSortMenuOpen] = useState(false)
  const sortMenuRef = useRef<HTMLDivElement>(null)

  // ── URL param helpers ──────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  // ── Topic filter → API param ────────────────────────────────────────────
  // 主题过滤直接走后端 paper_topics 表：unified category id 与 paper_topic
  // slug 一一对应（见 utils/paperCategories.ts），选中的主题 id 逗号拼接后
  // 作为 topic_slug 传给 /api/papers（服务端多值 OR 精确过滤、分页准确）。
  // nlp-llm 与 llm 是两个独立主题，互不合并。
  const topicSlug = selectedCategories.length > 0 ? selectedCategories.join(',') : undefined

  // ── API call ────────────────────────────────────────────────────────────
  const perPage = 15

  const { data, loading, error } = useApi(
    () => {
      if (favoritesOnly) {
        return getPaperFavorites({ page, per_page: perPage, source })
      }
      if (isFeaturedSource) {
        return getPapers({
          source,
          featured: true,
          topic_slug: topicSlug,
          sort: sortField,
          order: sortOrder,
          page,
          per_page: perPage,
        })
      }
      return getPapers({
        source,
        topic_slug: topicSlug,
        page,
        per_page: perPage,
        sort: sortField,
        order: sortOrder,
      })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [page, topicSlug, source, sortField, sortOrder, favoritesOnly, isFeaturedSource],
  )

  // 服务端已按 topic_slug（paper_topics）精确过滤并正确分页，无需客户端二次过滤。
  const filteredItems: Paper[] = data?.items ?? []

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleCategoryChange = (ids: string[]) => {
    updateParams({ topic: ids.length > 0 ? ids.join(',') : null, page: null })
  }

  const clearAllFilters = () => {
    updateParams({ topic: null, fav: null, page: null })
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

  // ── Sort menu（精选板块：时间 / 综合；经典库：时间 / 被引；收藏固定按收藏时间）─
  useEffect(() => {
    if (!sortMenuOpen) return
    const handleClick = (e: MouseEvent) => {
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setSortMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [sortMenuOpen])

  const selectSort = (s: string) => {
    updateParams({
      // 默认（时间降序）不在 URL 中显式出现；切回默认时清掉参数。
      sort: s === 'published_at' ? null : s,
      order: null,
      page: null,
    })
    setSortMenuOpen(false)
  }

  const hasAnyFilter = selectedCategories.length > 0 || favoritesOnly

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
        {/* 全部论文⌄：展开选择排序（时间 / 被引）。精选板块固定按精选日期排序；收藏视图固定按收藏时间排序。 */}
        <div ref={sortMenuRef} className="relative shrink-0">
          <button
            onClick={() => setSortMenuOpen(v => !v)}
            className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 min-h-[44px] sm:min-h-0 inline-flex items-center ${
              sortMenuOpen || !hasAnyFilter
                ? 'text-[var(--accent)]'
                : 'text-[var(--muted)] hover:text-[var(--ink)]'
            }`}
          >
            全部论文⌄
          </button>
          {sortMenuOpen && (
            <div className="absolute top-full left-0 mt-1 z-50 bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl overflow-hidden min-w-[150px] shadow-sm py-1">
              {!favoritesOnly && (
                <>
                  <div className="px-3 pt-1.5 pb-0.5 text-[10px] font-bold tracking-[.12em] text-[#8ea0b6]">排序</div>
                  <button
                    onClick={() => selectSort('published_at')}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      sortField === 'published_at'
                        ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    时间
                  </button>
                  {isFeaturedSource ? (
                    <button
                      onClick={() => selectSort('ai_relevance_score')}
                      className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                        sortField === 'ai_relevance_score'
                          ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                          : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                      }`}
                    >
                      综合
                    </button>
                  ) : (
                    <button
                      onClick={() => selectSort('citation_count')}
                      className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                        sortField === 'citation_count'
                          ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                          : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                      }`}
                    >
                      被引
                    </button>
                  )}
                </>
              )}
              {hasAnyFilter && (
                <>
                  {!favoritesOnly && <div className="h-px my-1 bg-[var(--line)]/60" />}
                  <button
                    onClick={() => { clearAllFilters(); setSortMenuOpen(false) }}
                    className="w-full text-left px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03] transition-colors cursor-pointer"
                  >
                    清除筛选
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {!favoritesOnly && source !== 'arxiv_fin' && (
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
              : isFeaturedSource
                ? '该板块暂无内容，敬请期待'
                : '当前暂无内容'
          }
          description={
            favoritesOnly
              ? '你收藏的论文会显示在这里'
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
              <PaperCard key={paper.id} paper={paper} backTo={backTo} />
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
