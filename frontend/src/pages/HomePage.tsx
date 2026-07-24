import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getDailyDetail, getPapers, getReports } from '../api/client'
import { todayStr } from '../utils/date'
import ScoreBadge from '../components/ScoreBadge'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import type { NewsItem, Paper, Report } from '../api/types'
import type { BackTarget } from '../utils/backTo'

const TOP_ITEMS_COUNT = 3
const BACK_TO_HOME: BackTarget = { path: '/', label: '返回首页' }

interface ColumnProps {
  eyebrow: string
  title: string
  to: string
  children: ReactNode
}

function Column({ eyebrow, title, to, children }: ColumnProps) {
  return (
    <section className="glass news-card rounded-[22px] p-5">
      <div className="flex items-end justify-between gap-4 mb-4">
        <div>
          <p className="text-[10px] font-bold tracking-[.18em] text-[#8ea0b6] mb-1.5">{eyebrow}</p>
          <Link to={to} className="text-lg font-normal text-[var(--ink)] hover:text-[var(--accent)] tracking-wide transition-colors">
            {title}
          </Link>
        </div>
      </div>
      {children}
    </section>
  )
}

function ComingSoon({ label }: { label: string }) {
  return <p className="text-sm text-[var(--muted)] text-center py-8">{label}暂无数据，敬请期待</p>
}

export default function HomePage() {
  const today = todayStr()
  const isOrganic = document.documentElement.getAttribute('data-theme') === 'organic'
  const { data: dailyData, loading, error } = useApi(() => getDailyDetail(today), [today])
  const { data: reportsData } = useApi(() => getReports({ per_page: 3 }), [])
  const { data: papersData } = useApi(() => getPapers({ sort: 'published_at', order: 'desc', per_page: 3 }), [])

  const topItems: NewsItem[] = dailyData?.items?.slice(0, TOP_ITEMS_COUNT) || []
  const topReports: Report[] = reportsData?.items || []
  const topPapers: Paper[] = papersData?.items || []

  if (loading && !dailyData) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-stretch">
      {/* Left half: 日报 / 论文 / 报告 columns */}
      <div className="space-y-6">
        <Column eyebrow="TODAY" title="日报" to={`/daily/${today}`}>
          {topItems.length > 0 ? (
            <div className="space-y-3">
              {topItems.map(item => (
                <div key={item.id} className="flex items-start gap-2">
                  <ScoreBadge score={item.ai_score} size="sm" />
                  <Link
                    to={`/items/${item.id}`}
                    state={{ backTo: BACK_TO_HOME }}
                    className="text-sm text-[#3d4a5f] hover:text-[var(--accent)] leading-snug line-clamp-2"
                  >
                    {item.metadata?.title_zh || item.title}
                  </Link>
                </div>
              ))}
            </div>
          ) : (
            <ComingSoon label="今日日报" />
          )}
        </Column>

        <Column eyebrow="PAPERS" title="论文" to="/papers">
          {topPapers.length > 0 ? (
            <div className="space-y-3">
              {topPapers.map(paper => (
                <div key={paper.id} className="flex flex-col gap-0.5">
                  <Link
                    to={`/papers/${paper.id}`}
                    state={{ backTo: BACK_TO_HOME }}
                    className="text-sm text-[#3d4a5f] hover:text-[var(--accent)] leading-snug line-clamp-2"
                  >
                    {paper.title_zh || paper.title}
                  </Link>
                  <span className="text-xs text-[var(--muted)]">
                    {paper.authors?.slice(0, 3).join(', ')}
                    {paper.authors?.length > 3 && ' 等'}
                    {paper.published_at && <> · {paper.published_at.slice(0, 10)}</>}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <ComingSoon label="论文库" />
          )}
        </Column>

        <Column eyebrow="REPORTS" title="报告" to="/reports">
          {topReports.length > 0 ? (
            <div className="space-y-3">
              {topReports.map(report => (
                <div key={report.id} className="flex flex-col gap-0.5">
                  <Link
                    to={`/reports/${report.id}`}
                    state={{ backTo: BACK_TO_HOME }}
                    className="text-sm text-[#3d4a5f] hover:text-[var(--accent)] leading-snug line-clamp-2"
                  >
                    {report.title}
                  </Link>
                  <span className="text-xs text-[var(--muted)]">
                    {report.institution}
                    {report.published_at && <> · {report.published_at.slice(0, 10)}</>}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <ComingSoon label="报告库" />
          )}
        </Column>
      </div>

      {/* Right half: hero image — absolute-fill so it's cropped from top if taller than left column */}
      <div className="hidden lg:relative lg:block overflow-hidden rounded-[26px]">
        <img
          src={isOrganic ? '/pexels-markus-winkler-1430818-19813735.jpg' : '/pexels-cottonbro-3951353.jpg'}
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-bottom"
        />
      </div>
    </div>
  )
}
