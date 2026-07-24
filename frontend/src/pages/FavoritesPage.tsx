import { useState, useCallback } from 'react'
import { Link, useSearchParams, useLocation } from 'react-router-dom'
import { ChevronDown, ChevronRight, BookmarkX } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getFavorites, getPaperFavorites, getReportFavorites } from '../api/client'
import ItemCard from '../components/ItemCard'
import PaperCard from '../components/PaperCard'
import ReportCard from '../components/ReportCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import type { BackTarget } from '../utils/backTo'

// Collapsed section ids, tracked outside React state so a section stays
// collapsed across navigating to a detail page and back (same pattern as
// SectionBlock.tsx).
const collapsedSections = new Set<string>()

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

interface CollapsibleSectionProps {
  sectionId: string
  title: string
  loading: boolean
  hasData: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  items: any[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderItem: (item: any) => React.ReactNode
  page: number
  pages: number
  onPageChange: (p: number) => void
}

function CollapsibleSection({
  sectionId,
  title,
  loading,
  hasData,
  items,
  renderItem,
  page,
  pages,
  onPageChange,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(() => !collapsedSections.has(sectionId))

  const toggle = () => {
    setExpanded(prev => {
      const next = !prev
      if (next) collapsedSections.delete(sectionId)
      else collapsedSections.add(sectionId)
      return next
    })
  }

  return (
    <section className="mb-10">
      <h2
        onClick={toggle}
        className="flex items-center gap-1.5 text-sm font-semibold mb-4 pb-2 border-b-2 border-[var(--accent)] text-[var(--accent)] cursor-pointer select-none"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 shrink-0" />
        )}
        {expanded ? (
          <>
            {title} <span className="text-sm font-normal text-[var(--muted)] ml-2">{items.length} 条</span>
          </>
        ) : (
          <span>{title}（{items.length}）</span>
        )}
      </h2>

      {loading && !items.length && <LoadingSkeleton />}

      {expanded && hasData && (
        <>
          <div className="space-y-3">
            {items.map(item => renderItem(item))}
          </div>
          {pages > 1 && (
            <div className="mt-4">
              <Pagination page={page} pages={pages} onPageChange={onPageChange} />
            </div>
          )}
        </>
      )}
    </section>
  )
}

export default function FavoritesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  // ── Derive per-section page from URL params ────────────────────────────
  const newsPage = Number(searchParams.get('np') ?? '1')
  const papersPage = Number(searchParams.get('pp') ?? '1')
  const reportsPage = Number(searchParams.get('rp') ?? '1')

  // ── URL param helper ───────────────────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams(prev => mergeParams(prev, updates), { replace: true })
    },
    [setSearchParams],
  )

  const { data: newsData, loading: newsLoading } = useApi(
    () => getFavorites({ page: newsPage, per_page: 20 }),
    [newsPage],
  )
  const { data: papersData, loading: papersLoading } = useApi(
    () => getPaperFavorites({ page: papersPage, per_page: 20 }),
    [papersPage],
  )
  const { data: reportsData, loading: reportsLoading } = useApi(
    () => getReportFavorites({ page: reportsPage, per_page: 20 }),
    [reportsPage],
  )

  const allLoaded = !newsLoading && !papersLoading && !reportsLoading
  const allEmpty = allLoaded &&
    (!newsData || newsData.items.length === 0) &&
    (!papersData || papersData.items.length === 0) &&
    (!reportsData || reportsData.items.length === 0)
  const initialLoading = !allLoaded && !newsData && !papersData && !reportsData

  // ── Dynamic backTo ─────────────────────────────────────────────────────
  const backToFavorites: BackTarget = {
    path: '/favorites' + location.search,
    label: '返回收藏',
  }

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  return (
    <div>
      <PageEyebrow>FAVORITES</PageEyebrow>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-6">我的收藏</h1>

      {initialLoading ? (
        <LoadingSkeleton />
      ) : allEmpty ? (
        <EmptyState
          title="还没有收藏"
          description="你收藏的内容会显示在这里"
          icon={<BookmarkX className="w-10 h-10 text-[var(--accent)]" strokeWidth={1.5} />}
        >
          <Link
            to="/daily"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
          >
            浏览日报
          </Link>
          <Link
            to="/papers"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
          >
            浏览论文
          </Link>
          <Link
            to="/reports"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors"
          >
            浏览报告
          </Link>
        </EmptyState>
      ) : (
        <>
          <CollapsibleSection
            sectionId="fav-news"
            title="新闻"
            loading={newsLoading}
            hasData={!!(newsData && newsData.items.length > 0)}
            items={newsData?.items ?? []}
            renderItem={(item) => <ItemCard key={item.id} item={item} backTo={backToFavorites} />}
            page={newsPage}
            pages={newsData?.pages ?? 0}
            onPageChange={p => updateParams({ np: p === 1 ? null : String(p) })}
          />

          <CollapsibleSection
            sectionId="fav-papers"
            title="论文"
            loading={papersLoading}
            hasData={!!(papersData && papersData.items.length > 0)}
            items={papersData?.items ?? []}
            renderItem={(paper) => <PaperCard key={paper.id} paper={paper} backTo={backToFavorites} />}
            page={papersPage}
            pages={papersData?.pages ?? 0}
            onPageChange={p => updateParams({ pp: p === 1 ? null : String(p) })}
          />

          <CollapsibleSection
            sectionId="fav-reports"
            title="报告"
            loading={reportsLoading}
            hasData={!!(reportsData && reportsData.items.length > 0)}
            items={reportsData?.items ?? []}
            renderItem={(report) => <ReportCard key={report.id} report={report} backTo={backToFavorites} />}
            page={reportsPage}
            pages={reportsData?.pages ?? 0}
            onPageChange={p => updateParams({ rp: p === 1 ? null : String(p) })}
          />
        </>
      )}
    </div>
  )
}
