import { useApi } from '../hooks/useApi'
import { getDailyList } from '../api/client'
import DailyReportCard from '../components/DailyReportCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'

export default function DailyListPage() {
  const { data, loading, error } = useApi(() => getDailyList(30), [])

  if (loading) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />

  const reports = data?.reports || []

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">📰 日报列表</h1>

      {reports.length > 0 ? (
        <div className="space-y-3">
          {reports.map(report => (
            <DailyReportCard key={report.date} report={report} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon="📭"
          title="暂无日报"
          description="运行 pipeline 后日报将在此显示"
        />
      )}
    </div>
  )
}
