import { Link } from 'react-router-dom'
import type { Report } from '../api/types'
import { backToState, type BackTarget } from '../utils/backTo'
import FavoriteButton from './FavoriteButton'

interface ReportCardProps {
  report: Report
  /** Where "back" should return to from the report detail page this card links into. */
  backTo?: BackTarget
}

export default function ReportCard({ report, backTo }: ReportCardProps) {
  return (
    <article className="glass news-card rounded-2xl p-5">
      <div className="flex items-start gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium text-[var(--ink)] leading-snug">
            <Link
              to={`/reports/${report.id}`}
              state={backToState(backTo)}
              className="hover:text-[var(--accent)] transition-colors"
            >
              {report.title}
            </Link>
          </h3>
        </div>
        <FavoriteButton itemId={report.id} initialFavorited={report.is_favorited ?? false} type="report" />
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)] mt-1 mb-3">
        {(report.institutions ?? [report.institution]).map(inst => (
          <span key={inst} className="text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]">{inst}</span>
        ))}
        {report.published_at && <span>· {report.published_at.slice(0, 10)}</span>}
        {report.view_count != null && <span>· {report.view_count}次浏览</span>}
        {report.download_count != null && <span>· {report.download_count}次下载</span>}
      </div>

      {report.summary && (
        <p className="text-sm text-[var(--muted)] line-clamp-3">{report.summary}</p>
      )}

      <div className="flex items-center gap-3 mt-3 text-xs">
        <a
          href={report.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--accent)] hover:opacity-80 font-medium"
        >
          查看原文
        </a>
        {report.pdf_urls.length > 0 && (
          <a
            href={report.pdf_urls[0].local_path ?? report.pdf_urls[0].url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[var(--accent)] hover:opacity-80 font-medium"
          >
            查看PDF文件
            {report.has_local_pdf && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)]">
                本地
              </span>
            )}
          </a>
        )}
      </div>
    </article>
  )
}
