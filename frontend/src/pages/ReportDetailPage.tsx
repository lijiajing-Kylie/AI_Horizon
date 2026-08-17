import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getReport } from '../api/client'
import ArticleHtml from '../components/ArticleHtml'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import BackLink from '../components/BackLink'
import FavoriteButton from '../components/FavoriteButton'
import CardHeading from '../components/CardHeading'

export default function ReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: report, loading, error } = useApi(() => getReport(id!), [id])

  // Hooks must be before early returns
  const [note, setNote] = useState<string | null | undefined>(report?.note)
  useEffect(() => setNote(report?.note ?? null), [report?.note])

  if (loading && !report) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!report) return <EmptyState title="报告不存在" />

  // aliyun 报告没有网页全文，正文都在本地 PDF 里 —— 全文区显示引导链接而非占位文本。
  const localPdf = report.pdf_urls.find(p => p.local_path)
  const showPdfFulltextHint =
    report.source === 'aliyunreports' && report.has_local_pdf && !!localPdf

  return (
    <div className="max-w-[1180px] mx-auto">
      <BackLink
        fallback={{ path: '/reports', label: '返回报告库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80 mb-4"
      />

      {/* ── Title card ── */}
      <header className="glass news-card rounded-[28px] p-7 mb-6">
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-semibold leading-snug mb-3 tracking-wide">
              <a
                href={report.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--ink)] hover:text-[var(--accent)] transition-colors"
              >
                {report.title}
              </a>
            </h1>
          </div>
          <FavoriteButton itemId={report.id} initialFavorited={report.is_favorited ?? false} type="report" size="md" note={note} onNoteChange={setNote} />
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-[var(--muted)] mb-3">
          {(report.institutions ?? [report.institution]).map(inst => (
            <span key={inst} className="text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]">{inst}</span>
          ))}
          {report.published_at && <span>· {report.published_at.slice(0, 10)}</span>}
          {report.view_count != null && <span>· {report.view_count}次浏览</span>}
          {report.download_count != null && <span>· {report.download_count}次下载</span>}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm mb-3">
          {report.url && (
            <a
              href={report.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
            >
              阅读原文 <ExternalLink className="w-3.5 h-3.5 inline" strokeWidth={2} />
            </a>
          )}
          {report.pdf_urls.map(pdf => (
            <a
              key={pdf.url}
              href={pdf.local_path ?? pdf.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
            >
              PDF <ExternalLink className="w-3.5 h-3.5 inline" strokeWidth={2} />
            </a>
          ))}
        </div>

        {report.categories.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {report.categories.map(c => (
              <span
                key={c}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]"
              >
                {c}
              </span>
            ))}
          </div>
        )}

        {report.keywords && report.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {report.keywords.slice(0, 8).map(k => (
              <span
                key={k}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)]"
              >
                {k}
              </span>
            ))}
          </div>
        )}

        {/* Favorite note */}
        {note && (
          <div className="mt-4 rounded-lg bg-black/[.03] px-4 py-3">
            <div className="text-xs font-medium text-[var(--muted)] mb-1">我的笔记</div>
            <p className="text-sm text-[var(--ink)] leading-relaxed whitespace-pre-line">{note}</p>
          </div>
        )}
      </header>

      {/* ── Summary ── */}
      {report.summary && (
        <section className="glass rounded-[22px] p-6 mb-6">
          <CardHeading>摘要</CardHeading>
          <p className="text-[17px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">
            {report.summary}
          </p>
        </section>
      )}

      {/* ── Full text ── */}
      {((report.content_text && report.content_text.length > 0) || report.display_html) ? (
        <section className="glass rounded-[22px] p-6">
          <CardHeading>全文</CardHeading>
          {showPdfFulltextHint && localPdf ? (
            <p className="text-[17px] leading-[1.85] text-[var(--ink)]">
              请点击
              <a
                href={localPdf.local_path ?? localPdf.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mx-1 font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
              >
                PDF文件
              </a>
              查看全文
            </p>
          ) : report.display_html ? (
            <ArticleHtml
              html={report.display_html}
              className="article-html text-[17px] leading-[1.85] text-[var(--ink)]"
            />
          ) : (
            <div className="text-[17px] leading-[1.85] text-[var(--ink)] whitespace-pre-line space-y-4">
              {report.content_text.split('\n').map((para, i) =>
                para.trim() ? <p key={i}>{para}</p> : null
              )}
            </div>
          )}
        </section>
      ) : null}

      <hr className="my-8 border-[var(--line)]" />

      <BackLink
        fallback={{ path: '/reports', label: '返回报告库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80"
      />
    </div>
  )
}
