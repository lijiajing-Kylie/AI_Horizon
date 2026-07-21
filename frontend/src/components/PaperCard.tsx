import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import type { Paper } from '../api/types'
import { backToState, type BackTarget } from '../utils/backTo'
import { paperSourceLabel } from '../utils/source'
import { unifiedCategoryId, unifiedLabelZh } from '../utils/paperCategoryMap'
import FavoriteButton from './FavoriteButton'

interface PaperCardProps {
  paper: Paper
  /** Where "back" should return to from the paper detail page this card links into. */
  backTo?: BackTarget
}

export default function PaperCard({ paper, backTo }: PaperCardProps) {
  const authors = paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' 等' : '')

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
    <article className="glass news-card rounded-2xl p-5">
      <div className="flex items-start gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium text-[var(--ink)] leading-snug flex flex-wrap items-center gap-2">
            <Link
              to={`/papers/${paper.id}`}
              state={backToState(backTo)}
              className="hover:text-[var(--accent)] transition-colors"
            >
              {displayTitle}
            </Link>
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
          </h3>
        </div>
        <FavoriteButton itemId={paper.id} initialFavorited={paper.is_favorited ?? false} type="paper" />
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)] mt-1 mb-3">
        {authors && <span>{authors}</span>}
        {paper.published_at && <span>· {paper.published_at.slice(0, 10)}</span>}
        <span>· {paperSourceLabel(paper.source)}</span>
        {paper.journal_ref && <span>· {paper.journal_ref}</span>}
        {paper.citation_count != null && (
          <span>· 被引 {paper.citation_count}</span>
        )}
        {paper.upvote_count != null && (
          <span>· {paper.upvote_count}赞</span>
        )}
      </div>

      <p className="text-sm text-[var(--muted)] line-clamp-3">{displayAbstract}</p>

      {paper.categories.length > 0 && (() => {
        const cats = displayLang === 'zh'
          ? [...new Set(paper.categories.map(c => unifiedLabelZh(unifiedCategoryId(c))))]
          : paper.categories
        return (
          <div className="flex flex-wrap gap-1.5 mt-3">
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

      <div className="flex items-center gap-3 mt-3 text-xs">
        <a
          href={paper.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--accent)] hover:opacity-80 font-medium"
        >
          在 {paperSourceLabel(paper.source)} 查看原文
        </a>
        {paper.pdf_url && (
          <a
            href={paper.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:opacity-80 font-medium"
          >
            查看PDF文件
          </a>
        )}
      </div>
    </article>
  )
}
