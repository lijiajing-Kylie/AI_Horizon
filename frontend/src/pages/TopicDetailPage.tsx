import { useState, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getTopicNews } from '../api/client'
import ItemCard from '../components/ItemCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'

function BackLink() {
  const [params] = useSearchParams()
  const from = params.get('from')
  if (from === '/') {
    return (
      <Link to="/" className="text-sm text-blue-600 hover:text-blue-700 mb-2 inline-block">
        ← 返回首页
      </Link>
    )
  }
  return (
    <Link to="/topics" className="text-sm text-blue-600 hover:text-blue-700 mb-2 inline-block">
      ← 返回主题总览
    </Link>
  )
}

export default function TopicDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const [sort, setSort] = useState('ai_score')
  const [order, setOrder] = useState('desc')
  const [page, setPage] = useState(1)

  const { data, loading, error } = useApi(
    () => getTopicNews(slug!, { page, per_page: 20, sort, order }),
    [slug, page, sort, order]
  )

  const handleSortChange = useCallback((newSort: string, newOrder: string) => {
    setSort(newSort)
    setOrder(newOrder)
    setPage(1)
  }, [])

  if (loading) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!data || !data.topic) return <EmptyState icon="📭" title="主题不存在" />

  const { topic, items, total, pages } = data

  return (
    <div>
      {/* Breadcrumb */}
      <BackLink />

      {/* Topic header */}
      <div className="mb-6 p-5 bg-white border border-gray-200 rounded-lg">
        <span className="text-xs text-gray-400">{topic.group_name}</span>
        <h1 className="text-2xl font-bold text-gray-900 mt-1">{topic.name}</h1>
        <p className="text-sm text-gray-500 mt-2">{topic.description}</p>
        <p className="text-sm text-blue-600 font-medium mt-2">{total} 条相关新闻</p>
      </div>

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
              <ItemCard key={item.id} item={item} />
            ))}
          </div>
          <Pagination page={page} pages={pages} onPageChange={setPage} />
        </>
      ) : (
        <EmptyState icon="📭" title="该主题下暂无新闻" />
      )}
    </div>
  )
}
