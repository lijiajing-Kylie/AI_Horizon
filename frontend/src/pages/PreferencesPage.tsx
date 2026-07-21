import { useApi } from '../hooks/useApi'
import { useTopicPrefsState } from '../hooks/useTopicPrefs'
import { getTopics } from '../api/client'
import TopicPrefButtons from '../components/TopicPrefButtons'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { Topic } from '../api/types'

export default function PreferencesPage() {
  const { data: topicsData, loading: topicsLoading, error: topicsError } = useApi(
    () => getTopics({ include_blocked: true }),
    []
  )
  const { prefs, loading: prefsLoading, error: prefsError, setPref } = useTopicPrefsState()

  if ((topicsLoading && !topicsData) || (prefsLoading && !prefs)) return <LoadingSkeleton />
  if (topicsError || prefsError) {
    return <EmptyState title="加载失败" description={topicsError || prefsError || ''} />
  }

  const groups = topicsData?.groups || []
  const allTopics: Topic[] = groups.flatMap(g => g.topics)
  const topicBySlug = new Map(allTopics.map(t => [t.slug, t]))

  const subscribedSlugs = Object.entries(prefs || {})
    .filter(([, state]) => state === 'subscribed')
    .map(([slug]) => slug)
  const blockedSlugs = Object.entries(prefs || {})
    .filter(([, state]) => state === 'blocked')
    .map(([slug]) => slug)
  const hasAnyPref = subscribedSlugs.length > 0 || blockedSlugs.length > 0

  const summaryRow = (slug: string) => {
    const topic = topicBySlug.get(slug)
    return (
      <div key={slug} className="flex items-center justify-between gap-3 py-2">
        <span className="text-sm text-[var(--ink)]">{topic?.name ?? slug}</span>
        <TopicPrefButtons state={prefs?.[slug] ?? null} onToggle={next => setPref(slug, next)} />
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-1">主题偏好</h1>
      <p className="text-sm text-[var(--muted)] mb-6">
        订阅功能暂未推出，敬请期待；屏蔽的主题会从首页、日报、主题总览和搜索结果中隐藏。
      </p>

      {hasAnyPref && (
        <details className="mb-8 border border-[var(--line)] rounded-lg overflow-hidden" open>
          <summary className="cursor-pointer select-none px-4 py-3 bg-[var(--accent)]/5 text-sm font-medium text-[var(--ink)]">
            我的订阅与屏蔽（订阅 {subscribedSlugs.length} · 屏蔽 {blockedSlugs.length}）
          </summary>
          <div className="px-4 py-2 divide-y divide-[var(--line)]/40">
            {subscribedSlugs.length > 0 && (
              <div className="py-2">
                <h3 className="text-xs font-semibold text-[var(--accent)] uppercase tracking-wide mb-1">已订阅</h3>
                {subscribedSlugs.map(summaryRow)}
              </div>
            )}
            {blockedSlugs.length > 0 && (
              <div className="py-2">
                <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-1">已屏蔽</h3>
                {blockedSlugs.map(summaryRow)}
              </div>
            )}
          </div>
        </details>
      )}

      {groups.length > 0 ? (
        <div className="space-y-8">
          {groups.map(group => (
            <section key={group.group_name}>
              <h2 className="text-[22px] font-normal text-[var(--ink)] tracking-wide mb-4">
                {group.group_name}
              </h2>
              <div className="space-y-2">
                {group.topics.map(topic => (
                  <div
                    key={topic.slug}
                    className="flex items-center justify-between gap-3 p-3 border border-[var(--line)] rounded-lg"
                  >
                    <span className="text-sm text-[var(--ink)]">{topic.name}</span>
                    <TopicPrefButtons
                      state={prefs?.[topic.slug] ?? null}
                      onToggle={next => setPref(topic.slug, next)}
                    />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState title="暂无主题数据" description="运行 pipeline 后主题将在此显示" />
      )}
    </div>
  )
}
