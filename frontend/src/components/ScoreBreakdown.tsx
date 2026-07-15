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

function DimensionRow({
  label,
  value,
  max,
  isPenalty,
}: {
  label: string
  value: number
  max: number
  isPenalty: boolean
}) {
  const valueColor = isPenalty
    ? value < 0
      ? 'text-red-600'
      : 'text-gray-400'
    : value >= max
      ? 'text-emerald-600'
      : value > 0
        ? 'text-amber-600'
        : 'text-gray-400'

  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-gray-600">{label}</span>
      <span className={`font-semibold tabular-nums ${valueColor}`}>
        {value > 0 && !isPenalty ? '+' : ''}
        {value}
        <span className="text-gray-400 font-normal"> / {isPenalty ? `-${max}` : max}</span>
      </span>
    </div>
  )
}

export default function ScoreBreakdown({ breakdown }: { breakdown: ScoreBreakdownData }) {
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        评分明细
      </h2>
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-baseline justify-between mb-3 pb-3 border-b border-gray-100">
          <span className="text-sm font-semibold text-gray-500">总分</span>
          <span className="text-lg font-bold text-gray-900 tabular-nums">
            {breakdown.total.toFixed(1)} <span className="text-gray-400 font-normal text-sm">/ 10</span>
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 sm:gap-x-6">
          <div>
            {POSITIVE_DIMENSIONS.map(d => (
              <DimensionRow
                key={d.key}
                label={d.label}
                value={breakdown[d.key] ?? 0}
                max={d.max}
                isPenalty={false}
              />
            ))}
          </div>
          <div>
            {PENALTY_DIMENSIONS.map(d => (
              <DimensionRow
                key={d.key}
                label={d.label}
                value={breakdown[d.key] ?? 0}
                max={d.max}
                isPenalty={true}
              />
            ))}
          </div>
        </div>
        {typeof breakdown.multi_source_bonus === 'number' && breakdown.multi_source_bonus > 0 && (
          <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-100 text-sm">
            <span className="text-gray-600">多源验证加分（≥3 个独立信源报道）</span>
            <span className="font-semibold tabular-nums text-emerald-600">
              +{breakdown.multi_source_bonus}
            </span>
          </div>
        )}
      </div>
    </section>
  )
}
