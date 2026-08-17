import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getReports, getReportInstitutions, getReportFavorites } from '../api/client'
import type { ReportsResponse } from '../api/types'
import ReportCard from '../components/ReportCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import { ChevronRight } from 'lucide-react'

/** Merge partial updates into URLSearchParams, deleting keys set to null/undefined. */
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

export default function ReportsListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  // ── Derive state from URL search params ────────────────────────────────
  const page = Number(searchParams.get('page') ?? '1')
  const institution = searchParams.get('inst') || null
  const favoritesOnly = searchParams.has('fav')
  // 与 SearchPage「查看全部」共用 search 参数。
  const searchQ = searchParams.get('search') ?? ''
  // 排序方式：time（发布时间，默认）| composite（综合分）。前端不显示综合分数值。
  const sort = searchParams.get('sort') ?? 'time'

  // ── UI-only state ──────────────────────────────────────────────────────
  const [sortMenuOpen, setSortMenuOpen] = useState(false)
  const sortMenuRef = useRef<HTMLDivElement>(null)
  const [instMenuOpen, setInstMenuOpen] = useState(false)

  // ── URL param helper ───────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  const { data: institutions } = useApi(() => getReportInstitutions(), [])

  const { data, loading, error } = useApi<ReportsResponse>(
    () => {
      if (favoritesOnly) {
        return getReportFavorites({ page, per_page: 15 })
      }
      return getReports({
        page,
        per_page: 15,
        institution: institution ?? undefined,
        search: searchQ || undefined,
        sort: sort === 'composite' ? 'composite_score' : 'published_at',
        order: 'desc',
      })
    },
    [page, institution, favoritesOnly, searchQ, sort],
  )

  // Close dropdown on outside click
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

  const clearAllFilters = () => {
    updateParams({ inst: null, fav: null, search: null, page: null })
  }

  const toggleFavoritesOnly = () => {
    updateParams({ fav: favoritesOnly ? null : '1', page: null })
  }

  const selectSort = (s: string) => {
    updateParams({ sort: s, page: null })
    setSortMenuOpen(false)
  }

  const selectInstitution = (inst: string | null) => {
    updateParams({ inst: inst ?? null, page: null })
    setSortMenuOpen(false)
  }

  // ── Dynamic backTo carrying current URL state ──────────────────────────
  const backTo = {
    path: '/reports' + location.search,
    label: '返回报告库',
  }

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!data || data.items.length === 0) {
    if (favoritesOnly) {
      return (
        <div>
          <PageEyebrow>REPORTS</PageEyebrow>
          <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">收藏报告</h1>
          <EmptyState
            title="还没有收藏报告"
            description="你收藏的报告会显示在这里"
          >
            <Link
              to="/reports"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
            >
              浏览报告
            </Link>
          </EmptyState>
        </div>
      )
    }
    return (
      <div>
        <PageEyebrow>REPORTS</PageEyebrow>
        <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">报告库</h1>
        <EmptyState
          title={searchQ ? `没有找到匹配 "${searchQ}" 的报告` : '暂无报告'}
          description={searchQ ? '试试更短的关键词，或检查拼写' : '报告库尚未同步'}
        />
      </div>
    )
  }

  const instList = institutions ?? []
  const hasAnyFilter = institution !== null || favoritesOnly || searchQ !== ''
  // 报告库最近一次抓取时间（后端返回 UTC ISO 时间戳，取前 10 位即为 YYYY-MM-DD）。
  const latestFetchedAt = data?.latest_fetched_at?.slice(0, 10)

  return (
    <div>
      <PageEyebrow>REPORTS</PageEyebrow>
      <h1
        className={`text-[28px] font-normal text-[var(--ink)] tracking-wide ${
          !favoritesOnly && latestFetchedAt ? 'mb-2' : 'mb-6'
        }`}
      >
        报告库
      </h1>

      {/* 报告库更新说明 */}
      {!favoritesOnly && latestFetchedAt && (
        <p className="text-sm text-[var(--muted)] mb-6">
          每周一更新 最近更新时间：{latestFetchedAt}
        </p>
      )}

      {/* ── Filter toolbar ── */}
      <div className="flex items-center gap-0.5 mb-3 flex-wrap">
        {/* 全部报告 ⌄：展开选择排序（时间 / 综合）与机构筛选。收藏视图固定按收藏时间排序，隐藏。 */}
        <div ref={sortMenuRef} className="relative shrink-0">
          <button
            onClick={() => setSortMenuOpen(v => !v)}
            className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
              sortMenuOpen || !hasAnyFilter
                ? 'text-[var(--accent)]'
                : 'text-[var(--muted)] hover:text-[var(--ink)]'
            }`}
          >
            全部报告⌄
          </button>
          {sortMenuOpen && (
            <div className="absolute top-full left-0 mt-1 z-50 bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl min-w-[180px] shadow-sm py-1">
              {!favoritesOnly && (
                <>
                  <div className="px-3 pt-1.5 pb-0.5 text-[10px] font-bold tracking-[.12em] text-[#8ea0b6]">排序</div>
                  <button
                    onClick={() => selectSort('time')}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      sort === 'time'
                        ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    时间
                  </button>
                  <button
                    onClick={() => selectSort('composite')}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      sort === 'composite'
                        ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    综合
                  </button>
                </>
              )}

              {!favoritesOnly && instList.length > 1 && (
                <div
                  className="relative"
                  onMouseEnter={() => setInstMenuOpen(true)}
                  onMouseLeave={() => setInstMenuOpen(false)}
                >
                  <div className="h-px my-1 bg-[var(--line)]/60" />
                  <button
                    onClick={() => setInstMenuOpen(v => !v)}
                    className={`w-full flex items-center justify-between px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      institution !== null
                        ? 'text-[var(--accent)] font-medium'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    机构
                    <ChevronRight size={12} strokeWidth={2} className="text-[var(--muted)] shrink-0" />
                  </button>
                  {instMenuOpen && (
                    <div className="absolute left-full top-0 ml-1 z-50 bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl min-w-[190px] shadow-sm py-1 max-h-[400px] overflow-y-auto">
                      <button
                        onClick={() => selectInstitution(null)}
                        className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                          institution === null
                            ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                            : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                        }`}
                      >
                        全部机构
                      </button>
                      {instList.map(({ institution: inst, count }) => (
                        <button
                          key={inst}
                          onClick={() => selectInstitution(inst)}
                          className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                            institution === inst
                              ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                              : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                          }`}
                        >
                          <span className="inline-block max-w-[220px] truncate align-middle">{inst}</span>
                          <span className="ml-1.5 text-xs text-[var(--muted)]">{count}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
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

        <div className="flex-1" />

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

      <div className="space-y-3">
        {data.items.map(report => (
          <ReportCard key={report.id} report={report} backTo={backTo} />
        ))}
      </div>
      <Pagination page={page} pages={data.pages} onPageChange={p => updateParams({ page: p === 1 ? null : String(p) })} />
    </div>
  )
}
