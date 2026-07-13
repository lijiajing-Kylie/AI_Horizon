import { useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getTopicNews, getTopicPrefs } from '../api/client'
import ItemCard from '../components/ItemCard'
import Pagination from '../components/Pagination'
import BackLink from '../components/BackLink'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import TopicPrefButtons from '../components/TopicPrefButtons'
import type { TopicPrefState } from '../api/types'

export default function TopicDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  // TODO: sort/order/page aren't synced to the URL, so returning here via
  // backTo always lands on page 1 / default sort rather than where the user
  // left off. Worth revisiting alongside URL query state for this page.
  const [sort, setSort] = useState('ai_score')
  const [order, setOrder] = useState('desc')
  const [page, setPage] = useState(1)

  const { data, loading, error } = useApi(
    () => getTopicNews(slug!, { page, per_page: 20, sort, order }),
    [slug, page, sort, order]
  )
  const { data: prefs } = useApi(() => getTopicPrefs(), [])

  const handleSortChange = useCallback((newSort: string, newOrder: string) => {
    setSort(newSort)
    setOrder(newOrder)
    setPage(1)
  }, [])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!data || !data.topic) return <EmptyState icon="📭" title="主题不存在" />

  const { topic, items, total, pages } = data
  const backTo = { path: `/topics/${slug}`, label: `← 返回主题：${topic.name}` }
  const prefState: TopicPrefState | null = prefs
    ? prefs.blocked.includes(slug!)
      ? 'blocked'
      : prefs.subscribed.includes(slug!)
        ? 'subscribed'
        : null
    : null

  return (
    <div>
      {/* Breadcrumb */}
      <BackLink fallback={{ path: '/topics', label: '← 返回主题总览' }} />

      {/* Topic header */}
      <div className="mb-6 p-5 bg-white border border-gray-200 rounded-lg">
        <div className="flex items-start justify-between gap-3">
          <div>
            <span className="text-xs text-gray-400">{topic.group_name}</span>
            <h1 className="text-2xl font-bold text-gray-900 mt-1">{topic.name}</h1>
          </div>
          {prefs && <TopicPrefButtons slug={slug!} initialState={prefState} />}
        </div>
        <p className="text-sm text-gray-500 mt-2">{topic.description}</p>
        <p className="text-sm text-blue-600 font-medium mt-2">{total} 条相关新闻</p>
      </div>

      {prefState === 'blocked' ? (
        <EmptyState icon="🚫" title="你已屏蔽此主题" description="取消屏蔽后可继续查看相关新闻" />
      ) : (
        <>
          {/* Sort bar */}
          <div className="flex items-center gap-2 mb-4 text-sm">
            <span className="text-gray-500">排序：</span>
            <button
              onClick={() => handleSortChange('ai_score', 'desc')}
              className={`px-2.5 py-1 rounded text-xs ${sort === 'ai_score' && order === 'desc' ? 'bg-blue-600 text-white' : 'border border-gray-300 text-gray-600 hover:bg-gray-50'}`}
            >
              评分 ↓
            </button>
            <button
              onClick={() => handleSortChange('published_at', 'desc')}
              className={`px-2.5 py-1 rounded text-xs ${sort === 'published_at' && order === 'desc' ? 'bg-blue-600 text-white' : 'border border-gray-300 text-gray-600 hover:bg-gray-50'}`}
            >
              时间 ↓
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
              <Pagination page={page} pages={pages} onPageChange={setPage} />
            </>
          ) : (
            <EmptyState icon="📭" title="该主题下暂无新闻" />
          )}
        </>
      )}
    </div>
  )
}
