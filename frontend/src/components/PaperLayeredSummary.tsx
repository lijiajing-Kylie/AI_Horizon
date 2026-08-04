import { useState, useRef, useEffect } from 'react'
import { ChevronDown, ArrowDown } from 'lucide-react'
import type { PaperLayeredSummary } from '../api/types'

/** innovation_level.level 枚举 → 中文标签。 */
const INNOVATION_LABELS: Record<string, string> = {
  breakthrough: '重大突破',
  significant_improvement: '重要改进',
  incremental: '渐进优化',
  engineering: '工程优化',
}

/**
 * 创新等级 badge，用于标题旁。悬停时以 tooltip 展示「它为什么属于这个等级」。
 * 悬停即可，无需点击（a11y 由原生 title 兜底；reason 为空则不渲染 tooltip）。
 */
export function InnovationBadge({ level, reason }: { level: string; reason?: string }) {
  const label = INNOVATION_LABELS[level] ?? level
  return (
    <span className="relative inline-block group align-middle">
      <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)] font-medium">
        {label}
      </span>
      {reason && (
        <span
          title={reason}
          className="absolute left-0 top-full mt-1.5 hidden group-hover:block z-10 w-72 max-w-[80vw] rounded-xl bg-[var(--dropdown-bg)] border border-[var(--line)] shadow-[var(--dropdown-shadow)] px-3 py-2 text-xs leading-relaxed text-[var(--muted)] pointer-events-none whitespace-pre-line"
        >
          它为什么属于这个等级：{reason}
        </span>
      )}
    </span>
  )
}

/** 详细解读 accordion 的条目配置（title 固定；fields 对应 PaperLayeredSummary 字段）。 */
const ACCORDION_ITEMS: {
  title: string
  fields: { key: keyof PaperLayeredSummary; label: string }[]
  muted?: boolean
}[] = [
  {
    title: '为什么会有这个问题？',
    fields: [
      { key: 'background', label: '背景' },
      { key: 'previous_problem', label: '过去方法的不足' },
    ],
  },
  {
    title: '作者提出了什么方法？',
    fields: [
      { key: 'core_idea', label: '核心创新' },
      { key: 'how_it_works', label: '如何实现' },
    ],
  },
  { title: '技术细节', fields: [{ key: 'technical_details', label: '' }], muted: true },
  { title: '实验结果', fields: [{ key: 'experimental_evidence', label: '' }] },
  { title: '实际影响', fields: [{ key: 'real_world_impact', label: '' }] },
  { title: '局限性', fields: [{ key: 'limitations', label: '' }] },
]

/**
 * 通用「默认截断 + 展开/收起」文本。默认最多显示 3 行，超长时显示「展开」按钮；
 * 展开后显示全文并切换为「收起」。仅在确实超长时才渲染按钮。
 */
function ClampText({ text, className }: { text: string; className?: string }) {
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const ref = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      // line-clamp 仅在折叠态生效，此时 scrollHeight > clientHeight 说明内容超长。
      if (!expanded) setOverflowing(el.scrollHeight > el.clientHeight + 1)
    }
    measure()
    window.addEventListener('resize', measure)
    // 字体加载完成后行高可能变化，需重新测量。
    document.fonts.ready.then(measure).catch(() => {})
    return () => window.removeEventListener('resize', measure)
  }, [text, expanded])

  return (
    <div>
      <p ref={ref} className={`${className ?? ''} ${expanded ? '' : 'line-clamp-3'}`}>
        {text}
      </p>
      {overflowing && (
        <button
          type="button"
          onClick={() => setExpanded(prev => !prev)}
          className="mt-1.5 text-xs font-medium text-[var(--accent)] hover:opacity-80 cursor-pointer"
        >
          {expanded ? '收起' : '展开'}
        </button>
      )}
    </div>
  )
}

/** 折叠项：button 作 header（a11y），每项独立 state，可同时展开多个。 */
function AccordionItem({
  title,
  fields,
  summary,
  muted,
}: {
  title: string
  fields: { key: keyof PaperLayeredSummary; label: string }[]
  summary: PaperLayeredSummary
  muted?: boolean
}) {
  const [open, setOpen] = useState(false)
  const present = fields
    .map(f => {
      const raw = summary[f.key]
      const text = typeof raw === 'string' ? raw.trim() : ''
      return { key: f.key, label: f.label, text }
    })
    .filter(f => !!f.text)
  if (present.length === 0) return null

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(prev => !prev)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-2 py-3 text-left cursor-pointer group"
      >
        <span className="text-[15px] font-medium text-[var(--ink)] group-hover:text-[var(--accent)] transition-colors">
          {title}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-[var(--muted)] shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="pb-4 space-y-4">
          {present.map(f => (
            <div key={f.key}>
              {f.label && (
                <div className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-1">
                  {f.label}
                </div>
              )}
              <p
                className={
                  muted
                    ? 'text-sm leading-relaxed text-[var(--muted)] whitespace-pre-line'
                    : 'text-[15px] leading-[1.85] text-[var(--ink)] whitespace-pre-line'
                }
              >
                {f.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * 论文 AI 解读的分层展示（仅新 11 字段格式）：
 * Part 1 首屏「30秒理解」+ Part 2「展开详细解读」可折叠区。
 * 创新等级 badge 由上层（标题处）通过 InnovationBadge 展示。
 */
export default function PaperLayeredSummary({ summary }: { summary: PaperLayeredSummary }) {
  const [detailOpen, setDetailOpen] = useState(false)
  const oneSentence = summary.one_sentence_summary?.trim()
  const why = summary.why_it_matters?.trim()
  const prevProblem = summary.previous_problem?.trim()
  const coreIdea = summary.core_idea?.trim()

  // 任一 accordion 条目有内容才显示总开关。
  const hasDetail = ACCORDION_ITEMS.some(item =>
    item.fields.some(f => {
      const raw = summary[f.key]
      return typeof raw === 'string' && raw.trim().length > 0
    }),
  )

  return (
    <div>
      {/* ── Part 1：首屏（默认展开） ───────────────────────────── */}
      <div className="space-y-6">
        {oneSentence && (
          <div>
            <div className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-2">30秒理解</div>
            <p className="text-xl leading-relaxed font-medium text-[var(--ink)] pl-4 border-l-2 border-[var(--accent)]/50">
              {oneSentence}
            </p>
          </div>
        )}

        {why && (
          <div>
            <div className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-2">为什么值得关注？</div>
            <ClampText
              text={why}
              className="text-[15px] leading-[1.85] text-[var(--ink)] whitespace-pre-line"
            />
          </div>
        )}

        {(prevProblem || coreIdea) && (
          <div>
            <div className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-2">核心创新</div>
            <div className="space-y-2">
              {prevProblem && (
                <div className="rounded-xl bg-black/[.03] px-4 py-3">
                  <div className="text-xs font-medium text-[var(--muted)] mb-1">过去</div>
                  <ClampText
                    text={prevProblem}
                    className="text-sm leading-relaxed text-[var(--muted)] whitespace-pre-line"
                  />
                </div>
              )}
              {prevProblem && coreIdea && (
                <div className="flex justify-center py-0.5">
                  <ArrowDown className="w-4 h-4 text-[var(--accent)]" strokeWidth={2} />
                </div>
              )}
              {coreIdea && (
                <div className="rounded-xl bg-[var(--accent)]/5 border border-[var(--accent)]/15 px-4 py-3">
                  <div className="text-xs font-medium text-[var(--accent)] mb-1">本文</div>
                  <ClampText
                    text={coreIdea}
                    className="text-sm leading-relaxed text-[var(--ink)] whitespace-pre-line"
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Part 2：展开详细解读（总开关，默认折叠） ───────────── */}
      {hasDetail && (
        <div className="mt-8">
          <button
            type="button"
            onClick={() => setDetailOpen(prev => !prev)}
            aria-expanded={detailOpen}
            className="w-full flex items-center justify-center gap-1.5 rounded-xl border border-[var(--line)] py-3 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors cursor-pointer"
          >
            {detailOpen ? '收起详细解读' : '展开详细解读'}
            <ChevronDown
              className={`w-4 h-4 text-[var(--muted)] transition-transform ${detailOpen ? 'rotate-180' : ''}`}
            />
          </button>
          {detailOpen && (
            <div className="divide-y divide-[var(--line)] mt-2">
              {ACCORDION_ITEMS.map(item => (
                <AccordionItem
                  key={item.title}
                  title={item.title}
                  fields={item.fields}
                  summary={summary}
                  muted={item.muted}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
