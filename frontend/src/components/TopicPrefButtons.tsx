import { useState, useCallback } from 'react'
import { putTopicPref } from '../api/client'
import type { TopicPrefState } from '../api/types'

interface TopicPrefButtonsProps {
  slug: string
  initialState: TopicPrefState | null
}

/** Subscribe/block toggle for one topic. Clicking an already-active state
 * clears it back to "no preference" rather than requiring a third button. */
export default function TopicPrefButtons({ slug, initialState }: TopicPrefButtonsProps) {
  const [state, setState] = useState<TopicPrefState | null>(initialState)
  const [pending, setPending] = useState(false)

  const setPref = useCallback(async (next: TopicPrefState | null) => {
    if (pending) return
    const prev = state
    setState(next) // optimistic
    setPending(true)
    try {
      await putTopicPref(slug, next)
    } catch {
      setState(prev) // revert on failure
    } finally {
      setPending(false)
    }
  }, [pending, slug, state])

  const baseBtn = 'px-2.5 py-1 rounded text-xs border transition-colors disabled:opacity-50 cursor-pointer'

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        disabled={pending}
        onClick={() => setPref(state === 'subscribed' ? null : 'subscribed')}
        className={`${baseBtn} ${
          state === 'subscribed'
            ? 'bg-blue-600 text-white border-blue-600'
            : 'border-gray-300 text-gray-600 hover:bg-gray-50'
        }`}
      >
        {state === 'subscribed' ? '✓ 已订阅' : '+ 订阅'}
      </button>
      <button
        type="button"
        disabled={pending}
        onClick={() => setPref(state === 'blocked' ? null : 'blocked')}
        className={`${baseBtn} ${
          state === 'blocked'
            ? 'bg-gray-700 text-white border-gray-700'
            : 'border-gray-300 text-gray-600 hover:bg-gray-50'
        }`}
      >
        {state === 'blocked' ? '✓ 已屏蔽' : '🚫 屏蔽'}
      </button>
    </div>
  )
}
