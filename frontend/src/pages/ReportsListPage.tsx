import { useState, useRef, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import { getReports, getReportInstitutions } from '../api/client'
import ReportCard from '../components/ReportCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'

const backTo = { path: '/reports', label: '返回报告库' }

export default function ReportsListPage() {
  const [page, setPage] = useState(1)
  const [institution, setInstitution] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const { data: institutions } = useApi(() => getReportInstitutions(), [])

  const { data, loading, error } = useApi(
    () => getReports({ page, per_page: 15, institution: institution ?? undefined }),
    [page, institution],
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

  const clearInstitution = () => {
    setInstitution(null)
    setPage(1)
  }

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!data || data.items.length === 0) {
    return (
      <div>
        <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">REPORTS</p>
        <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">报告库</h1>
        <EmptyState title="暂无报告" description="报告库尚未同步" />
      </div>
    )
  }

  const instList = institutions ?? []
  const hasFilter = institution !== null

  return (
    <div>
      <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">REPORTS</p>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">报告库</h1>

      {/* ── Filter toolbar ── */}
      <div className="flex items-center gap-0.5 mb-3 flex-wrap">
        <button
          onClick={clearInstitution}
          className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
            !hasFilter
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
        >
          全部报告
        </button>

        {instList.length > 1 && (
          <>
            <span className="shrink-0 text-xs text-[var(--line)] px-0.5 select-none">|</span>

            <div ref={menuRef} className="relative shrink-0">
              <button
                onClick={() => setMenuOpen(v => !v)}
                className={`text-xs font-medium transition-colors cursor-pointer px-1.5 py-1 ${
                  hasFilter
                    ? 'text-[var(--accent)]'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                {hasFilter ? `机构：${institution}` : '机构⌄'}
              </button>
              {hasFilter && (
                <button
                  onClick={clearInstitution}
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
                      onClick={() => { setInstitution(inst); setMenuOpen(false); setPage(1) }}
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
      </div>

      <div className="space-y-3">
        {data.items.map(report => (
          <ReportCard key={report.id} report={report} backTo={backTo} />
        ))}
      </div>
      <Pagination page={page} pages={data.pages} onPageChange={setPage} />
    </div>
  )
}
