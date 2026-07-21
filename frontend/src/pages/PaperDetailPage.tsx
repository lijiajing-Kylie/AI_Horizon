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

export default function PaperDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: paper, loading, error } = useApi(() => getPaper(id!), [id])

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
  const [displayLang, setDisplayLang] = useState<'original' | 'zh'>('zh')

  const toggleLang = useCallback(() => {
    setDisplayLang(prev => (prev === 'zh' ? 'original' : 'zh'))
  }, [])

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

      <header className="mb-6">
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
          <div className="text-sm text-[var(--muted)] mb-2">{paper.authors.join(', ')}</div>
        )}

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--muted)] mb-3">
          {paper.published_at && <span>{paper.published_at.slice(0, 10)}</span>}
          <span>· {paperSourceLabel(paper.source)}</span>
          {paper.journal_ref && <span>· {paper.journal_ref}</span>}
          {paper.citation_count != null && <span>· 被引 {paper.citation_count}</span>}
          {paper.upvote_count != null && <span>· {paper.upvote_count}赞</span>}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm mb-3">
          <a
            href={paper.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
          >
            {paperSourceLabel(paper.source)} 页面 <ExternalLink className="w-3.5 h-3.5" strokeWidth={2} />
          </a>
          {paper.pdf_url && (
            <a
              href={paper.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
            >
              PDF <ExternalLink className="w-3.5 h-3.5" strokeWidth={2} />
            </a>
          )}
        </div>

        {paper.categories.length > 0 && (() => {
          const cats = displayLang === 'zh'
            ? [...new Set(paper.categories.map(c => unifiedLabelZh(unifiedCategoryId(c))))]
            : paper.categories
          return (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {cats.map(c => (
                <span
                  key={c}
                  className="inline-block text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]"
                >
                  {c}
                </span>
              ))}
            </div>
          )
        })()}
      </header>

      <section className="mb-6">
        <h2 className="text-sm font-semibold text-[var(--ink)] mb-2">摘要</h2>
        <p className="text-[var(--ink)] leading-relaxed whitespace-pre-line">{displayAbstract}</p>
      </section>

      <BackLink
        fallback={{ path: '/papers', label: '返回论文库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80"
      />
    </div>
  )
}
