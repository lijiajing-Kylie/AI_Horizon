import type { ScoreBreakdown as ScoreBreakdownData } from '../api/types'

const POSITIVE_DIMENSIONS: { key: keyof ScoreBreakdownData; label: string; max: number }[] = [
  { key: 'source_authority', label: '来源权威性', max: 2 },
  { key: 'novelty', label: '新颖性', max: 2 },
  { key: 'technical_substance', label: '技术实质', max: 2 },
  { key: 'real_world_impact', label: '现实影响', max: 2 },
  { key: 'community_validation', label: '社区验证', max: 1 },
  { key: 'content_completeness', label: '内容完整度', max: 1 },
]

const PENALTY_DIMENSIONS: { key: keyof ScoreBreakdownData; label: string; max: number }[] = [
  { key: 'marketing_penalty', label: '营销扣分', max: 2 },
  { key: 'duplicate_penalty', label: '重复扣分', max: 2 },
  { key: 'thin_content_penalty', label: '内容单薄扣分', max: 2 },
  { key: 'weak_ai_relevance_penalty', label: 'AI 相关性弱扣分', max: 2 },
]

function PositiveRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) * 100 : 0
  return (
    <div className="py-1.5">
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-[var(--muted)]">{label}</span>
        <span className="font-semibold tabular-nums text-[var(--ink)]">
          {value}<span className="text-[var(--muted)] font-normal"> / {max}</span>
        </span>
      </div>
      <div className="h-1 rounded-full bg-[var(--line)] overflow-hidden">
        <div className="h-full rounded-full bg-[#A0C497]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function PenaltyRow({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-xs">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="font-medium tabular-nums text-[var(--muted)]">
        {value}<span className="font-normal"> / -{max}</span>
      </span>
    </div>
  )
}

export default function ScoreBreakdown({ breakdown }: { breakdown: ScoreBreakdownData }) {
  return (
    <section className="glass rounded-[22px] p-5">
      <h2 className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-3">评分明细</h2>

      <div className="flex items-baseline justify-between mb-4 pb-4 border-b border-[var(--line)]">
        <span className="text-sm font-medium text-[var(--muted)]">总分</span>
        <span className="text-2xl font-semibold text-[var(--ink)] tabular-nums">
          {breakdown.total.toFixed(1)} <span className="text-sm font-normal text-[var(--muted)]">/ 10</span>
        </span>
      </div>

      <div className="space-y-0.5 mb-4">
        {POSITIVE_DIMENSIONS.map(d => (
          <PositiveRow key={d.key} label={d.label} value={breakdown[d.key] ?? 0} max={d.max} />
        ))}
      </div>

      <div className="pt-3 border-t border-[var(--line)] space-y-0.5">
        {PENALTY_DIMENSIONS.map(d => (
          <PenaltyRow key={d.key} label={d.label} value={breakdown[d.key] ?? 0} max={d.max} />
        ))}
      </div>

      {typeof breakdown.multi_source_bonus === 'number' && breakdown.multi_source_bonus > 0 && (
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--line)] text-xs">
          <span className="text-[var(--muted)]">多源验证加分（≥3 个独立信源报道）</span>
          <span className="font-semibold tabular-nums text-[var(--ink)]">
            +{breakdown.multi_source_bonus}
          </span>
        </div>
      )}
    </section>
  )
}
