import { useState, useCallback, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getPaper } from '../api/client'
import type { PaperLayeredSummary as PaperLayeredSummaryType } from '../api/types'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import BackLink from '../components/BackLink'
import { paperSourceLabel } from '../utils/source'
import { unifiedCategoryId, unifiedLabelZh } from '../utils/paperCategoryMap'
import FavoriteButton from '../components/FavoriteButton'
import CardHeading from '../components/CardHeading'
import PaperLayeredSummary from '../components/PaperLayeredSummary'

/** 旧版单层解读（背景/问题/贡献/方法/证据/意义/局限）——兼容 pre-monolingual 历史数据。 */
const LEGACY_SUMMARY_FIELDS: { key: string; label: string }[] = [
  { key: 'background', label: '背景' },
  { key: 'problem', label: '要解决的问题' },
  { key: 'contribution', label: '核心贡献' },
  { key: 'method', label: '方法' },
  { key: 'evidence', label: '实验证据' },
  { key: 'significance', label: '实际意义' },
  { key: 'limitation', label: '局限' },
]

export default function PaperDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: paper, loading, error } = useApi(() => getPaper(id!), [id])

  // Hooks must be before early returns
  const [displayLang, setDisplayLang] = useState<'original' | 'zh'>('zh')
  const [note, setNote] = useState<string | null | undefined>(paper?.note)
  useEffect(() => setNote(paper?.note ?? null), [paper?.note])

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

  // ── AI interpretation (arXiv featured papers) ──
  // Monolingual (Chinese) rows store summary fields at the top level; legacy
  // bilingual rows keep them under { zh }. Fall back so old data still renders.
  const summary = (paper.ai_summary?.zh ?? paper.ai_summary) as PaperLayeredSummaryType | undefined
  const hasAI = !!summary
  // New 11-layer monolingual rows render with the layered PaperLayeredSummary
  // component; older rows that only carry background/problem/contribution/...
  // fall back to the flat LEGACY rendering. Detection keys must be NEW-format-
  // only (one_sentence_summary, core_idea, ...) — `background` exists in both
  // formats and would misclassify. experimental_evidence/limitations are also
  // new-format-only; including them covers the edge case where only the
  // evaluation segment succeeded in segmented generation.
  const summaryRecord = summary as Record<string, unknown> | undefined
  const isNewFormat = !!(
    summary &&
    [
      'one_sentence_summary',
      'core_idea',
      'experimental_evidence',
      'limitations',
    ].some(k => typeof summaryRecord?.[k] === 'string')
  )
  const legacyFields = isNewFormat ? [] : LEGACY_SUMMARY_FIELDS

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
                    <span className="inline-flex items-center text-xs px-1.5 py-0.5 rounded bg-[var(--tag-warn-bg)] text-[var(--tag-warn-text)] border border-[var(--tag-warn-border)]">
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
          <FavoriteButton itemId={paper.id} initialFavorited={paper.is_favorited ?? false} type="paper" size="md" note={note} onNoteChange={setNote} />
        </div>

        {paper.keywords && paper.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {paper.keywords.slice(0, 5).map(k => (
              <span
                key={k}
                className="inline-block text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)]"
              >
                {k}
              </span>
            ))}
          </div>
        )}

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
            {paper.github_url && (
              <a
                href={paper.github_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
              >
                GitHub <ExternalLink className="w-3.5 h-3.5 inline" strokeWidth={2} />
              </a>
            )}
          </div>
          {paper.source !== 'arxiv' && paper.source !== 'arxiv_fin' && paper.categories.length > 0 && (() => {
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

        {/* Favorite note */}
        {note && (
          <div className="mt-4 rounded-lg bg-black/[.03] px-4 py-3">
            <div className="text-xs font-medium text-[var(--muted)] mb-1">我的笔记</div>
            <p className="text-sm text-[var(--ink)] leading-relaxed whitespace-pre-line">{note}</p>
          </div>
        )}
      </header>

      {hasAI && summary && (
        <section className="glass rounded-[22px] p-6 mb-6">
          <CardHeading>AI 解读</CardHeading>

          {isNewFormat ? (
            <PaperLayeredSummary summary={summary} />
          ) : (
            <div className="space-y-5">
              {legacyFields.map(({ key, label }) => {
                const text = summary[key as keyof typeof summary]
                if (typeof text !== 'string' || !text) return null
                return (
                  <div key={key}>
                    <div className="text-[11px] font-bold tracking-[.14em] text-[var(--eyebrow)] mb-1">{label}</div>
                    <p className="text-[15px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">{text}</p>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      )}

      <section className="glass rounded-[22px] p-6 mb-6">
        <CardHeading>论文摘要</CardHeading>
        <p className="text-[17px] leading-[1.85] text-[var(--ink)] whitespace-pre-line">{displayAbstract}</p>
      </section>

      {paper.topics && paper.topics.length > 0 && (
        <section className="glass rounded-[22px] p-6">
          <CardHeading>主题</CardHeading>
          <div className="flex flex-wrap gap-1.5">
            {paper.topics.map((t: { id: number; name: string; slug: string; group_name: string }) => (
              <span
                key={t.slug}
                className="text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]"
              >
                {t.name}
              </span>
            ))}
          </div>
        </section>
      )}

      <hr className="my-8 border-[var(--line)]" />
      <BackLink
        fallback={{ path: '/papers', label: '返回论文库' }}
        className="inline-flex items-center gap-1 text-sm text-[var(--accent)] hover:opacity-80"
      />
    </div>
  )
}
