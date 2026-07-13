import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { getFavorites } from '../api/client'
import ItemCard from '../components/ItemCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'

const backTo = { path: '/favorites', label: '← 返回收藏' }

export default function FavoritesPage() {
  const [page, setPage] = useState(1)
  const { data, loading, error } = useApi(() => getFavorites({ page, per_page: 20 }), [page])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!data || data.items.length === 0) {
    return <EmptyState icon="☆" title="还没有收藏" description="在新闻卡片或详情页点击星标即可收藏" />
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">我的收藏</h1>
      <p className="text-sm text-gray-500 mb-6">{data.total} 条收藏</p>

      <div className="space-y-3">
        {data.items.map(item => (
          <ItemCard key={item.id} item={item} backTo={backTo} />
        ))}
      </div>
      <Pagination page={page} pages={data.pages} onPageChange={setPage} />
    </div>
  )
}
