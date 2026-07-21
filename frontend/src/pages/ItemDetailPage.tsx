import { useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getItem } from '../api/client'
import ScoreBadge from '../components/ScoreBadge'
import ScoreBreakdown from '../components/ScoreBreakdown'
import FavoriteButton from '../components/FavoriteButton'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import BackLink from '../components/BackLink'
import { sourceLabel, roleLabelZh } from '../utils/source'
import { backToState } from '../utils/backTo'
import ArticleHtml from '../components/ArticleHtml'
import ScrapeDiagnosticsPanel from '../components/ScrapeDiagnosticsPanel'
import type { ArticleImage, ContentBlock, SourceProvenance, EnrichmentSource, ScoreBreakdown as ScoreBreakdownData } from '../api/types'

// ── helpers (unchanged — pure presentation rewrite below, logic untouched) ──

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
        className="w-full h-28 object-cover rounded-lg"
        onError={() => setFailed(true)}
      />
      {image.caption && (
        <figcaption className="mt-1 text-xs text-[var(--muted)] truncate" title={image.caption}>
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

// clean_content is the display-ready article body (comments section already
// stripped server-side). Deliberately does NOT fall back to raw_content —
// that field is the untouched scrape, which for comment-fetching sources
// (HN/Reddit/Twitter) still contains the "--- Top Comments ---" section —
// nor to the AI summary, which belongs in its own "完整摘要" section and
// must never be presented as if it were the article body.
function resolveArticleBody(item: { clean_content: string | null }): string {
  if (item.clean_content && item.clean_content.trim()) return item.clean_content
  return ''
}

// display_html (structured, sanitized article HTML) is preferred when
// present; everything else falls back to the plain-text chain above.
// display_html_zh (AI-translated body) is shown when displayLang is 'zh'
// and a translation exists, falling back to the original-language HTML —
// in which case translationFailed flags that the fallback happened because
// translation didn't produce a usable result, not because the user asked
// to see the original (toggling displayLang away from 'zh' is a normal
// user choice, not a failure).
function resolveArticleHtml(
  item: { display_html: string | null; display_html_zh: string | null },
  displayLang: string,
): { html: string; translationFailed: boolean } {
  if (displayLang === 'zh' && item.display_html_zh && item.display_html_zh.trim()) {
    return { html: item.display_html_zh, translationFailed: false }
  }
  if (item.display_html && item.display_html.trim()) {
    return { html: item.display_html, translationFailed: displayLang === 'zh' }
  }
  return { html: '', translationFailed: false }
}

// A section heading inside a glass card — small tracked-out eyebrow label,
// matching the home/daily pages' typographic system.
function CardHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-3">{children}</h2>
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
  if (error) return <EmptyState title="加载失败" description={error} />
  if (!item) return <EmptyState title="内容不存在" />

  const content = resolveItemContent(contentBlock, displayLang, item)
  const provenance = item.metadata?.source_provenance as SourceProvenance | undefined
  // Prefer the role-priority-resolved primary source over the merged item's
  // own feed/subreddit label — when duplicates from several sources get
  // merged, the surviving DB row isn't necessarily the most authoritative
  // one (e.g. an aggregator RSS entry can win the content-richness merge
  // while an official page wins provenance's authority ranking), so this
  // avoids showing a source next to the date that "查看原文" doesn't link to.
  const source = provenance?.primary_source_name || sourceLabel(item)
  const scoreBreakdown = item.metadata?.score_breakdown as ScoreBreakdownData | undefined
  const enrichmentSources = (contentBlock?.enrichment_sources || []) as EnrichmentSource[]
  const discussionUrl = contentBlock?.discussion_url as string | undefined
  const primaryUrl = provenance?.primary_source_url || item.url
  const showTranslationUI =
    contentBlock &&
    originalLang !== 'zh' &&
    originalLang !== 'unknown' &&
    contentBlock.is_ai_translated
  const showingTranslation = displayLang !== originalLang && displayLang === defaultLang
  const toggleLabel = displayLang === defaultLang ? '显示原文' : '显示译文'
  const topics = item.topics || []
  // Topic tags always send you back to *this* item detail page — never
  // chained to wherever this page itself was reached from.
  const topicBackTo = { path: `/items/${id}`, label: '返回新闻详情' }
  const { html: articleHtml, translationFailed } = resolveArticleHtml(item, displayLang)
  const articleBody = resolveArticleBody(item)
  // Extracted article text (trafilatura) separates paragraphs with a single
  // newline rather than a blank line, so split on any run of newlines.
  const paragraphs = articleBody.split(/\n+/).map(p => p.trim()).filter(Boolean)

  const otherSources = provenance?.sources.filter(s => !s.is_primary) || []

  return (
    <div className="max-w-[1180px] mx-auto">
      {/* Back link */}
      <BackLink
        fallback={{ path: '/', label: '返回首页' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80 mb-4"
      />

      {/* ===== Article info card ===== */}
      <header className="glass news-card rounded-[28px] p-7 mb-6">
        <div className="flex items-start gap-3 mb-3">
          <ScoreBadge score={item.ai_score} />
          <h1 className="flex-1 text-xl font-semibold text-[var(--ink)] leading-snug">
            {content.title}
          </h1>
          <FavoriteButton itemId={item.id} initialFavorited={item.is_favorited ?? false} size="md" />
        </div>

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
              className="text-xs text-[var(--accent)] hover:opacity-80 cursor-pointer"
            >
              {toggleLabel}
            </button>
          </div>
        )}

        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--muted)] mb-3">
          <span>{source}</span>
          {item.published_at && <span>· {item.published_at.slice(0, 10)}</span>}
          <a
            href={primaryUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-[var(--ink)] hover:text-[var(--accent)] transition-colors"
          >
            查看原文 <ExternalLink className="w-3.5 h-3.5" strokeWidth={2} />
          </a>
        </div>

        {/* Tags */}
        {item.ai_tags && item.ai_tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {item.ai_tags.map((tag: string, i: number) => (
              <span
                key={i}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Topics */}
        {topics.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {topics.map(t => (
              <Link
                key={t.slug}
                to={`/topics/${t.slug}`}
                state={backToState(topicBackTo)}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
              >
                {t.name}
              </Link>
            ))}
          </div>
        )}
      </header>

      {/* ===== Two-column body ===== */}
      <div className="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-6 items-start">
        {/* ---- Left: long-form reading ---- */}
        <div className="min-w-0 space-y-6">
          {/* 完整摘要 */}
          {content.summary && (
            <section className="glass rounded-[22px] p-6">
              <CardHeading>完整摘要</CardHeading>
              <div className="text-[17px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">
                {content.summary}
              </div>
            </section>
          )}

          {/* 正文 */}
          {articleHtml ? (
            <section className="glass rounded-[22px] p-6">
              <CardHeading>正文</CardHeading>
              {translationFailed && (
                <p className="text-xs text-amber-600 mb-3">正文翻译失败，以下为原文</p>
              )}
              <ArticleHtml html={articleHtml} className="article-html text-[17px] leading-[1.85] text-[var(--ink)]" />
            </section>
          ) : paragraphs.length > 0 ? (
            <section className="glass rounded-[22px] p-6">
              <CardHeading>正文</CardHeading>
              {paragraphs.map((p, i) => (
                <p key={i} className="text-[17px] leading-[1.85] text-[var(--ink)] mb-5 last:mb-0">
                  {p}
                </p>
              ))}

              {/* Inline article images — shown after the text so they don't break up paragraph flow */}
              {item.images.length > 0 && (
                <div className="mt-5 pt-5 border-t border-[var(--line)] grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {item.images.map((img, i) => (
                    <ImageThumb key={i} image={img} />
                  ))}
                </div>
              )}
            </section>
          ) : (
            <section className="glass rounded-[22px] p-6">
              <CardHeading>正文</CardHeading>
              <p className="text-sm text-[var(--muted)]">
                因原网站限制、抓取失败或正文不可解析，当前无法显示正文。请点击
                <a
                  href={primaryUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--accent)] hover:opacity-80"
                >
                  查看原文
                </a>
                。
              </p>
            </section>
          )}

          {/* 社区讨论 */}
          {content.communityDiscussion && (
            <section className="glass rounded-[22px] p-6">
              <CardHeading>社区讨论</CardHeading>
              <div className="text-[15px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">
                {content.communityDiscussion}
              </div>
              {discussionUrl && (
                <a
                  href={discussionUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block mt-3 text-sm text-[var(--accent)] hover:opacity-80"
                >
                  查看原讨论
                </a>
              )}
            </section>
          )}
        </div>

        {/* ---- Right: reasoning / scoring / sources, sticky ---- */}
        <aside className="lg:sticky lg:top-[86px] lg:self-start space-y-6">
          {/* 推荐理由 */}
          {content.reason && (
            <section className="glass rounded-[22px] p-5">
              <CardHeading>推荐理由</CardHeading>
              <p className="text-sm leading-relaxed text-[var(--ink)]">{content.reason}</p>
            </section>
          )}

          {/* 评分明细 */}
          {scoreBreakdown && <ScoreBreakdown breakdown={scoreBreakdown} />}

          {/* 来源信息：相关来源 + 参考来源 */}
          {((provenance && provenance.source_count > 1) || enrichmentSources.length > 0) && (
            <section className="glass rounded-[22px] p-5">
              <CardHeading>来源信息</CardHeading>

              {provenance && provenance.source_count > 1 && (
                <div className="mb-4">
                  <div className="flex flex-wrap gap-2">
                    {otherSources.map((s, i) => (
                      <a
                        key={i}
                        href={s.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={s.title || undefined}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--line)] text-sm hover:border-[var(--accent)] transition-colors"
                      >
                        <span className="text-[var(--ink)]">{s.source_name}</span>
                        <span className="text-xs text-[var(--muted)]">{roleLabelZh(s.role)}</span>
                      </a>
                    ))}
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-2">共 {provenance.source_count} 个来源报道</p>
                </div>
              )}

              {enrichmentSources.length > 0 && (
                <div className={provenance && provenance.source_count > 1 ? 'pt-4 border-t border-[var(--line)]' : ''}>
                  <p className="text-xs text-[var(--muted)] mb-2">参考来源</p>
                  <div className="space-y-1.5">
                    {enrichmentSources.map((src, i) => (
                      <a
                        key={i}
                        href={src.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-sm text-[var(--accent)] hover:opacity-80 truncate"
                      >
                        {src.title || src.url}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}
        </aside>
      </div>

      {/* Scrape diagnostics — dev-only, never rendered in a production build */}
      {import.meta.env.DEV && item.debug && (
        <ScrapeDiagnosticsPanel debug={item.debug} />
      )}

      {/* Divider */}
      <hr className="my-8 border-[var(--line)]" />

      {/* Back link (bottom) */}
      <BackLink
        fallback={{ path: '/', label: '返回首页' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80"
      />
    </div>
  )
}
