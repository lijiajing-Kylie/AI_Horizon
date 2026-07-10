import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, ChevronRight, Copy, Check, Code, Eye } from 'lucide-react'
import ArticleHtml from './ArticleHtml'
import type { ScrapeDiagnostics, DiagnosticsStageInput, TranslationStatus } from '../api/types'

// ── shared bits ─────────────────────────────────────────────────────────────

const TRANSLATION_STATUS_INFO: Record<TranslationStatus, { label: string; className: string }> = {
  success: { label: '翻译成功', className: 'bg-green-50 text-green-700 border-green-200' },
  skipped_already_chinese: { label: '原文已是中文，无需翻译', className: 'bg-gray-50 text-gray-600 border-gray-200' },
  failed: { label: '翻译失败', className: 'bg-red-50 text-red-700 border-red-200' },
  fallback_to_original: { label: '回退到原文（异常状态）', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  not_attempted: { label: '尚未翻译', className: 'bg-gray-50 text-gray-600 border-gray-200' },
  empty_input: { label: '输入为空', className: 'bg-gray-50 text-gray-500 border-gray-200' },
}

function StatusBadge({ status }: { status: TranslationStatus }) {
  const info = TRANSLATION_STATUS_INFO[status] ?? { label: status, className: 'bg-gray-50 text-gray-600 border-gray-200' }
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full border shrink-0 ${info.className}`}>
      {info.label}
    </span>
  )
}

function HttpStatusBadge({ status }: { status: number | null }) {
  if (status === null) return <span className="text-xs text-gray-400">无数据</span>
  const ok = status >= 200 && status < 300
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full border ${ok ? 'bg-green-50 text-green-700 border-green-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
      HTTP {status}
    </span>
  )
}

const EXTRACTION_STATUS_STYLES: Record<string, string> = {
  success: 'bg-green-50 text-green-700 border-green-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  skipped: 'bg-amber-50 text-amber-700 border-amber-200',
}

function ExtractionStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-gray-400">无数据</span>
  const cls = EXTRACTION_STATUS_STYLES[status] ?? 'bg-gray-50 text-gray-600 border-gray-200'
  return <span className={`inline-block text-xs px-2 py-0.5 rounded-full border ${cls}`}>{status}</span>
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch {
          // Clipboard API unavailable/denied — nothing else to do here.
        }
      }}
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-1.5 py-0.5 hover:bg-gray-50 shrink-0"
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? '已复制' : '复制'}
    </button>
  )
}

// Monospace, fixed max height with internal scroll (never grows the page),
// line breaks preserved, native browser find (Cmd/Ctrl+F) works because
// it's real text, not virtualized.
function PreText({ text }: { text: string }) {
  return (
    <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words font-mono text-xs text-gray-800 bg-gray-50 rounded p-2 border border-gray-100 select-text">
      {text}
    </pre>
  )
}

function CollapsibleSection({
  title, children, defaultExpanded = false, badge,
}: {
  title: string
  children: ReactNode
  defaultExpanded?: boolean
  badge?: ReactNode
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-gray-50 text-left cursor-pointer"
      >
        <span className="flex items-center gap-1.5 text-sm font-medium text-gray-700">
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
          {title}
        </span>
        {badge}
      </button>
      {expanded && <div className="p-3 bg-white">{children}</div>}
    </div>
  )
}

// A single long-text field: full content (never truncated), char count,
// copy button. `null`/empty renders "无数据" (+ an optional reason) instead
// of a blank box, so an empty field never reads as a rendering bug.
function LongTextBlock({
  title, text, length, emptyReason, defaultExpanded = false,
}: {
  title: string
  text: string | null
  length: number
  emptyReason?: string
  defaultExpanded?: boolean
}) {
  const isEmpty = !text || text.length === 0
  return (
    <CollapsibleSection
      title={title}
      defaultExpanded={defaultExpanded}
      badge={<span className="text-xs text-gray-400 shrink-0">{length.toLocaleString()} 字符</span>}
    >
      {isEmpty ? (
        <p className="text-xs text-gray-400">无数据{emptyReason ? `（${emptyReason}）` : ''}</p>
      ) : (
        <div>
          <div className="flex justify-end mb-1.5">
            <CopyButton text={text} />
          </div>
          <PreText text={text} />
        </div>
      )}
    </CollapsibleSection>
  )
}

// display_html / display_html_zh get a 源码/渲染效果 toggle. "渲染" only ever
// uses ArticleHtml, which only ever renders already nh3-sanitized fields —
// this component must never be given raw_html.
function HtmlDualView({
  title, html, length, emptyReason,
}: {
  title: string
  html: string | null
  length: number
  emptyReason?: string
}) {
  const [tab, setTab] = useState<'source' | 'rendered'>('source')
  const isEmpty = !html || html.length === 0

  return (
    <CollapsibleSection
      title={title}
      badge={<span className="text-xs text-gray-400 shrink-0">{length.toLocaleString()} 字符</span>}
    >
      {isEmpty ? (
        <p className="text-xs text-gray-400">无数据{emptyReason ? `（${emptyReason}）` : ''}</p>
      ) : (
        <div>
          <div className="flex items-center justify-between mb-1.5 gap-2">
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => setTab('source')}
                className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border cursor-pointer ${tab === 'source' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'text-gray-500 border-gray-200'}`}
              >
                <Code className="w-3 h-3" /> 源码
              </button>
              <button
                type="button"
                onClick={() => setTab('rendered')}
                className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border cursor-pointer ${tab === 'rendered' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'text-gray-500 border-gray-200'}`}
              >
                <Eye className="w-3 h-3" /> 渲染效果
              </button>
            </div>
            <CopyButton text={html} />
          </div>
          {tab === 'source' ? (
            <PreText text={html} />
          ) : (
            <div className="max-h-80 overflow-y-auto rounded p-2 border border-gray-100">
              <ArticleHtml html={html} />
            </div>
          )}
        </div>
      )}
    </CollapsibleSection>
  )
}

function KeyValueRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs py-1 border-b border-gray-50 last:border-0">
      <span className="w-28 shrink-0 text-gray-400">{label}</span>
      <span className="text-gray-700 break-all">{value ?? <span className="text-gray-300">无数据</span>}</span>
    </div>
  )
}

// Analysis / Enrichment share the exact same shape (StageInput on the
// backend), so they share one renderer.
function StageInputBlock({ title, stage }: { title: string; stage: DiagnosticsStageInput }) {
  return (
    <CollapsibleSection
      title={title}
      badge={
        <span className="text-xs text-gray-400 shrink-0">
          {stage.sent_length.toLocaleString()} / {stage.original_length.toLocaleString()} 字符
        </span>
      }
    >
      <div className="mb-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
        <div>Content Source: <span className="text-gray-700">{stage.content_source ?? '无数据'}</span></div>
        <div>截断阈值: <span className="text-gray-700">{stage.truncation_limit ?? '无数据'} 字符</span></div>
        <div>原始长度: <span className="text-gray-700">{stage.original_length.toLocaleString()}</span></div>
        <div>实际发送长度: <span className="text-gray-700">{stage.sent_length.toLocaleString()}</span></div>
      </div>
      {stage.source_note && (
        <p className="mb-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">{stage.source_note}</p>
      )}
      {stage.input ? (
        <div>
          <div className="flex justify-end mb-1.5"><CopyButton text={stage.input} /></div>
          <PreText text={stage.input} />
        </div>
      ) : (
        <p className="text-xs text-gray-400">无数据</p>
      )}
    </CollapsibleSection>
  )
}

// ── panel ─────────────────────────────────────────────────────────────────

export default function ScrapeDiagnosticsPanel({ debug }: { debug: ScrapeDiagnostics }) {
  const [expanded, setExpanded] = useState(false)
  const { source, fetch: fetchInfo, translation } = debug

  const rawHtmlHasBodyButRawContentEmpty = debug.raw_html_length > 0 && debug.raw_content_length === 0
  const rawContentHasBodyButCleanEmpty = debug.raw_content_length > 0 && debug.clean_content_length === 0
  const rawHtmlHasBodyButDisplayHtmlEmpty = debug.raw_html_length > 0 && debug.display_html_length === 0

  return (
    <section className="mt-8 border-2 border-dashed border-amber-300 rounded-lg overflow-hidden">
      <h2
        onClick={() => setExpanded(prev => !prev)}
        className="flex items-center gap-1.5 text-sm font-semibold text-amber-800 bg-amber-50 px-3 py-2 cursor-pointer select-none"
      >
        {expanded ? <ChevronDown className="w-4 h-4 shrink-0" /> : <ChevronRight className="w-4 h-4 shrink-0" />}
        🔧 抓取诊断（仅开发环境）
      </h2>

      {expanded && (
        <div className="p-3 space-y-3 bg-white">
          {/* 1. 来源信息 */}
          <CollapsibleSection title="来源信息" defaultExpanded>
            <div>
              <KeyValueRow label="原标题" value={source.original_title} />
              <KeyValueRow
                label="原始 URL"
                value={source.original_url && (
                  <a href={source.original_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                    {source.original_url}
                  </a>
                )}
              />
              <KeyValueRow label="来源" value={source.source_name} />
              <KeyValueRow label="发布时间" value={source.published_at} />
            </div>
            <div className="mt-2">
              <div className="text-xs text-gray-400 mb-1">RSS Summary</div>
              {source.rss_summary ? (
                <p className="text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 rounded p-2 border border-gray-100">
                  {source.rss_summary}
                </p>
              ) : (
                <p className="text-xs text-gray-400">无数据</p>
              )}
            </div>
          </CollapsibleSection>

          {/* 2. HTTP 与抓取状态 */}
          <CollapsibleSection title="HTTP 与抓取状态" defaultExpanded>
            <div>
              <KeyValueRow label="HTTP Status" value={<HttpStatusBadge status={fetchInfo.http_status} />} />
              <KeyValueRow label="Content-Type" value={fetchInfo.content_type ?? <span className="text-gray-300">未持久化（当前管线暂不记录）</span>} />
              <KeyValueRow label="Final URL" value={fetchInfo.final_url} />
              <KeyValueRow label="Extraction Status" value={<ExtractionStatusBadge status={fetchInfo.extraction_status} />} />
              <KeyValueRow label="Extraction Error" value={fetchInfo.extraction_error} />
              <KeyValueRow label="Content Source" value={fetchInfo.content_source} />
              <KeyValueRow label="Text Length" value={fetchInfo.text_length} />
              <KeyValueRow label="Extracted At" value={fetchInfo.extracted_at} />
              <KeyValueRow label="Extractor Version" value={fetchInfo.extractor_version} />
            </div>
            {(fetchInfo.extraction_status === 'failed' || fetchInfo.extraction_status === 'skipped') && (
              <p className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
                正文抓取{fetchInfo.extraction_status === 'failed' ? '失败' : '被跳过'}
                {fetchInfo.extraction_error ? `（原因：${fetchInfo.extraction_error}）` : ''}
                。HTTP 状态码只反映页面是否可访问，不代表正文抽取成功——下方 Raw Content 已回退到「{fetchInfo.content_source ?? '未知'}」来源。
              </p>
            )}
          </CollapsibleSection>

          {/* 3. Raw HTML — pre-only, this must never get a render tab */}
          <LongTextBlock
            title="Raw HTML（未净化源码，禁止渲染）"
            text={debug.raw_html}
            length={debug.raw_html_length}
            emptyReason="本条目未产出结构化正文 HTML"
          />

          {/* 4. Raw Content */}
          <LongTextBlock
            title="Raw Content（正文抽取结果）"
            text={debug.raw_content}
            length={debug.raw_content_length}
            emptyReason={
              rawHtmlHasBodyButRawContentEmpty
                ? '有 Raw HTML 但 Raw Content 为空 —— 纯文本抽取阶段的问题'
                : fetchInfo.extraction_status
                  ? `抓取状态：${fetchInfo.extraction_status}${fetchInfo.extraction_error ? `（${fetchInfo.extraction_error}）` : ''}`
                  : undefined
            }
          />

          {/* 5. Clean Content */}
          <LongTextBlock
            title="Clean Content（清洗结果）"
            text={debug.clean_content}
            length={debug.clean_content_length}
            emptyReason={rawContentHasBodyButCleanEmpty ? '有 Raw Content 但清洗后为空 —— 清洗阶段的问题' : undefined}
          />

          {/* 6. Display HTML */}
          <HtmlDualView
            title="Display HTML"
            html={debug.display_html}
            length={debug.display_html_length}
            emptyReason={rawHtmlHasBodyButDisplayHtmlEmpty ? '有 Raw HTML 但未生成 Display HTML —— 结构化/净化阶段的问题' : undefined}
          />

          {/* 7. Display HTML 中文 */}
          <HtmlDualView
            title="Display HTML 中文"
            html={debug.display_html_zh}
            length={debug.display_html_zh_length}
            emptyReason={TRANSLATION_STATUS_INFO[translation.status]?.label}
          />

          {/* 8. Analysis Input */}
          <StageInputBlock title="Analysis Input" stage={debug.analysis} />

          {/* 9. Enrichment Input */}
          <StageInputBlock title="Enrichment Input" stage={debug.enrichment} />

          {/* 10 & 11. Translation Input / Output */}
          <CollapsibleSection title="Translation Input / Output" badge={<StatusBadge status={translation.status} />}>
            <div className="space-y-3">
              {translation.skipped_reason && (
                <p className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded p-2">{translation.skipped_reason}</p>
              )}
              <div>
                <div className="text-xs text-gray-400 mb-1">
                  Translation Input（{translation.input_length.toLocaleString()} 字符）
                </div>
                {translation.input ? <PreText text={translation.input} /> : <p className="text-xs text-gray-400">无数据</p>}
              </div>
              <div>
                <div className="text-xs text-gray-400 mb-1">
                  Translation Output（{translation.output_length.toLocaleString()} 字符）
                </div>
                {translation.output ? (
                  <PreText text={translation.output} />
                ) : (
                  <p className="text-xs text-gray-400">
                    无数据 — {TRANSLATION_STATUS_INFO[translation.status]?.label ?? translation.status}
                  </p>
                )}
              </div>
            </div>
          </CollapsibleSection>
        </div>
      )}
    </section>
  )
}
