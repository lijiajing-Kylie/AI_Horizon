import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getPapers, getPaperFavorites } from '../api/client'
import PaperCard from '../components/PaperCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import CategoryFilterMenu from '../components/CategoryFilterMenu'
import { ArrowDown } from 'lucide-react'
import { UNIFIED_TO_SEED_CATEGORY, unifiedCategoryIds } from '../utils/paperCategoryMap'
import type { Paper } from '../api/types'

type PaperSource = 'openalex' | 'huggingface'

const backTo = { path: '/papers', label: '返回论文库' }

// Years for the year filter dropdown
const CURRENT_YEAR = new Date().getFullYear() // 2026
const YEAR_OPTIONS = Array.from({ length: 7 }, (_, i) => CURRENT_YEAR - i)

export default function PapersListPage() {
  const [page, setPage] = useState(1)
  const [source, setSource] = useState<PaperSource>('openalex')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [yearFilter, setYearFilter] = useState<number | null>(null)
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [yearMenuOpen, setYearMenuOpen] = useState(false)
  const [sortField, setSortField] = useState('published_at')
  const [sortOrder, setSortOrder] = useState('desc')

  const yearMenuRef = useRef<HTMLDivElement>(null)
  const isHuggingFace = source === 'huggingface'

  // Close year dropdown on outside click
  useEffect(() => {
    if (!yearMenuOpen) return
    const handleClick = (e: MouseEvent) => {
      if (yearMenuRef.current && !yearMenuRef.current.contains(e.target as Node)) {
        setYearMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [yearMenuOpen])

  // ── Category → seed param for OpenAlex API ─────────────────────────────
  // Collect unique seed names from selected categories. Categories without
  // seed mapping rely on client-side filtering.
  const categoryParam = (() => {
    if (selectedCategories.length === 0) return undefined
    const seeds = [...new Set(
      selectedCategories
        .map(id => UNIFIED_TO_SEED_CATEGORY[id as keyof typeof UNIFIED_TO_SEED_CATEGORY])
        .filter(Boolean),
    )] as string[]
    return seeds.length > 0 ? seeds.join(',') : undefined
  })()

  // Whether client-side filtering is needed (for categories without seed mapping)
  const needsClientFilter = selectedCategories.some(
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
        year: yearFilter ?? undefined,
        page,
        per_page: hfPerPage,
        sort: sortField,
        order: sortOrder,
      })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [page, categoryParam, yearFilter, source, sortField, sortOrder, favoritesOnly],
  )

  // ── Client-side filtering ───────────────────────────────────────────────
  let filteredItems: Paper[] = data?.items ?? []
  if (selectedCategories.length > 0 && data) {
    filteredItems = data.items.filter(paper =>
      unifiedCategoryIds(paper.categories).some(c => selectedCategories.includes(c)),
    )
  }

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleCategoryChange = (ids: string[]) => {
    setSelectedCategories(ids)
    setPage(1)
  }

  const clearAllFilters = () => {
    setSelectedCategories([])
    setYearFilter(null)
    setFavoritesOnly(false)
    setPage(1)
  }

  const handleSourceChange = (s: PaperSource) => {
    setSource(s)
    setPage(1)
    setSelectedCategories([])
    setYearFilter(null)
    setFavoritesOnly(false)
    setSortField('published_at')
    setSortOrder('desc')
  }

  const handleYearSelect = (year: number | null) => {
    setYearFilter(year)
    setYearMenuOpen(false)
    setPage(1)
  }

  const toggleFavoritesOnly = () => {
    setFavoritesOnly(v => !v)
    setPage(1)
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
    setSortField(next.sort)
    setSortOrder(next.order)
    setPage(1)
  }

  const sortLabels: Record<string, string> = {
    published_at: '时间',
    citation_count: '被引',
    upvote_count: '赞数',
  }

  const hasAnyFilter = selectedCategories.length > 0 || yearFilter !== null || favoritesOnly

  const title = favoritesOnly
    ? '收藏论文'
    : isHuggingFace
      ? 'HuggingFace 趋势论文'
      : '经典论文库'

  return (
    <div>
      <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">PAPERS</p>
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

            {/* 主题⌄ — two-level cascading menu */}
            <CategoryFilterMenu
              selectedIds={selectedCategories}
              onSelectionChange={handleCategoryChange}
              onClear={() => setSelectedCategories([])}
            />

            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            {/* 年份⌄ — year dropdown */}
            <div ref={yearMenuRef} className="relative shrink-0">
              <button
                onClick={() => setYearMenuOpen(v => !v)}
                className={`text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
                  yearFilter !== null
                    ? 'text-[var(--accent)]'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {yearFilter !== null ? `${yearFilter}年` : '年份⌄'}
              </button>
              {yearFilter !== null && (
                <button
                  onClick={() => handleYearSelect(null)}
                  className="text-xs text-[var(--muted)] hover:text-[var(--ink)] transition-colors cursor-pointer px-0.5 py-1"
                  title="清除年份筛选"
                >
                  ✕
                </button>
              )}
              {yearMenuOpen && (
                <div className="absolute top-full left-0 mt-1 z-50 bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl overflow-hidden min-w-[100px] shadow-sm py-1">
                  <button
                    onClick={() => handleYearSelect(null)}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      yearFilter === null
                        ? 'text-[var(--accent)] font-medium'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    全部年份
                  </button>
                  {YEAR_OPTIONS.map(y => (
                    <button
                      key={y}
                      onClick={() => handleYearSelect(y)}
                      className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                        yearFilter === y
                          ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                          : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                      }`}
                    >
                      {y}年
                    </button>
                  ))}
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
        <div className="text-center py-10 text-[var(--muted)]">
          <h3 className="text-base font-medium text-[var(--ink)] mb-1">
            {favoritesOnly ? '还没有收藏论文' : '当前暂无内容'}
          </h3>
          <p className="text-sm mb-5">
            {favoritesOnly ? '你收藏的论文会显示在这里' : '我们正在整理这部分论文，稍后再来看'}
          </p>
          {favoritesOnly && (
            <div className="flex items-center gap-3 flex-wrap justify-center">
              <Link
                to="/papers"
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
              >
                浏览论文
              </Link>
            </div>
          )}
        </div>
      )}
      {data && filteredItems.length > 0 && (
        <>
          <div className="space-y-3">
            {filteredItems.map(paper => (
              <PaperCard key={paper.id} paper={paper} backTo={backTo} />
            ))}
          </div>
          {/* Pagination: server-side for OpenAlex when not favorites-only and no client filter needed */}
          {!isHuggingFace && !favoritesOnly && !needsClientFilter && (
            <Pagination page={page} pages={data.pages} onPageChange={setPage} />
          )}
        </>
      )}
    </div>
  )
}
