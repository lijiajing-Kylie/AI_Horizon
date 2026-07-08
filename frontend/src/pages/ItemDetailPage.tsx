import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { getItem } from '../api/client'
import ScoreBadge from '../components/ScoreBadge'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import BackLink from '../components/BackLink'
import { sourceLabel, roleLabelZh } from '../utils/source'
import { backToState } from '../utils/backTo'
import type { ArticleImage, ContentBlock, SourceProvenance, EnrichmentSource } from '../api/types'

// ── helpers ───────────────────────────────────────────────────────────────

// A broken image (dead link, blocked hotlink, etc.) just disappears rather
// than showing the browser's broken-image icon.
function ImageThumb({ image }: { image: ArticleImage }) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  return (
    <figure className="min-w-0">
      <img
        src={image.url}
        alt={image.alt || image.caption || ''}
        loading="lazy"
        className="w-full h-28 object-cover rounded-md border border-gray-200"
        onError={() => setFailed(true)}
      />
      {image.caption && (
        <figcaption className="mt-1 text-xs text-gray-400 truncate" title={image.caption}>
          {image.caption}
        </figcaption>
      )}
    </figure>
  )
}

function resolveItemContent(
  contentBlock: ContentBlock | undefined,
  displayLang: string,
  item: { title: string; ai_reason: string | null; ai_summary: string | null },
) {
  if (contentBlock?.content?.[displayLang]) {
    const b = contentBlock.content[displayLang]
    return {
      title: b.title || item.title,
      reason: b.reason || item.ai_reason,
      summary: b.summary || item.ai_summary,
      communityDiscussion: b.community_discussion || '',
    }
  }
  return {
    title: item.title,
    reason: item.ai_reason,
    summary: item.ai_summary,
    communityDiscussion: '',
  }
}

// clean_content is the display-ready article body; fall back to the AI
// summary, then the untouched raw_content, if it's empty.
function resolveArticleBody(
  item: { clean_content: string | null; raw_content: string | null },
  summary: string | null,
): string {
  if (item.clean_content && item.clean_content.trim()) return item.clean_content
  if (summary && summary.trim()) return summary
  if (item.raw_content && item.raw_content.trim()) return item.raw_content
  return ''
}

// display_html (structured, sanitized article HTML) is preferred when
// present; everything else falls back to the plain-text chain above.
function resolveArticleHtml(item: { display_html: string | null }): string {
  if (item.display_html && item.display_html.trim()) return item.display_html
  return ''
}

// Renders sanitized article HTML via dangerouslySetInnerHTML. Images inside
// raw HTML don't get React's onError handling for free, so a broken image
// (dead link, blocked hotlink) is hidden via a plain DOM listener instead —
// mirrors the behavior of the plain-text-fallback ImageThumb component.
function ArticleHtml({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = ref.current
    if (!container) return
    const imgs = Array.from(container.querySelectorAll('img'))
    const hide = (e: Event) => {
      (e.currentTarget as HTMLImageElement).style.display = 'none'
    }
    imgs.forEach(img => img.addEventListener('error', hide))
    return () => imgs.forEach(img => img.removeEventListener('error', hide))
  }, [html])

  return (
    <div
      ref={ref}
      className="article-html text-sm text-gray-800 leading-[1.7]"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

// ── component ─────────────────────────────────────────────────────────────

export default function ItemDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: item, loading, error } = useApi(() => getItem(id!), [id])

  const contentBlock = item?.content_block as ContentBlock | undefined
  const originalLang = contentBlock?.original_language ?? 'unknown'
  const defaultLang = contentBlock?.default_language ?? 'zh'
  const [displayLang, setDisplayLang] = useState(defaultLang)

  const toggleLang = useCallback(() => {
    setDisplayLang(prev => (prev === defaultLang ? originalLang : defaultLang))
  }, [defaultLang, originalLang])

  if (loading && !item) return <LoadingSkeleton />
  if (error) return <EmptyState icon="⚠️" title="加载失败" description={error} />
  if (!item) return <EmptyState icon="📭" title="内容不存在" />

  const content = resolveItemContent(contentBlock, displayLang, item)
  const source = sourceLabel(item)
  const provenance = item.metadata?.source_provenance as SourceProvenance | undefined
  const enrichmentSources = (contentBlock?.enrichment_sources || []) as EnrichmentSource[]
  const discussionUrl = contentBlock?.discussion_url as string | undefined
  const primaryUrl = provenance?.primary_source_url || item.url
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
  const topics = item.topics || []
  // Topic tags always send you back to *this* item detail page — never
  // chained to wherever this page itself was reached from.
  const topicBackTo = { path: `/items/${id}`, label: '← 返回新闻详情' }
  const articleHtml = resolveArticleHtml(item)
  const articleBody = resolveArticleBody(item, content.summary)
  // Extracted article text (trafilatura) separates paragraphs with a single
  // newline rather than a blank line, so split on any run of newlines.
  const paragraphs = articleBody.split(/\n+/).map(p => p.trim()).filter(Boolean)

  return (
    <div className="max-w-3xl mx-auto">
      {/* Back link */}
      <BackLink
        fallback={{ path: '/', label: '← 返回首页' }}
        className="text-sm text-blue-600 hover:text-blue-700 mb-4 inline-block"
      />

      {/* Header */}
      <header className="mb-6">
        <div className="flex items-start gap-3 mb-3">
          <ScoreBadge score={item.ai_score} />
          <h1 className="text-xl font-bold text-gray-900 leading-snug">
            {content.title}
          </h1>
        </div>

        {/* Cover image */}
        {item.cover_image && (
          <img
            src={item.cover_image}
            alt={content.title}
            className="w-full max-h-[420px] object-cover rounded-lg mb-3"
            onError={e => { e.currentTarget.style.display = 'none' }}
          />
        )}

        {/* Translation toggle */}
        {showTranslationUI && (
          <div className="flex items-center gap-2 mb-3">
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

        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-400 mb-3">
          <span>{source}</span>
          {item.published_at && <span>· {item.published_at.slice(0, 10)}</span>}
        </div>

        {/* 查看原文 button — kept separate from the article body */}
        <a
          href={primaryUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:border-gray-400 transition-colors mb-3"
        >
          查看原文 ↗
        </a>

        {/* Tags */}
        {item.ai_tags && item.ai_tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {item.ai_tags.map((tag: string, i: number) => (
              <span
                key={i}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Topics */}
        {topics.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-4">
            {topics.map(t => (
              <Link
                key={t.slug}
                to={`/topics/${t.slug}`}
                state={backToState(topicBackTo)}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
              >
                {t.name}
              </Link>
            ))}
          </div>
        )}
      </header>

      {/* 1. 推荐理由 */}
      {content.reason && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            推荐理由
          </h2>
          <div className="border-l-2 border-blue-400 pl-4 text-gray-600 italic bg-blue-50/50 py-3 rounded-r-lg">
            {content.reason}
          </div>
        </section>
      )}

      {/* 2. 完整摘要 */}
      {content.summary && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            完整摘要
          </h2>
          <div className="text-gray-800 leading-relaxed whitespace-pre-line">
            {content.summary}
          </div>
        </section>
      )}

      {/* 3. 正文 */}
      {/* TODO: display_html is always shown in its original extraction
          language — there is no "中文正文 / 原文" toggle or on-demand
          translation endpoint yet (only title/summary/reason/community
          discussion are bilingual today, via content_block). Deferred to a
          later phase; see the design doc discussion. */}
      {articleHtml ? (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            正文
          </h2>
          <div className="bg-white border border-gray-200 rounded-lg p-5">
            <div className="mx-auto max-w-[760px]">
              <ArticleHtml html={articleHtml} />
            </div>
          </div>
        </section>
      ) : paragraphs.length > 0 ? (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            正文
          </h2>
          <div className="bg-white border border-gray-200 rounded-lg p-5">
            <div className="mx-auto max-w-[760px]">
              {paragraphs.map((p, i) => (
                <p key={i} className="text-sm text-gray-800 leading-[1.7] mb-4 last:mb-0">
                  {p}
                </p>
              ))}

              {/* Inline article images — shown after the text so they don't break up paragraph flow */}
              {item.images.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-100 grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {item.images.map((img, i) => (
                    <ImageThumb key={i} image={img} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      {/* 4. 社区讨论 */}
      {content.communityDiscussion && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            社区讨论
          </h2>
          <div className="text-gray-700 leading-relaxed whitespace-pre-line bg-gray-50 p-4 rounded-lg">
            {content.communityDiscussion}
          </div>
          {discussionUrl && (
            <a
              href={discussionUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-2 text-sm text-blue-500 hover:text-blue-700"
            >
              💬 查看原讨论 →
            </a>
          )}
        </section>
      )}

      {/* 5. 来源 */}
      {provenance && provenance.source_count > 1 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            来源
          </h2>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="text-sm mb-3">
              <span className="font-medium text-gray-700">主要来源: </span>
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
            <div className="text-xs text-gray-400 mb-2">
              共 {provenance.source_count} 个来源报道
            </div>
            <div className="space-y-1.5">
              {provenance.sources.filter(s => !s.is_primary).map((s, i) => (
                <div key={i} className="text-sm text-gray-600">
                  <a
                    href={s.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 hover:text-blue-700"
                  >
                    {s.source_name}
                  </a>
                  <span className="ml-2 text-gray-400 text-xs">{roleLabelZh(s.role)}</span>
                  {s.title && (
                    <span className="ml-2 text-gray-500 text-xs">
                      — {s.title.length > 80 ? s.title.slice(0, 77) + '...' : s.title}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Enrichment Sources */}
      {enrichmentSources.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            参考来源
          </h2>
          <div className="space-y-1">
            {enrichmentSources.map((src, i) => (
              <div key={i} className="text-sm">
                <a
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:text-blue-700"
                >
                  📄 {src.title || src.url}
                </a>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Divider */}
      <hr className="my-8 border-gray-200" />

      {/* Back link (bottom) */}
      <BackLink
        fallback={{ path: '/', label: '← 返回首页' }}
        className="text-sm text-blue-600 hover:text-blue-700"
      />
    </div>
  )
}
