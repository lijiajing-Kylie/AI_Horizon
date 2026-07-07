import { Link } from 'react-router-dom'
import type { DailyReport } from '../api/types'
import { formatDate } from '../utils/date'

interface DailyReportCardProps {
  report: DailyReport
}

export default function DailyReportCard({ report }: DailyReportCardProps) {
  return (
    <Link
      to={`/daily/${report.date}`}
      className="block border border-gray-200 rounded-lg p-5 hover:shadow-md hover:border-blue-300 transition-all"
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium text-gray-900">{formatDate(report.date)} 日报</h3>
        <span className="text-xs text-gray-400">{report.date}</span>
      </div>
      <div className="flex gap-4 text-sm text-gray-500">
        <span>📥 抓取 {report.total_fetched} 条</span>
        <span>⭐ 精选 {report.total_selected} 条</span>
      </div>
    </Link>
  )
}
