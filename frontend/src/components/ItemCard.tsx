import { useState, useCallback } from 'react'
import type { NewsItem, SourceProvenance, ContentBlock } from '../api/types'
import ScoreBadge from './ScoreBadge'
import { sourceLabel, roleLabelZh } from '../utils/source'
import { Link } from 'react-router-dom'

interface ItemCardProps {
  item: NewsItem
  showTopics?: boolean
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

export default function ItemCard({ item, showTopics = true }: ItemCardProps) {
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
  const source = sourceLabel(item)
  const attribution = item.metadata?.source_attribution
  const provenance = item.metadata?.source_provenance as SourceProvenance | undefined
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
    <article className="border border-gray-200 rounded-lg p-5 hover:border-blue-200 transition-colors">
      {/* Title row */}
      <div className="flex items-start gap-2 mb-2">
        <ScoreBadge score={item.ai_score} />
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium text-gray-900 leading-snug">
            <a
              href={primaryUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-blue-600 transition-colors"
            >
              {content.title}
            </a>
          </h3>
          {/* Translation badge + toggle */}
          {showTranslationUI && (
            <div className="flex items-center gap-2 mt-1">
              {showingTranslation && (
                <span className="inline-flex items-center text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                  已翻译
                </span>
              )}
              <button
                onClick={toggleLang}
                className="text-xs text-blue-500 hover:text-blue-700 cursor-pointer"
              >
                {toggleLabel}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-400 mb-3">
        <span>{source}</span>
        {item.published_at && <span>· {item.published_at.slice(0, 10)}</span>}
        {attribution && attribution.count > 1 && (
          <span className="text-blue-500" title={attribution.labels.join(', ')}>
            · 📰 {attribution.count} 家报道
          </span>
        )}
      </div>

      {/* Source provenance (primary + other sources) */}
      {provenance && provenance.source_count > 1 && (
        <div className="mt-2 mb-3 pt-2 border-t border-gray-100">
          <div className="text-xs text-gray-500 mb-1">
            <span className="font-medium text-gray-600">主要来源: </span>
            <a
              href={provenance.primary_source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:text-blue-700"
            >
              {provenance.primary_source_name}
            </a>
            <span className="ml-1 text-gray-400">
              ({roleLabelZh(provenance.primary_source_type)})
            </span>
          </div>
          <div className="text-xs text-gray-400">
            共 {provenance.source_count} 个来源报道
          </div>
          {provenance.sources.filter(s => !s.is_primary).length > 0 && (
            <details className="mt-1">
              <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                其他来源 ({provenance.sources.filter(s => !s.is_primary).length})
              </summary>
              <div className="mt-1 ml-2 space-y-0.5">
                {provenance.sources.filter(s => !s.is_primary).map((s, i) => (
                  <div key={i} className="text-xs text-gray-500">
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-500 hover:text-blue-700"
                    >
                      {s.source_name}
                    </a>
                    <span className="ml-1 text-gray-400">
                      — {s.title?.length > 40 ? s.title.slice(0, 37) + '...' : s.title}
                    </span>
                    <span className="ml-1 text-gray-300">({roleLabelZh(s.role)})</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* Reason */}
      {content.reason && (
        <div className="border-l-2 border-blue-400 pl-3 my-2 text-sm text-gray-500 italic">
          {content.reason}
        </div>
      )}

      {/* Summary */}
      {content.summary && (
        <p className="text-sm text-gray-600 mt-2 line-clamp-3">{content.summary}</p>
      )}

      {/* Topics */}
      {showTopics && topics.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {topics.map(t => (
            <Link
              key={t.slug}
              to={`/topics/${t.slug}`}
              className="inline-block text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
            >
              {t.name}
            </Link>
          ))}
        </div>
      )}
    </article>
  )
}
