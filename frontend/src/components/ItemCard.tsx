import { useState, useCallback } from 'react'
import type { NewsItem, SourceProvenance, ContentBlock } from '../api/types'
import ScoreBadge from './ScoreBadge'
import FavoriteButton from './FavoriteButton'
import { sourceLabel, roleLabelZh } from '../utils/source'
import { Link } from 'react-router-dom'
import { backToState, type BackTarget } from '../utils/backTo'

interface ItemCardProps {
  item: NewsItem
  showTopics?: boolean
  /** Where "back" should return to from the item detail / topic pages this
   * card links into — i.e. the page this card is currently rendered on. */
  backTo?: BackTarget
}

/** Resolve the best available content for the active display language. */
function resolveContent(
  contentBlock: ContentBlock | undefined,
  displayLang: string,
  fallback: {
    title: string
    reason: string | null
    summary: string | null
  },
) {
  if (contentBlock?.content?.[displayLang]) {
    const b = contentBlock.content[displayLang]
    return {
      title: b.title || fallback.title,
      reason: b.reason || fallback.reason,
      summary: b.summary || fallback.summary,
    }
  }
  return fallback
}

export default function ItemCard({ item, showTopics = true, backTo }: ItemCardProps) {
  const contentBlock = item.content_block as ContentBlock | undefined
  const originalLang = contentBlock?.original_language ?? 'unknown'
  const defaultLang = contentBlock?.default_language ?? 'zh'

  const [displayLang, setDisplayLang] = useState(defaultLang)

  const toggleLang = useCallback(() => {
    setDisplayLang(prev => (prev === defaultLang ? originalLang : defaultLang))
  }, [defaultLang, originalLang])

  // Fallback values from metadata (preserves backward compat)
  const fallback = {
    title: item.metadata?.title_zh || item.title,
    reason: item.metadata?.reason_zh || item.ai_reason,
    summary: item.ai_summary,
  }

  const content = resolveContent(contentBlock, displayLang, fallback)
  const attribution = item.metadata?.source_attribution
  const provenance = item.metadata?.source_provenance as SourceProvenance | undefined
  // Prefer the role-priority-resolved primary source over the merged item's
  // own feed/subreddit label — see ItemDetailPage.tsx for why these can differ.
  const source = provenance?.primary_source_name || sourceLabel(item)
  const topics = item.topics || []

  // Primary URL: prefer provenance primary_source_url, otherwise item.url
  const primaryUrl = provenance?.primary_source_url || item.url

  // Should we show the translated badge and toggle?
  const showTranslationUI =
    contentBlock &&
    originalLang !== 'zh' &&
    originalLang !== 'unknown' &&
    contentBlock.is_ai_translated

  const showingTranslation = displayLang !== originalLang && displayLang === defaultLang
  const toggleLabel =
    displayLang === defaultLang
      ? originalLang === 'en' ? '显示原文' : '显示原文'
      : '显示译文'

  return (
    <article className="glass news-card rounded-2xl p-5">
      {/* Title row */}
      <div className="flex items-start gap-2 mb-2">
        <ScoreBadge score={item.ai_score} />
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium text-[var(--ink)] leading-snug flex flex-wrap items-center gap-2">
            <Link
              to={`/items/${item.id}`}
              state={backToState(backTo)}
              className="hover:text-[var(--accent)] transition-colors"
            >
              {content.title}
            </Link>
            {/* Translation badge + toggle */}
            {showTranslationUI && (
              <>
                {showingTranslation && (
                  <span className="inline-flex items-center text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                    已翻译
                  </span>
                )}
                <button
                  onClick={toggleLang}
                  className="text-xs font-normal text-[var(--accent)] hover:opacity-80 cursor-pointer"
                >
                  {toggleLabel}
                </button>
              </>
            )}
          </h3>
        </div>
        <FavoriteButton itemId={item.id} initialFavorited={item.is_favorited ?? false} />
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)] mb-3">
        <span>{source}</span>
        {item.published_at && <span>· {item.published_at.slice(0, 10)}</span>}
        {attribution && attribution.count > 1 && (
          <span title={attribution.labels.join(', ')}>
            · {attribution.count} 家报道
          </span>
        )}
      </div>

      {/* Source provenance (primary + other sources) */}
      {provenance && provenance.source_count > 1 && (
        <div className="mt-2 mb-3 pt-2 border-t border-[var(--line)]">
          <div className="text-xs text-[var(--muted)] mb-1 flex flex-wrap items-start gap-x-4">
            {provenance.sources.filter(s => !s.is_primary).length > 0 && (
              <details className="inline-block">
                <summary className="cursor-pointer hover:text-[var(--ink)]">
                  其他来源 ({provenance.sources.filter(s => !s.is_primary).length})
                </summary>
                <div className="mt-1 ml-2 space-y-0.5">
                  {provenance.sources.filter(s => !s.is_primary).map((s, i) => (
                    <div key={i} className="text-xs text-[var(--muted)]">
                      <a
                        href={s.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--accent)] hover:opacity-80"
                      >
                        {s.source_name}
                      </a>
                      <span className="ml-1 text-[var(--muted)]">
                        — {s.title?.length > 40 ? s.title.slice(0, 37) + '...' : s.title}
                      </span>
                      <span className="ml-1 text-[var(--muted)]">({roleLabelZh(s.role)})</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      {content.summary && (
        <p className="text-sm text-[var(--muted)] mt-2 line-clamp-3">{content.summary}</p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 mt-3 text-xs">
        <a
          href={primaryUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--accent)] hover:opacity-80 font-medium"
        >
          在{source}打开原文
        </a>
      </div>

      {/* Topics */}
      {showTopics && topics.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {topics.map(t => (
            <Link
              key={t.slug}
              to={`/topics/${t.slug}`}
              state={backToState(backTo)}
              className="inline-block text-xs px-2 py-0.5 rounded-full bg-black/[.04] text-[var(--muted)] backdrop-blur-sm hover:bg-[var(--accent)]/15 hover:text-[var(--accent)] transition-colors"
            >
              {t.name}
            </Link>
          ))}
        </div>
      )}
    </article>
  )
}
