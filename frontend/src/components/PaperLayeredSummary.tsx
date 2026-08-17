import { useState, useRef, useEffect } from 'react'
import { ChevronDown } from 'lucide-react'
import type { PaperLayeredSummary } from '../api/types'

/**
 * 详细解读 accordion 条目配置（title 固定；fields 对应 PaperLayeredSummary 字段）。
 * 第一组「为什么会有这个问题？」v3 起用合并的 background_problem；旧行
 * （v<3）只有 background/previous_problem，回退渲染这两个。
 */
function buildAccordionItems(
  summary: PaperLayeredSummary,
): { title: string; fields: { key: keyof PaperLayeredSummary; label: string }[]; muted?: boolean }[] {
  const text = (k: keyof PaperLayeredSummary) =>
    typeof summary[k] === 'string' ? (summary[k] as string).trim() : ''
  const problemFields: { key: keyof PaperLayeredSummary; label: string }[] = []
  if (text('background_problem')) {
    problemFields.push({ key: 'background_problem', label: '背景与问题' })
  } else {
    if (text('background')) problemFields.push({ key: 'background', label: '背景' })
    if (text('previous_problem')) problemFields.push({ key: 'previous_problem', label: '过去方法的不足' })
  }
  return [
    { title: '为什么会有这个问题？', fields: problemFields },
    { title: '作者提出了什么方法？', fields: [{ key: 'core_idea', label: '' }] },
    { title: '实验结果', fields: [{ key: 'experimental_evidence', label: '' }] },
    { title: '技术细节', fields: [{ key: 'technical_details', label: '' }], muted: true },
    { title: '局限性', fields: [{ key: 'limitations', label: '' }] },
  ]
}

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
                <div className="text-[11px] font-bold tracking-[.14em] text-[var(--eyebrow)] mb-1">
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
 * 论文 AI 解读的分层展示（仅新格式）：
 * Part 1 首屏「30秒理解」+ Part 2「展开详细解读」可折叠区。
 */
export default function PaperLayeredSummary({ summary }: { summary: PaperLayeredSummary }) {
  const [detailOpen, setDetailOpen] = useState(false)
  const accordionItems = buildAccordionItems(summary)
  const oneSentence = summary.one_sentence_summary?.trim()
  const impact = summary.real_world_impact?.trim()

  // 任一 accordion 条目有内容才显示总开关。
  const hasDetail = accordionItems.some(item =>
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
            <div className="text-[11px] font-bold tracking-[.14em] text-[var(--eyebrow)] mb-2">30秒理解</div>
            <p className="text-xl leading-relaxed font-medium text-[var(--ink)] pl-4 border-l-2 border-[var(--accent)]/50">
              {oneSentence}
            </p>
          </div>
        )}

        {impact && (
          <div>
            <div className="text-[11px] font-bold tracking-[.14em] text-[var(--eyebrow)] mb-2">可能带来什么改变</div>
            <ClampText
              text={impact}
              className="text-[15px] leading-[1.85] text-[var(--ink)] whitespace-pre-line"
            />
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
              {accordionItems.map(item => (
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
