import { useState, useCallback } from 'react'
import {
  putFavorite, deleteFavorite,
  putPaperFavorite, deletePaperFavorite,
  putReportFavorite, deleteReportFavorite,
  putItemNote, putPaperNote, putReportNote,
} from '../api/client'
import NoteEditDialog from './NoteEditDialog'
import ConfirmDialog from './ConfirmDialog'

interface FavoriteButtonProps {
  itemId: string
  initialFavorited: boolean
  size?: 'sm' | 'md'
  /** Which API to call — defaults to 'news' so existing call sites don't change. */
  type?: 'news' | 'paper' | 'report'
  /** 回填的已有笔记；无笔记为 null/undefined。 */
  note?: string | null
  /** 笔记保存或清除成功后回调（父组件同步展示）。 */
  onNoteChange?: (note: string | null) => void
}

export default function FavoriteButton({
  itemId, initialFavorited, size = 'sm', type = 'news', note, onNoteChange,
}: FavoriteButtonProps) {
  const [favorited, setFavorited] = useState(initialFavorited)
  const [pending, setPending] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [clearDialogOpen, setClearDialogOpen] = useState(false)
  const [unfavDialogOpen, setUnfavDialogOpen] = useState(false)

  const hasNote = !!note && note.trim().length > 0

  // 收藏 / 取消收藏(无笔记时直接执行；带笔记的取消先走 confirmUnfavorite)
  const doToggle = useCallback(async (next: boolean) => {
    if (pending) return
    setFavorited(next) // optimistic
    setPending(true)
    try {
      if (type === 'paper') {
        await (next ? putPaperFavorite(itemId) : deletePaperFavorite(itemId))
      } else if (type === 'report') {
        await (next ? putReportFavorite(itemId) : deleteReportFavorite(itemId))
      } else {
        await (next ? putFavorite(itemId) : deleteFavorite(itemId))
      }
      if (!next) onNoteChange?.(null) // 取消收藏时笔记随行删除
    } catch {
      setFavorited(!next) // revert on failure
    } finally {
      setPending(false)
    }
  }, [itemId, pending, type, onNoteChange])

  const toggle = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (pending) return
    const next = !favorited
    // 取消收藏且带笔记 → 先确认，避免笔记被静默删除
    if (favorited && hasNote) {
      setUnfavDialogOpen(true)
      return
    }
    void doToggle(next)
  }, [favorited, pending, hasNote, doToggle])

  const confirmUnfavorite = useCallback(() => {
    setUnfavDialogOpen(false)
    void doToggle(false)
  }, [doToggle])

  const openEditDialog = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!favorited || pending) return
    setEditDialogOpen(true)
  }, [favorited, pending])

  const handleSaveNote = useCallback(async (saved: string) => {
    const next = saved.trim() ? saved.trim() : null
    try {
      if (type === 'paper') await putPaperNote(itemId, next)
      else if (type === 'report') await putReportNote(itemId, next)
      else await putItemNote(itemId, next)
      onNoteChange?.(next)
      setEditDialogOpen(false)
    } catch {
      // 保存失败保持对话框打开，用户可重试或取消
    }
  }, [itemId, type, onNoteChange])

  const handleClearNote = useCallback(async () => {
    try {
      if (type === 'paper') await putPaperNote(itemId, null)
      else if (type === 'report') await putReportNote(itemId, null)
      else await putItemNote(itemId, null)
      onNoteChange?.(null)
      setClearDialogOpen(false)
    } catch {
      // 清除失败保持对话框打开，用户可重试或取消
    }
  }, [itemId, type, onNoteChange])

  const textSize = size === 'md' ? 'text-xl' : 'text-base'

  return (
    <div className="flex flex-col items-center gap-1 shrink-0">
      <button
        onClick={toggle}
        disabled={pending}
        aria-pressed={favorited}
        aria-label={favorited ? '取消收藏' : '收藏'}
        title={favorited ? '取消收藏' : '收藏'}
        className={`${textSize} leading-none transition-colors disabled:opacity-50 cursor-pointer ${
          favorited ? 'text-amber-500 hover:text-amber-600' : 'text-[var(--muted)] hover:text-amber-500'
        }`}
      >
        {favorited ? '★' : '☆'}
      </button>
      {favorited && (
        <button
          onClick={openEditDialog}
          disabled={pending}
          className="text-[10px] leading-none text-[var(--muted)] hover:text-[var(--accent)] transition-colors cursor-pointer whitespace-nowrap disabled:opacity-50"
        >
          {hasNote ? '修改/清除笔记' : '添加笔记'}
        </button>
      )}
      <NoteEditDialog
        open={editDialogOpen}
        initialNote={note ?? ''}
        onSave={handleSaveNote}
        onClear={() => { setEditDialogOpen(false); setClearDialogOpen(true) }}
        onClose={() => setEditDialogOpen(false)}
      />
      <ConfirmDialog
        open={clearDialogOpen}
        title="清除笔记"
        description="确认清空这条笔记吗？清除后无法恢复。"
        confirmLabel="清除"
        onConfirm={handleClearNote}
        onClose={() => setClearDialogOpen(false)}
      />
      <ConfirmDialog
        open={unfavDialogOpen}
        title="取消收藏"
        description="取消收藏会一并删除笔记，是否仍要取消？"
        confirmLabel="取消收藏"
        onConfirm={confirmUnfavorite}
        onClose={() => setUnfavDialogOpen(false)}
      />
    </div>
  )
}
