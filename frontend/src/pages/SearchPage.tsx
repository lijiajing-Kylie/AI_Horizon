import { useState, useEffect, useCallback, type FormEvent } from 'react'
import { useSearchParams, Link, useLocation } from 'react-router-dom'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { globalSearch } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import ItemCard from '../components/ItemCard'
import PaperCard from '../components/PaperCard'
import ReportCard from '../components/ReportCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import type {
  GlobalSearchResponse,
  NewsItem,
  Paper,
  Report,
} from '../api/types'

type SectionKey = 'news' | 'papers' | 'reports'

const SECTION_LABELS: Record<SectionKey, string> = {
  news: '新闻',
  papers: '论文',
  reports: '报告',
}

const PER_PAGE = 10

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const q = searchParams.get('q') ?? ''
  const [input, setInput] = useState(q)

  // ── Derive per-section page & sort from URL params ─────────────────────
  const newsPage = Number(searchParams.get('np') ?? '1')
  const papersPage = Number(searchParams.get('pp') ?? '1')
  const reportsPage = Number(searchParams.get('rp') ?? '1')
  const sortBy = (searchParams.get('sort') ?? 'relevance') as 'relevance' | 'published_at'

  // ── UI-only state ──────────────────────────────────────────────────────
  const [collapsedSections, setCollapsedSections] = useState<Set<SectionKey>>(new Set())

  // Keep the input in sync when q changes externally
  useEffect(() => {
    setInput(q)
  }, [q])

  // Helper: merge params with replace so we don't flood history
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(updates)) {
          if (value === null || value === undefined || value === '') {
            next.delete(key)
          } else {
            next.set(key, value)
          }
        }
        return next
      }, { replace: true })
    },
    [setSearchParams],
  )

  const { data, loading, error } = useApi(
    () => {
      if (!q.trim()) return Promise.resolve(null)
      return globalSearch({
        q: q.trim(),
        per_page: PER_PAGE,
        news_page: newsPage,
        papers_page: papersPage,
        reports_page: reportsPage,
        sort: sortBy,
        order: 'desc',
      })
    },
    [q, newsPage, papersPage, reportsPage, sortBy],
  )

  // ── Dynamic backTo ─────────────────────────────────────────────────────
  const backTo = {
    path: q ? '/search' + location.search : '/search',
    label: '返回搜索',
  }

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  function submit(e: FormEvent) {
    e.preventDefault()
    const trimmed = input.trim()
    if (trimmed) {
      updateParams({ q: trimmed, np: null, pp: null, rp: null, sort: null })
    } else {
      setSearchParams({}, { replace: true })
    }
  }

  const toggleSection = useCallback((key: SectionKey) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  function renderSection(
    key: SectionKey,
    section: GlobalSearchResponse[SectionKey] | undefined,
    page: number,
    onPageChange: (p: number) => void,
    renderItem: (item: NewsItem | Paper | Report) => React.ReactNode,
    viewAllLink?: string,
  ) {
    if (!section || section.total === 0) return null

    const collapsed = collapsedSections.has(key)

    return (
      <section className="rounded-[22px] p-5 bg-[var(--card)]">
        {/* Section header — clickable toggle */}
        <button
          onClick={() => toggleSection(key)}
          className="w-full flex items-center gap-2 text-left cursor-pointer"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4 text-[var(--muted)] shrink-0" strokeWidth={2} />
          ) : (
            <ChevronDown className="w-4 h-4 text-[var(--muted)] shrink-0" strokeWidth={2} />
          )}
          <h2 className="text-sm font-semibold text-[var(--accent)]">
            {SECTION_LABELS[key]}
            <span className="text-sm font-normal text-[var(--muted)] ml-2">
              {section.total} 条
            </span>
          </h2>
        </button>

        {/* Collapsible content */}
        {!collapsed && (
          <div className="mt-4">
            <div className="space-y-3">
              {section.items.map((item: unknown) => (
                <>{renderItem(item as NewsItem | Paper | Report)}</>
              ))}
            </div>

            {section.pages > 1 && (
              <Pagination
                page={page}
                pages={section.pages}
                onPageChange={onPageChange}
              />
            )}

            {viewAllLink && section.total > section.items.length && (
              <div className="text-center mt-3">
                <Link
                  to={viewAllLink}
                  className="inline-block text-sm text-[var(--accent)] hover:opacity-80 font-medium"
                >
                  查看全部 {section.total} 条{SECTION_LABELS[key]}结果
                </Link>
              </div>
            )}
          </div>
        )}
      </section>
    )
  }

  // Compute total count across all sections
  const allCount = (() => {
    if (!data) return 0
    let total = 0
    for (const key of ['news', 'papers', 'reports'] as const) {
      total += data[key]?.total ?? 0
    }
    return total
  })()

  return (
    <div>
      <PageEyebrow>SEARCH</PageEyebrow>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-1">搜索</h1>
      <p className="text-sm text-[var(--muted)] mb-6">按关键词搜索新闻、论文和报告</p>

      <form onSubmit={submit} className="flex gap-2 mb-6">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="输入关键词，例如 OpenAI、芯片、GitHub..."
          autoFocus
          className="flex-1 border border-[var(--line)] rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80 transition-opacity"
        >
          搜索
        </button>
      </form>

      {!q.trim() && (
        <EmptyState title="输入关键词开始搜索" description="支持搜索新闻、论文和报告" />
      )}

      {q.trim() !== '' && loading && !data && <LoadingSkeleton />}

      {q.trim() !== '' && error && (
        <EmptyState title="搜索失败" description={error} />
      )}

      {q.trim() !== '' && !loading && !error && data && allCount === 0 && (
        <EmptyState title="没有找到相关内容" description={`没有匹配 "${q}" 的结果`} />
      )}

      {q.trim() !== '' && data && allCount > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-[var(--muted)]">共找到 {allCount} 条结果</p>
            <div className="flex items-center gap-1 text-xs">
              <button
                onClick={() => updateParams({ sort: null, np: null, pp: null, rp: null })}
                className={`px-2.5 py-1 rounded-full font-medium transition-colors ${
                  sortBy === 'relevance'
                    ? 'bg-[var(--accent)] text-white'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                相关度
              </button>
              <button
                onClick={() => updateParams({ sort: 'published_at', np: null, pp: null, rp: null })}
                className={`px-2.5 py-1 rounded-full font-medium transition-colors ${
                  sortBy === 'published_at'
                    ? 'bg-[var(--accent)] text-white'
                    : 'text-[var(--muted)] hover:text-[var(--ink)]'
                }`}
              >
                最新
              </button>
            </div>
          </div>

          <div className="space-y-4">
            {/* News */}
            {renderSection(
              'news',
              data.news,
              newsPage,
              p => updateParams({ np: p === 1 ? null : String(p) }),
              item => <ItemCard key={(item as NewsItem).id} item={item as NewsItem} backTo={backTo} />,
            )}

            {/* Papers */}
            {renderSection(
              'papers',
              data.papers,
              papersPage,
              p => updateParams({ pp: p === 1 ? null : String(p) }),
              item => <PaperCard key={(item as Paper).id} paper={item as Paper} backTo={backTo} />,
              `/papers?search=${encodeURIComponent(q.trim())}`,
            )}

            {/* Reports */}
            {renderSection(
              'reports',
              data.reports,
              reportsPage,
              p => updateParams({ rp: p === 1 ? null : String(p) }),
              item => <ReportCard key={(item as Report).id} report={item as Report} backTo={backTo} />,
              `/reports?search=${encodeURIComponent(q.trim())}`,
            )}
          </div>
        </div>
      )}
    </div>
  )
}
