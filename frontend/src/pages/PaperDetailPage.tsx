import { useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getPaper } from '../api/client'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import BackLink from '../components/BackLink'
import { paperSourceLabel } from '../utils/source'
import { unifiedCategoryId, unifiedLabelZh } from '../utils/paperCategoryMap'
import FavoriteButton from '../components/FavoriteButton'
import CardHeading from '../components/CardHeading'

export default function PaperDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: paper, loading, error } = useApi(() => getPaper(id!), [id])

  // Hooks must be before early returns
  const [displayLang, setDisplayLang] = useState<'original' | 'zh'>('zh')

  const toggleLang = useCallback(() => {
    setDisplayLang(prev => (prev === 'zh' ? 'original' : 'zh'))
  }, [])

  if (loading && !paper) return <LoadingSkeleton />
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!paper) return <EmptyState title="论文不存在" />

  // ---- translation toggle ------------------------------------------------
  const hasTranslation = !!(
    paper.original_language &&
    paper.original_language !== 'zh' &&
    paper.original_language !== 'unknown' &&
    paper.title_zh
  )

  const displayTitle =
    displayLang === 'zh' && paper.title_zh ? paper.title_zh : paper.title
  const displayAbstract =
    displayLang === 'zh' && paper.abstract_zh ? paper.abstract_zh : paper.abstract

  return (
    <div className="max-w-[1180px] mx-auto">
      <BackLink
        fallback={{ path: '/papers', label: '返回论文库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80 mb-4"
      />

      <header className="glass news-card rounded-[28px] p-7 mb-6">
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-semibold text-[var(--ink)] leading-snug mb-3 tracking-wide flex flex-wrap items-center gap-2">
              {displayTitle}
              {hasTranslation && (
                <>
                  {displayLang === 'zh' && (
                    <span className="inline-flex items-center text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                      已翻译
                    </span>
                  )}
                  <button
                    onClick={toggleLang}
                    className="text-xs font-normal text-[var(--accent)] hover:opacity-80 cursor-pointer"
                  >
                    {displayLang === 'zh' ? '显示原文' : '显示译文'}
                  </button>
                </>
              )}
            </h1>
          </div>
          <FavoriteButton itemId={paper.id} initialFavorited={paper.is_favorited ?? false} type="paper" size="md" />
        </div>

        {paper.authors.length > 0 && (
          <div className="text-sm text-[var(--muted)] mb-2 leading-relaxed">
            {paper.authors.slice(0, 3).join(', ')}{paper.authors.length > 3 && ` 等`}
          </div>
        )}

        <div className="text-sm text-[var(--muted)] mb-2">
          {paper.published_at && <span>{paper.published_at.slice(0, 10)}</span>}
          {paper.citation_count != null && <span> · 被引 {paper.citation_count}</span>}
          {paper.upvote_count != null && <span> · {paper.upvote_count} 赞</span>}
        </div>

        {paper.journal_ref && (
          <div className="text-xs text-[var(--muted)]/60 mb-3">{paper.journal_ref}</div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
            >
              {paperSourceLabel(paper.source)} 页面 <ExternalLink className="w-3.5 h-3.5 inline" strokeWidth={2} />
            </a>
            {paper.pdf_url && (
              <a
                href={paper.pdf_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
              >
                PDF <ExternalLink className="w-3.5 h-3.5 inline" strokeWidth={2} />
              </a>
            )}
          </div>
          {paper.categories.length > 0 && (() => {
            const cats = displayLang === 'zh'
              ? [...new Set(paper.categories.map(c => unifiedLabelZh(unifiedCategoryId(c))))]
              : paper.categories
            return (
              <div className="flex flex-wrap gap-1.5">
                {cats.slice(0, 3).map(c => (
                  <span
                    key={c}
                    className="text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]"
                  >
                    {c}
                  </span>
                ))}
              </div>
            )
          })()}
        </div>

        {/* Topic tags */}
        {paper.topics && paper.topics.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {paper.topics.map((t: { id: number; name: string; slug: string; group_name: string }) => (
              <span
                key={t.slug}
                className="text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)]"
              >
                {t.name}
              </span>
            ))}
          </div>
        )}
      </header>

      <section className="glass rounded-[22px] p-6 mb-6">
        <CardHeading>摘要</CardHeading>
        <p className="text-[17px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">{displayAbstract}</p>
      </section>

      <hr className="my-8 border-[var(--line)]" />
      <BackLink
        fallback={{ path: '/papers', label: '返回论文库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80"
      />
    </div>
  )
}
