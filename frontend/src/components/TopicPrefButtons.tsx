import type { TopicPrefState } from '../api/types'

interface TopicPrefButtonsProps {
  state: TopicPrefState | null
  onToggle: (next: TopicPrefState | null) => void
}

/** Subscribe/block toggle for one topic. Clicking an already-active state
 * clears it back to "no preference" rather than requiring a third button.
 *
 * Controlled: the caller owns the state (see hooks/useTopicPrefs.ts) so that
 * when the same topic is rendered more than once on a page (e.g. a
 * subscribed/blocked summary plus the full topic list), every instance
 * stays in sync. */
export default function TopicPrefButtons({ state, onToggle }: TopicPrefButtonsProps) {
  const baseBtn = 'px-2.5 py-1 rounded-full text-xs border transition-colors cursor-pointer'

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => onToggle(state === 'subscribed' ? null : 'subscribed')}
        className={`${baseBtn} ${
          state === 'subscribed'
            ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
            : 'border-[var(--line)] text-[var(--muted)] hover:bg-white/70'
        }`}
      >
        {state === 'subscribed' ? '✓ 已订阅' : '+ 订阅'}
      </button>
      <button
        type="button"
        onClick={() => onToggle(state === 'blocked' ? null : 'blocked')}
        className={`${baseBtn} ${
          state === 'blocked'
            ? 'bg-[var(--ink)] text-white border-[var(--ink)]'
            : 'border-[var(--line)] text-[var(--muted)] hover:bg-white/70'
        }`}
      >
        {state === 'blocked' ? '✓ 已屏蔽' : '屏蔽'}
      </button>
    </div>
  )
}
