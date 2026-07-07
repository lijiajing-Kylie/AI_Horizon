import type { NewsItem, SourceProvenance } from '../api/types'
import ScoreBadge from './ScoreBadge'
import { sourceLabel, roleLabelZh } from '../utils/source'
import { Link } from 'react-router-dom'

interface ItemCardProps {
  item: NewsItem
  showTopics?: boolean
}

export default function ItemCard({ item, showTopics = true }: ItemCardProps) {
  const title = item.metadata?.title_zh || item.title
  const reason = item.metadata?.reason_zh || item.ai_reason
  const summary = item.ai_summary
  const source = sourceLabel(item)
  const attribution = item.metadata?.source_attribution
  const provenance = item.metadata?.source_provenance as SourceProvenance | undefined
  const topics = item.topics || []

  // Primary URL: use provenance primary_source_url if available, otherwise item.url
  const primaryUrl = provenance?.primary_source_url || item.url

  return (
    <article className="border border-gray-200 rounded-lg p-5 hover:border-blue-200 transition-colors">
      {/* Title row */}
      <div className="flex items-start gap-2 mb-2">
        <ScoreBadge score={item.ai_score} />
        <h3 className="text-base font-medium text-gray-900 leading-snug flex-1">
          <a href={primaryUrl} target="_blank" rel="noopener noreferrer" className="hover:text-blue-600 transition-colors">
            {title}
          </a>
        </h3>
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
      {reason && (
        <div className="border-l-2 border-blue-400 pl-3 my-2 text-sm text-gray-500 italic">
          {reason}
        </div>
      )}

      {/* Summary */}
      {summary && (
        <p className="text-sm text-gray-600 mt-2 line-clamp-3">{summary}</p>
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
