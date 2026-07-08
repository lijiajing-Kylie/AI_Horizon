import { useApi } from '../hooks/useApi'
import { getTopics } from '../api/client'
import TopicCard from '../components/TopicCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { BackTarget } from '../utils/backTo'

const BACK_TO_TOPICS: BackTarget = { path: '/topics', label: '← 返回主题总览' }

export default function TopicsPage() {
  const { data, loading, error } = useApi(() => getTopics(), [])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />

  const groups = data?.groups || []

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">🏷️ 主题分类</h1>
      <p className="text-sm text-gray-400 -mt-4 mb-6">按公司与模型 · 技术方向 · 内容形态三维分类浏览</p>

      {groups.length > 0 ? (
        <div className="space-y-8">
          {groups.map(group => (
            <section key={group.group_name}>
              <h2 className="text-lg font-semibold text-gray-800 mb-3 pb-2 border-b-2 border-blue-400">
                {group.group_name}
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {group.topics.map(topic => (
                  <TopicCard key={topic.slug} topic={topic} backTo={BACK_TO_TOPICS} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState
          icon="🏷️"
          title="暂无主题数据"
          description="运行 pipeline 后主题将在此显示"
        />
      )}
    </div>
  )
}
