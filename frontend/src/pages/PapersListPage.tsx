import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getPapers, getPaperFavorites, getPaperMonthCounts } from '../api/client'
import PaperCard from '../components/PaperCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import CategoryFilterMenu from '../components/CategoryFilterMenu'
import { ArrowDown } from 'lucide-react'
import { UNIFIED_TO_SEED_CATEGORY, unifiedCategoryIds } from '../utils/paperCategoryMap'
import type { Paper } from '../api/types'

type PaperSource = 'openalex' | 'huggingface'

// Months for the cascading time filter
const _CUR_D = new Date()
const _CUR_Y = _CUR_D.getFullYear()
const _CUR_M = _CUR_D.getMonth() + 1

const YEAR_MONTHS: { year: number; months: string[] }[] = [
  // Current year: up to current month, descending
  {
    year: _CUR_Y,
    months: Array.from({ length: _CUR_M }, (_, i) =>
      String(_CUR_M - i).padStart(2, '0'),
    ),
  },
  // Past 2 years: all 12 months, descending
  ...[1, 2].map(yi => ({
    year: _CUR_Y - yi,
    months: Array.from({ length: 12 }, (_, i) =>
      String(12 - i).padStart(2, '0'),
    ),
  })),
]

function formatMonth(ym: string): string {
  const [y, m] = ym.split('-')
  return `${y}年${Number(m)}月`
}

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
  const source = (searchParams.get('source') ?? 'openalex') as PaperSource
  const selectedCategories = searchParams.get('cat')?.split(',').filter(Boolean) ?? []
  const monthFilter = searchParams.get('month') ?? null
  const favoritesOnly = searchParams.has('fav')
  const sortField = searchParams.get('sort') ?? 'published_at'
  const sortOrder = searchParams.get('order') ?? 'desc'

  // ── UI-only state (not persisted to URL) ───────────────────────────────
  const [menuOpen, setMenuOpen] = useState(false)
  const [hoveredYearIndex, setHoveredYearIndex] = useState(0)
  const [monthCounts, setMonthCounts] = useState<Record<string, number>>({})
  const menuRef = useRef<HTMLDivElement>(null)
  const isHuggingFace = source === 'huggingface'

  // For HF, the first selected category IS the topic slug (single-select via menu)
  const topicSlug = isHuggingFace ? (selectedCategories[0] ?? null) : null

  // Fetch month counts when menu opens
  useEffect(() => {
    if (!menuOpen) return
    getPaperMonthCounts().then(counts => {
      const map: Record<string, number> = {}
      for (const c of counts) map[c.ym] = c.cnt
      setMonthCounts(map)
    }).catch(() => {})
  }, [menuOpen])

  // ── URL param helpers ──────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  // Close time dropdown on outside click
  useEffect(() => {
    if (!menuOpen) return
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

  // ── Category → seed param for OpenAlex API ─────────────────────────────
  const categoryParam = (() => {
    if (isHuggingFace || selectedCategories.length === 0) return undefined
    const seeds = [...new Set(
      selectedCategories
        .map(id => UNIFIED_TO_SEED_CATEGORY[id as keyof typeof UNIFIED_TO_SEED_CATEGORY])
        .filter(Boolean),
    )] as string[]
    return seeds.length > 0 ? seeds.join(',') : undefined
  })()

  // Whether client-side filtering is needed (for categories without seed mapping).
  // Not applicable in HF mode — the server handles everything via topic_slug.
  const needsClientFilter = !isHuggingFace && selectedCategories.some(
    id => !UNIFIED_TO_SEED_CATEGORY[id as keyof typeof UNIFIED_TO_SEED_CATEGORY],
  )

  // ── API call ────────────────────────────────────────────────────────────
  const hfPerPage = 15

  const { data, loading, error } = useApi(
    () => {
      if (favoritesOnly) {
        return getPaperFavorites({ page, per_page: hfPerPage, source })
      }
      return getPapers({
        source,
        category: categoryParam,
        topic_slug: topicSlug ?? undefined,
        month: monthFilter ?? undefined,
        page,
        per_page: hfPerPage,
        sort: sortField,
        order: sortOrder,
      })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [page, categoryParam, topicSlug, monthFilter, source, sortField, sortOrder, favoritesOnly],
  )

  // ── Client-side filtering ───────────────────────────────────────────────
  // HF mode: server handles all filtering via topic_slug — skip client-side.
  // Classic mode: apply unified-category mapping for categories without a seed.
  let filteredItems: Paper[] = data?.items ?? []
  if (selectedCategories.length > 0 && data && !isHuggingFace) {
    filteredItems = data.items.filter(paper =>
      unifiedCategoryIds(paper.categories).some(c => selectedCategories.includes(c)),
    )
  }

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleCategoryChange = (ids: string[]) => {
    updateParams({ cat: ids.length > 0 ? ids.join(',') : null, page: null })
  }

  const clearAllFilters = () => {
    updateParams({ cat: null, month: null, fav: null, page: null })
  }

  const handleSourceChange = (s: PaperSource) => {
    updateParams({
      source: s === 'openalex' ? null : s,
      cat: null,
      month: null,
      fav: null,
      sort: null,
      order: null,
      page: null,
    })
  }

  const handleMonthSelect = (month: string | null) => {
    updateParams({ month: month ?? null, page: null })
    setMenuOpen(false)
  }

  const toggleFavoritesOnly = () => {
    updateParams({
      fav: favoritesOnly ? null : '1',
      page: null,
    })
  }

  // Sort options per source
  const sortOptions = isHuggingFace
    ? [
        { sort: 'published_at', order: 'desc', label: '时间' },
        { sort: 'upvote_count', order: 'desc', label: '赞数' },
      ]
    : [
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

  const hasAnyFilter = selectedCategories.length > 0 || monthFilter !== null || favoritesOnly

  // ── Dynamic backTo carrying current URL state ──────────────────────────
  const backTo = {
    path: '/papers' + location.search,
    label: '返回论文库',
  }

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  const title = favoritesOnly
    ? '收藏论文'
    : isHuggingFace
      ? 'HuggingFace 趋势论文'
      : '经典论文库'

  return (
    <div>
      <PageEyebrow>PAPERS</PageEyebrow>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">{title}</h1>

      {/* Source tabs */}
      <div className="relative mb-4">
        <div className="flex gap-6 border-b border-[var(--line)]/30">
          {(['openalex', 'huggingface'] as PaperSource[]).map(s => {
            const active = source === s
            return (
              <button
                key={s}
                onClick={() => handleSourceChange(s)}
                className={`relative pb-2 text-sm font-medium transition-colors cursor-pointer ${
                  active ? 'text-[var(--accent)]' : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {s === 'openalex' ? '经典论文' : 'Hugging Face 趋势'}
                {active && (
                  <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-[var(--accent)] rounded-full" />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Filter toolbar (single row) */}
      <div className="flex items-center gap-0.5 mb-3 flex-wrap">
        {/* 全部论文 — resets all filters */}
        <button
          onClick={clearAllFilters}
          className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
            !hasAnyFilter
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
        >
          全部论文
        </button>

        {!favoritesOnly && (
          <>
            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            {/* 主题⌄ — two-level cascading menu (shared across both tabs) */}
            <CategoryFilterMenu
              selectedIds={selectedCategories}
              onSelectionChange={handleCategoryChange}
              onClear={() => updateParams({ cat: null, page: null })}
              multiSelect={!isHuggingFace}
            />

            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            {/* 时间⌄ — cascading year→month menu */}
            <div ref={menuRef} className="relative shrink-0">
              <button
                onClick={() => setMenuOpen(v => !v)}
                className={`text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
                  monthFilter !== null
                    ? 'text-[var(--accent)]'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {monthFilter !== null ? formatMonth(monthFilter) : '时间⌄'}
              </button>
              {monthFilter !== null && (
                <button
                  onClick={() => handleMonthSelect(null)}
                  className="text-xs text-[var(--muted)] hover:text-[var(--ink)] transition-colors cursor-pointer px-0.5 py-1"
                  title="清除时间筛选"
                >
                  ✕
                </button>
              )}

              {menuOpen && (
                <div
                  className="absolute top-full left-0 mt-1 z-50"
                  onClick={e => e.stopPropagation()}
                >
                  {/* Desktop: two-column layout */}
                  <div className="hidden lg:flex bg-white/90 backdrop-blur-sm border border-[var(--line)] rounded-xl overflow-hidden min-w-[240px] shadow-sm">
                    {/* Left: years */}
                    <div className="w-[115px] border-r border-[var(--line)] py-1">
                      {/* 全部时间 option */}
                      <button
                        onClick={() => handleMonthSelect(null)}
                        className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                          monthFilter === null
                            ? 'text-[var(--accent)] font-medium'
                            : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                        }`}
                      >
                        全部时间
                      </button>
                      {YEAR_MONTHS.map((ym, i) => {
                        const yearSelected = monthFilter?.startsWith(String(ym.year))
                        return (
                          <button
                            key={ym.year}
                            onMouseEnter={() => setHoveredYearIndex(i)}
                            className={`w-full flex items-center justify-between px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                              yearSelected
                                ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                                : 'text-[var(--ink)] hover:bg-black/[.03]'
                            }`}
                          >
                            {ym.year}
                            <span className={`text-xs ${hoveredYearIndex === i ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}`}>▸</span>
                          </button>
                        )
                      })}
                    </div>

                    {/* Right: months of hovered year */}
                    <div className="w-[130px] py-1">
                      {YEAR_MONTHS[hoveredYearIndex].months.map(m => {
                        const ym = `${YEAR_MONTHS[hoveredYearIndex].year}-${m}`
                        const selected = monthFilter === ym
                        const cnt = monthCounts[ym] ?? -1
                        const isEmpty = cnt === 0
                        return (
                          <button
                            key={ym}
                            onClick={() => !isEmpty && handleMonthSelect(ym)}
                            disabled={isEmpty}
                            className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${
                              selected
                                ? 'text-[var(--accent)] bg-[var(--accent)]/8 font-medium'
                                : isEmpty
                                  ? 'text-[var(--line)]'
                                  : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03] cursor-pointer'
                            }`}
                          >
                            {Number(m)}月
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  {/* Mobile: accordion layout */}
                  <div className="lg:hidden bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl min-w-[200px] shadow-sm overflow-hidden">
                    <button
                      onClick={() => handleMonthSelect(null)}
                      className={`w-full text-left px-3 py-2.5 text-sm transition-colors cursor-pointer ${
                        monthFilter === null
                          ? 'text-[var(--accent)] font-medium'
                          : 'text-[var(--muted)] hover:bg-black/[.03]'
                      }`}
                    >
                      全部时间
                    </button>
                    {YEAR_MONTHS.map((ym, i) => {
                      const isExpanded = hoveredYearIndex === i
                      return (
                        <div key={ym.year}>
                          <button
                            onClick={() => setHoveredYearIndex(isExpanded ? -1 : i)}
                            className={`w-full flex items-center justify-between px-3 py-2.5 text-sm transition-colors cursor-pointer ${
                              monthFilter?.startsWith(String(ym.year))
                                ? 'text-[var(--accent)] bg-[var(--accent)]/8 font-medium'
                                : 'text-[var(--ink)] hover:bg-black/[.03]'
                            }`}
                          >
                            {ym.year}
                            <span className={`text-xs text-[var(--muted)] transition-transform ${isExpanded ? 'rotate-180' : ''}`}>▾</span>
                          </button>
                          {isExpanded && (
                            <div className="border-t border-[var(--line)]/40">
                              {ym.months.map(m => {
                                const ymVal = `${ym.year}-${m}`
                                const selected = monthFilter === ymVal
                                const cnt = monthCounts[ymVal] ?? -1
                                const isEmpty = cnt === 0
                                return (
                                  <button
                                    key={ymVal}
                                    onClick={() => !isEmpty && handleMonthSelect(ymVal)}
                                    disabled={isEmpty}
                                    className={`w-full text-left px-5 py-2 text-sm transition-colors ${
                                      selected
                                        ? 'text-[var(--accent)] bg-[var(--accent)]/8 font-medium'
                                        : isEmpty
                                          ? 'text-[var(--line)]'
                                          : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03] cursor-pointer'
                                    }`}
                                  >
                                    {Number(m)}月
                                  </button>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <div className="flex-1" />

        {/* Sort toggle */}
        <button
          onClick={cycleSort}
          className="shrink-0 inline-flex items-center gap-1 text-xs text-[var(--muted)] hover:text-[var(--ink)] transition-colors cursor-pointer px-1.5 py-1"
        >
          {sortLabels[sortField] || '时间'}
          <ArrowDown size={13} strokeWidth={1.5} />
        </button>

        {/* 仅看收藏 */}
        <button
          onClick={toggleFavoritesOnly}
          className={`shrink-0 inline-flex items-center gap-1.5 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
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
          title={favoritesOnly ? '还没有收藏论文' : '当前暂无内容'}
          description={favoritesOnly ? '你收藏的论文会显示在这里' : '我们正在整理这部分论文，稍后再来看'}
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
          <div className="space-y-3">
            {filteredItems.map(paper => (
              <PaperCard key={paper.id} paper={paper} backTo={backTo} />
            ))}
          </div>
          {/* Pagination: server-side when not favorites-only and no client filter needed */}
          {!favoritesOnly && !needsClientFilter && (
            <Pagination page={page} pages={data.pages} onPageChange={p => updateParams({ page: p === 1 ? null : String(p) })} />
          )}
        </>
      )}
    </div>
  )
}
