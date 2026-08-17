import { useCallback, useState } from 'react'
import { Save } from 'lucide-react'
import { exportItemToKnowledgeBase, IS_STATIC_MODE } from '../api/client'
import SaveNoteDialog from './SaveNoteDialog'

/**
 * "导出 Markdown" — 先弹出两步笔记对话框：可跳过直接下载，或在导出的 md 底部
 * 追加一条 `## 我的笔记` 模块。已存在收藏笔记时第一步改为「是 / 重新写 / 取消」。
 * 随后从后端取渲染好的 Markdown，触发浏览器原生下载 `.md` 文件。
 *
 * 文件名来自后端（由标题派生并清洗）。GitHub Pages 静态部署无后端，按钮不渲染。
 */
export default function SaveToKnowledgeBaseButton({ itemId, note }: { itemId: string; note?: string | null }) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saving'>('idle')
  const [error, setError] = useState<string | null>(null)

  const download = useCallback(async (note?: string) => {
    if (status === 'saving') return
    setStatus('saving')
    setError(null)
    try {
      const { filename, markdown } = await exportItemToKnowledgeBase(itemId, note)
      // 触发浏览器原生下载任务（出现在下载栏，而非仅按钮状态变化）
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      // 延迟撤销以兼容 Firefox（立即 revoke 可能取消下载）
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setStatus('idle')
    } catch {
      setStatus('idle')
      setError('导出失败，请稍后重试')
    }
  }, [itemId, status])

  const handleDialogDownload = useCallback((note: string) => {
    setDialogOpen(false)
    const trimmed = note.trim()
    // 空/纯空白笔记 → 不传 note，输出与「跳过笔记」完全一致
    void download(trimmed || undefined)
  }, [download])

  const handleDialogClose = useCallback(() => setDialogOpen(false), [])

  if (IS_STATIC_MODE) return null

  return (
    <>
      <button
        onClick={() => setDialogOpen(true)}
        disabled={status === 'saving'}
        title={error ?? '导出为 Markdown 并下载到本地'}
        aria-label="导出 Markdown"
        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors disabled:opacity-50"
      >
        <Save className="w-4 h-4" strokeWidth={2} />
        {status === 'saving' ? '导出中' : '导出 Markdown'}
      </button>
      {error && <span className="text-xs text-[var(--tag-warn-text)]">{error}</span>}
      <SaveNoteDialog open={dialogOpen} existingNote={note} onDownload={handleDialogDownload} onClose={handleDialogClose} />
    </>
  )
}
