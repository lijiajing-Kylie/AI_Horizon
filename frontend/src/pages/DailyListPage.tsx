import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getDailyDetail, getTopics } from '../api/client'
import { todayStr, formatDate, timeAgo } from '../utils/date'
import { SECTION_NAMES, groupBySection } from '../utils/sections'
import DailyCalendar from '../components/DailyCalendar'
import ScoreBadge from '../components/ScoreBadge'
import TopicCard from '../components/TopicCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { BackTarget } from '../utils/backTo'

const BACK_TO_DAILY: BackTarget = { path: '/daily', label: '返回日报' }
const TOPICS_PREVIEW_COUNT = 6

export default function DailyListPage() {
  const today = todayStr()
  const { data: todayData, loading: todayLoading } = useApi(() => getDailyDetail(today), [today])

  const [selectedDate, setSelectedDate] = useState<string | null>(today)
  const { data: selectedData, loading: selectedLoading } = useApi(
    () => (selectedDate ? getDailyDetail(selectedDate) : Promise.resolve(null)),
    [selectedDate],
  )

  const { data: topicsData } = useApi(() => getTopics(), [])
  let featuredTopics = (topicsData?.groups || []).flatMap(g => g.topics).filter(t => (t.count || 0) > 0)
  if (featuredTopics.length === 0) {
    featuredTopics = (topicsData?.groups || []).flatMap(g => g.topics)
  }
  const displayTopics = featuredTopics.slice(0, TOPICS_PREVIEW_COUNT)

  const todaySections = todayData ? groupBySection(todayData.items) : new Map()
  const todayCards = SECTION_NAMES
    .map(name => ({ name, top: todaySections.get(name)?.[0] }))
    .filter((c): c is { name: string; top: NonNullable<typeof c.top> } => !!c.top)

  return (
    <div>
      {/* ===== Today ===== */}
      <section className="mb-14">
        <div className="flex items-end justify-between gap-6 mb-7">
          <div>
            <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">DAILY BRIEF</p>
            <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide">
              <Link to={`/daily/${today}`} state={{ backTo: BACK_TO_DAILY }} className="hover:text-[var(--accent)] transition-colors">
                今日日报
              </Link>
            </h1>
          </div>
          <Link
            to={`/daily/${today}`}
            state={{ backTo: BACK_TO_DAILY }}
            className="text-sm text-[var(--muted)] mb-1 hover:text-[var(--accent)] transition-colors"
          >
            {formatDate(today)}
          </Link>
        </div>

        {todayLoading && !todayData && <LoadingSkeleton />}

        {todayData && todayCards.length === 0 && (
          <div className="glass rounded-[22px] p-10 text-center text-[var(--muted)]">
            <p>今日暂无日报数据</p>
            <p className="text-xs mt-1">等待 GitHub Actions 定时运行 pipeline 后会生成</p>
          </div>
        )}

        {todayCards.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {todayCards.map(({ name, top }) => {
              const title = top.metadata?.title_zh || top.title
              return (
                <article
                  key={name}
                  className="glass news-card rounded-[26px] p-6 flex flex-col justify-between min-h-[300px]"
                >
                  <div>
                    <span className="text-xs font-bold tracking-wider" style={{ color: 'var(--accent)' }}>{name}</span>
                    <h2 className="mt-3 text-[17px] font-medium text-[var(--ink)] leading-snug">
                      <Link to={`/items/${top.id}`} state={{ backTo: BACK_TO_DAILY }} className="hover:opacity-80">
                        {title}
                      </Link>
                    </h2>
                    {top.ai_summary && (
                      <p className="mt-3 text-[13px] text-[var(--muted)] leading-relaxed line-clamp-3">{top.ai_summary}</p>
                    )}
                  </div>
                  <div className="flex items-center justify-between mt-6 text-[11px] text-[var(--muted)]">
                    <span>{timeAgo(top.published_at || top.fetched_at)}</span>
                    <Link
                      to={`/items/${top.id}`}
                      state={{ backTo: BACK_TO_DAILY }}
                      className="text-xs font-semibold"
                      style={{ color: 'var(--accent)' }}
                    >
                      阅读全文 ›
                    </Link>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      {/* ===== Archive ===== */}
      <section>
        <div className="mb-6">
          <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">PAST DAILY</p>
          <h2 className="text-[22px] font-normal text-[var(--ink)] tracking-wide">往日日报</h2>
        </div>

        <div className="flex flex-col lg:flex-row gap-6 items-stretch">
          <div className="w-full lg:w-[30%] shrink-0 flex flex-col">
            <DailyCalendar selectedDate={selectedDate} onSelectDate={setSelectedDate} />
          </div>

          <div className="flex-1 min-w-0 glass rounded-[22px] p-4 flex flex-col max-h-[360px]">
            {!selectedDate && (
              <div className="flex-1 flex items-center justify-center">
                <EmptyState title="点击左侧日期" description="查看当天的日报内容" />
              </div>
            )}

            {selectedDate && selectedLoading && !selectedData && <LoadingSkeleton />}

            {selectedDate && selectedData && (
              <div className="flex flex-col flex-1 min-h-0">
                <div className="mb-3 shrink-0">
                  <Link
                    to={`/daily/${selectedDate}`}
                    state={{ backTo: BACK_TO_DAILY }}
                    className="text-base font-medium text-[var(--ink)] hover:text-[var(--accent)] transition-colors"
                  >
                    {formatDate(selectedDate)}
                  </Link>
                </div>

                {selectedData.items.length === 0 ? (
                  <EmptyState title="该日暂无内容" />
                ) : (
                  <div className="space-y-1 flex-1 overflow-y-auto min-h-0 pr-1">
                    {selectedData.items.map(item => (
                      <Link
                        key={item.id}
                        to={`/items/${item.id}`}
                        state={{ backTo: BACK_TO_DAILY }}
                        className="flex items-start gap-2 p-2 rounded-lg hover:bg-white/70 transition-colors"
                      >
                        <ScoreBadge score={item.ai_score} size="sm" />
                        <span className="text-sm text-[#3d4a5f] leading-snug line-clamp-2">
                          {item.metadata?.title_zh || item.title}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ===== Topics ===== */}
      <section className="mt-14">
        <div className="mb-6">
          <p className="text-[11px] font-bold tracking-[.21em] text-[#8ea0b6] mb-2">TOPICS</p>
          <h2 className="text-[22px] font-normal text-[var(--ink)] tracking-wide">
            <Link to="/topics" className="text-[var(--ink)] hover:text-[var(--accent)] transition-colors">
              主题分类
            </Link>
          </h2>
        </div>

        {displayTopics.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {displayTopics.map(topic => (
              <TopicCard key={topic.slug} topic={topic} backTo={BACK_TO_DAILY} />
            ))}
          </div>
        ) : (
          <EmptyState title="暂无主题数据" description="运行 pipeline 后主题将在此显示" />
        )}
      </section>
    </div>
  )
}
