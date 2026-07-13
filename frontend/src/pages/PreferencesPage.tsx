import { useApi } from '../hooks/useApi'
import { getTopics, getTopicPrefs } from '../api/client'
import TopicPrefButtons from '../components/TopicPrefButtons'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { TopicPrefState } from '../api/types'

export default function PreferencesPage() {
  const { data: topicsData, loading: topicsLoading, error: topicsError } = useApi(() => getTopics(), [])
  const { data: prefs, loading: prefsLoading, error: prefsError } = useApi(() => getTopicPrefs(), [])

  if ((topicsLoading && !topicsData) || (prefsLoading && !prefs)) return <LoadingSkeleton />
  if (topicsError || prefsError) {
    return <EmptyState icon="⚠️" title="加载失败" description={topicsError || prefsError || ''} />
  }

  const groups = topicsData?.groups || []

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">主题偏好</h1>
      <p className="text-sm text-gray-500 mb-6">
        订阅的主题不影响首页展示范围，只是方便你在「主题」页快速找到；屏蔽的主题会从首页、日报和搜索结果中隐藏。
      </p>

      {groups.length > 0 ? (
        <div className="space-y-8">
          {groups.map(group => (
            <section key={group.group_name}>
              <h2 className="text-lg font-semibold text-gray-800 mb-3 pb-2 border-b-2 border-blue-400">
                {group.group_name}
              </h2>
              <div className="space-y-2">
                {group.topics.map(topic => {
                  const state: TopicPrefState | null = prefs
                    ? prefs.blocked.includes(topic.slug)
                      ? 'blocked'
                      : prefs.subscribed.includes(topic.slug)
                        ? 'subscribed'
                        : null
                    : null
                  return (
                    <div
                      key={topic.slug}
                      className="flex items-center justify-between gap-3 p-3 border border-gray-200 rounded-lg"
                    >
                      <span className="text-sm text-gray-800">{topic.name}</span>
                      <TopicPrefButtons slug={topic.slug} initialState={state} />
                    </div>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState icon="🏷️" title="暂无主题数据" description="运行 pipeline 后主题将在此显示" />
      )}
    </div>
  )
}
