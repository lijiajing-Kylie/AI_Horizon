import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getDailyDetail, getTopics } from '../api/client'
import { todayStr, formatDate } from '../utils/date'
import ScoreBadge from '../components/ScoreBadge'
import TopicCard from '../components/TopicCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { NewsItem } from '../api/types'

const TOP_ITEMS_COUNT = 5
const TOPICS_PREVIEW_COUNT = 6

export default function HomePage() {
  const today = todayStr()
  const { data: dailyData, loading, error } = useApi(() => getDailyDetail(today), [today])
  const { data: topicsData } = useApi(() => getTopics(), [])

  const topItems: NewsItem[] = dailyData?.items?.slice(0, TOP_ITEMS_COUNT) || []

  // Pick featured topics from each group
  let featuredTopics = (topicsData?.groups || []).flatMap(g => g.topics).filter(t => (t.count || 0) > 0)
  if (featuredTopics.length === 0) {
    featuredTopics = (topicsData?.groups || []).flatMap(g => g.topics)
  }
  const displayTopics = featuredTopics.slice(0, TOPICS_PREVIEW_COUNT)

  if (loading) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />

  return (
    <div>
      {/* ===== Daily Report Preview ===== */}
      <section className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">今日 AI 日报</h1>
            <p className="text-sm text-gray-400 mt-1">{formatDate(today)}</p>
          </div>
          <Link
            to={`/daily/${today}`}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            查看完整日报 →
          </Link>
        </div>

        {topItems.length > 0 ? (
          <div className="space-y-3">
            {topItems.map(item => (
              <div key={item.id} className="border border-gray-200 rounded-lg p-4 hover:border-blue-200 transition-colors bg-white">
                <div className="flex items-start gap-2 mb-1">
                  <ScoreBadge score={item.ai_score} size="sm" />
                  <h3 className="text-sm font-medium text-gray-900 leading-snug">
                    <a href={item.url} target="_blank" rel="noopener noreferrer" className="hover:text-blue-600">
                      {item.metadata?.title_zh || item.title}
                    </a>
                  </h3>
                </div>
                {item.ai_summary && (
                  <p className="text-xs text-gray-500 ml-8 line-clamp-1">{item.ai_summary}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-400">
            <p>今日暂无日报数据</p>
            <p className="text-xs mt-1">等待 GitHub Actions 定时运行 pipeline 后会生成</p>
          </div>
        )}
      </section>

      {/* ===== Topic Entry ===== */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">主题分类</h2>
          <Link
            to="/topics"
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            查看全部主题 →
          </Link>
        </div>

        {displayTopics.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {displayTopics.map(topic => (
              <TopicCard key={topic.slug} topic={topic} from="/" />
            ))}
          </div>
        ) : (
          <EmptyState icon="🏷️" title="暂无主题数据" description="运行 pipeline 后主题将在此显示" />
        )}
      </section>
    </div>
  )
}
