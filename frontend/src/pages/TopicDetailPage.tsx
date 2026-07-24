import { useCallback } from 'react'
import { useParams, useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { useTopicPrefsState } from '../hooks/useTopicPrefs'
import { getTopicNews } from '../api/client'
import ItemCard from '../components/ItemCard'
import Pagination from '../components/Pagination'
import BackLink from '../components/BackLink'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import TopicPrefButtons from '../components/TopicPrefButtons'
import { ArrowDown } from 'lucide-react'

export default function TopicDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  // ── Derive state from URL params ───────────────────────────────────────
  const sort = searchParams.get('sort') ?? 'ai_score'
  const order = searchParams.get('order') ?? 'desc'
  const page = Number(searchParams.get('page') ?? '1')

  // ── URL param helper ───────────────────────────────────────────────────
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
    () => getTopicNews(slug!, { page, per_page: 20, sort, order }),
    [slug, page, sort, order],
  )
  const { prefs, setPref } = useTopicPrefsState()

  // ── Scroll restoration ─────────────────────────────────────────────────
  useScrollRestoration(location.pathname + location.search)

  const handleSortChange = useCallback(
    (newSort: string, newOrder: string) => {
      updateParams({
        sort: newSort === 'ai_score' ? null : newSort,
        order: newOrder === 'desc' ? null : newOrder,
        page: null,
      })
    },
    [updateParams],
  )

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!data || !data.topic) return <EmptyState title="主题不存在" />

  const { topic, items, total, pages } = data
  const backTo = {
    path: `/topics/${slug}` + location.search,
    label: `返回主题：${topic.name}`,
  }
  const prefState = prefs?.[slug!] ?? null

  return (
    <div>
      {/* Breadcrumb */}
      <BackLink fallback={{ path: '/topics', label: '返回主题总览' }} />

      {/* Topic header */}
      <header className="glass news-card rounded-[28px] p-7 mb-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold tracking-[.18em] text-[#8ea0b6] mb-1.5">{topic.group_name}</p>
            <h1 className="text-xl font-semibold text-[var(--ink)] leading-snug">{topic.name}</h1>
          </div>
          {prefs && (
            <TopicPrefButtons state={prefState} onToggle={next => setPref(slug!, next)} />
          )}
        </div>
        <p className="text-sm text-[var(--muted)] mt-2">{topic.description}</p>
        <p className="text-sm text-[var(--accent)] font-medium mt-2">{total} 条相关新闻</p>
      </header>

      {prefState === 'blocked' ? (
        <EmptyState title="你已屏蔽此主题" description="取消屏蔽后可继续查看相关新闻" />
      ) : (
        <>
          {/* Sort bar */}
          <div className="flex items-center gap-2 mb-4 text-sm">
            <span className="text-[var(--muted)]">排序：</span>
            <button
              onClick={() => handleSortChange('ai_score', 'desc')}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs transition-colors ${sort === 'ai_score' && order === 'desc' ? 'bg-[var(--accent)] text-white' : 'border border-[var(--line)] text-[var(--muted)] hover:bg-white/70'}`}
            >
              评分
              <ArrowDown size={13} strokeWidth={1.5} />
            </button>
            <button
              onClick={() => handleSortChange('published_at', 'desc')}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs transition-colors ${sort === 'published_at' && order === 'desc' ? 'bg-[var(--accent)] text-white' : 'border border-[var(--line)] text-[var(--muted)] hover:bg-white/70'}`}
            >
              时间
              <ArrowDown size={13} strokeWidth={1.5} />
            </button>
          </div>

          {/* Items */}
          {items.length > 0 ? (
            <>
              <div className="space-y-3">
                {items.map(item => (
                  <ItemCard key={item.id} item={item} backTo={backTo} />
                ))}
              </div>
              <Pagination page={page} pages={pages} onPageChange={p => updateParams({ page: p === 1 ? null : String(p) })} />
            </>
          ) : (
            <EmptyState title="该主题下暂无新闻" />
          )}
        </>
      )}
    </div>
  )
}
