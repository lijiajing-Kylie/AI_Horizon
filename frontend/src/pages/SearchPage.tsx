import { useState, useEffect, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { searchItems } from '../api/client'
import { useApi } from '../hooks/useApi'
import ItemCard from '../components/ItemCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''
  const [input, setInput] = useState(q)

  // Keep the input box in sync when q changes externally (e.g. back/forward nav).
  useEffect(() => { setInput(q) }, [q])

  const { data, loading, error } = useApi(
    () => (q.trim() ? searchItems(q.trim(), 30) : Promise.resolve([])),
    [q],
  )

  const backTo = { path: q ? `/search?q=${encodeURIComponent(q)}` : '/search', label: '返回搜索' }

  function submit(e: FormEvent) {
    e.preventDefault()
    const trimmed = input.trim()
    setSearchParams(trimmed ? { q: trimmed } : {})
  }

  return (
    <div>
      <h1 className="text-[28px] font-normal text-[var(--ink)] tracking-wide mb-1">搜索</h1>
      <p className="text-sm text-[var(--muted)] mb-6">按关键词搜索新闻标题、摘要和标签</p>

      <form onSubmit={submit} className="flex gap-2 mb-6">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="输入关键词，例如 OpenAI、芯片、GitHub..."
          autoFocus
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80 transition-opacity"
        >
          搜索
        </button>
      </form>

      {!q.trim() && (
        <EmptyState title="输入关键词开始搜索" description="支持搜索新闻标题、摘要和标签" />
      )}

      {q.trim() !== '' && loading && !data && <LoadingSkeleton />}

      {q.trim() !== '' && error && (
        <EmptyState title="搜索失败" description={error} />
      )}

      {q.trim() !== '' && data && data.length === 0 && !loading && (
        <EmptyState title="没有找到相关内容" description={`没有匹配 "${q}" 的新闻`} />
      )}

      {q.trim() !== '' && data && data.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-[var(--muted)]">找到 {data.length} 条结果</p>
          {data.map(item => (
            <ItemCard key={item.id} item={item} backTo={backTo} />
          ))}
        </div>
      )}
    </div>
  )
}
