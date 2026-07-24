import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getReports, getReportInstitutions, getReportFavorites } from '../api/client'
import ReportCard from '../components/ReportCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'

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

  // ── UI-only state ──────────────────────────────────────────────────────
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // ── URL param helper ───────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  const { data: institutions } = useApi(() => getReportInstitutions(), [])

  const { data, loading, error } = useApi(
    () => {
      if (favoritesOnly) {
        return getReportFavorites({ page, per_page: 15 })
      }
      return getReports({ page, per_page: 15, institution: institution ?? undefined })
    },
    [page, institution, favoritesOnly],
  )

  // Close dropdown on outside click
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

  const clearAllFilters = () => {
    updateParams({ inst: null, fav: null, page: null })
  }

  const toggleFavoritesOnly = () => {
    updateParams({ fav: favoritesOnly ? null : '1', page: null })
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
        <EmptyState title="暂无报告" description="报告库尚未同步" />
      </div>
    )
  }

  const instList = institutions ?? []
  const hasAnyFilter = institution !== null || favoritesOnly

  return (
    <div>
      <PageEyebrow>REPORTS</PageEyebrow>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">报告库</h1>

      {/* ── Filter toolbar ── */}
      <div className="flex items-center gap-0.5 mb-3 flex-wrap">
        <button
          onClick={clearAllFilters}
          className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
            !hasAnyFilter
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
        >
          全部报告
        </button>

        {!favoritesOnly && instList.length > 1 && (
          <>
            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            <div ref={menuRef} className="relative shrink-0">
              <button
                onClick={() => setMenuOpen(v => !v)}
                className={`text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
                  institution !== null
                    ? 'text-[var(--accent)]'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {institution !== null ? `机构：${institution}` : '机构⌄'}
              </button>
              {institution !== null && (
                <button
                  onClick={() => updateParams({ inst: null, page: null })}
                  className="text-xs text-[var(--muted)] hover:text-[var(--ink)] transition-colors cursor-pointer px-0.5 py-1"
                  title="清除机构筛选"
                >
                  ✕
                </button>
              )}
              {menuOpen && (
                <div className="absolute top-full left-0 mt-1 z-50 bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl overflow-hidden min-w-[140px] shadow-sm py-1">
                  {instList.map(({ institution: inst, count }) => (
                    <button
                      key={inst}
                      onClick={() => { updateParams({ inst, page: null }); setMenuOpen(false) }}
                      className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                        institution === inst
                          ? 'text-[var(--accent)] font-medium bg-[var(--accent)]/8'
                          : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                      }`}
                    >
                      {inst}
                      <span className="ml-1.5 text-xs text-[var(--muted)]">{count}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

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
