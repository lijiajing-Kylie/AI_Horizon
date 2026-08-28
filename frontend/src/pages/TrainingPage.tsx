import { useCallback } from 'react'
import { useSearchParams, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { getItems } from '../api/client'
import ItemCard from '../components/ItemCard'
import Pagination from '../components/Pagination'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import type { BackTarget } from '../utils/backTo'

export default function TrainingPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  const page = Number(searchParams.get('page') ?? '1')

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

  // Training items are selected by the independent training gate and are not
  // news-scored — list every one chronologically (newest first).
  const { data, loading, error } = useApi(
    () => getItems({ is_training: true, sort: 'published_at', order: 'desc', page, per_page: 20 }),
    [page],
  )

  useScrollRestoration(location.pathname + location.search)

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!data) return <EmptyState title="暂无数据" />

  const { items, total, pages } = data
  const backTo: BackTarget = { path: '/training' + location.search, label: '返回' }

  return (
    <div>
      {/* Training header — 与论文/报告列表页一致的大字标题 */}
      <PageEyebrow>TRAINING</PageEyebrow>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-2">培训相关</h1>
      <p className="text-sm text-[var(--muted)] mb-2">结合AI/科技的创新方法论，可能对员工培训与组织管理等方面有启发</p>
      <p className="text-sm text-[var(--accent)] font-medium mb-6">{total} 条培训内容</p>

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
        <EmptyState title="暂无培训内容" description="运行 pipeline 后，通过培训相关度门槛的内容将在此显示" />
      )}
    </div>
  )
}
