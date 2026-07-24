import { useApi } from '../hooks/useApi'
import { getTopics } from '../api/client'
import TopicCard from '../components/TopicCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import PageEyebrow from '../components/PageEyebrow'
import type { BackTarget } from '../utils/backTo'

const BACK_TO_TOPICS: BackTarget = { path: '/topics', label: '返回主题总览' }

export default function TopicsPage() {
  const { data, loading, error } = useApi(() => getTopics(), [])

  if (loading && !data) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />

  const groups = data?.groups || []

  return (
    <div>
      <div className="mb-10">
        <PageEyebrow>TOPICS</PageEyebrow>
        <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide">主题分类</h1>
        <p className="text-sm text-[var(--muted)] mt-2">按公司与模型 · 技术方向 · 内容形态三维分类浏览</p>
      </div>

      {groups.length > 0 ? (
        <div className="space-y-10">
          {groups.map(group => (
            <section key={group.group_name}>
              <h2 className="text-[22px] font-normal text-[var(--ink)] tracking-wide mb-4">
                {group.group_name}
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {group.topics.map(topic => (
                  <TopicCard key={topic.slug} topic={topic} backTo={BACK_TO_TOPICS} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState
          title="暂无主题数据"
          description="运行 pipeline 后主题将在此显示"
        />
      )}
    </div>
  )
}
