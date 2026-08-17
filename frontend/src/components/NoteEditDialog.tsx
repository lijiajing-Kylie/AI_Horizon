import { useEffect, useRef, useState } from 'react'

interface NoteEditDialogProps {
  open: boolean
  /** 打开时回填的已有笔记。 */
  initialNote: string
  /** 点「保存」时回调（原始字符串；空串=清除，由调用方归一化）。 */
  onSave: (note: string) => void
  /** 点「清除笔记」时回调（编辑已有笔记时显示）。 */
  onClear?: () => void
  /** 取消 / Escape / 点击遮罩时回调。 */
  onClose: () => void
}

/**
 * 收藏笔记编辑对话框：单步直接输入，不复用「保存到知识库」的询问步。
 * 复用 SaveNoteDialog 的原生 <dialog>.showModal() 模式（top layer、焦点陷阱、
 * Escape 关闭、::backdrop 遮罩已在 index.css 定义）。
 */
export default function NoteEditDialog({ open, initialNote, onSave, onClear, onClose }: NoteEditDialogProps) {
  const [note, setNote] = useState('')
  const dialogRef = useRef<HTMLDialogElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // open ↔ showModal()/close()；打开时回填已有笔记
  useEffect(() => {
    if (open) {
      setNote(initialNote)
      if (dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal()
    } else if (dialogRef.current?.open) {
      dialogRef.current.close()
    }
  }, [open, initialNote])

  // 打开即聚焦 textarea
  useEffect(() => {
    if (open) textareaRef.current?.focus()
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        // :modal 下点击 ::backdrop 区域时事件目标就是 <dialog> 本身
        if (e.target === dialogRef.current) onClose()
      }}
      aria-labelledby="note-edit-title"
      className="m-auto w-[min(90vw,420px)] rounded-2xl border border-[var(--line)] bg-[var(--dropdown-bg)] p-5 shadow-[var(--dropdown-shadow)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="note-edit-title" className="text-base font-semibold text-[var(--ink)]">
            我的笔记
          </h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            保存后显示在卡片底部；清空保存会删除这条笔记。
          </p>
        </div>
        {initialNote.trim() && onClear && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-[var(--muted)] hover:text-[var(--accent)] transition-colors cursor-pointer whitespace-nowrap shrink-0"
          >
            清除笔记
          </button>
        )}
      </div>
      <textarea
        ref={textareaRef}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="我的笔记"
        placeholder="写点你的想法"
        className="mt-4 w-full min-h-[96px] resize-y rounded-lg border border-[var(--line)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--input-text)] placeholder:text-[var(--input-placeholder)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
      />
      <div className="mt-4 flex flex-wrap gap-2 justify-end">
        <button
          type="button"
          onClick={onClose}
          className="min-h-[44px] inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => onSave(note)}
          className="min-h-[44px] px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80"
        >
          保存
        </button>
      </div>
    </dialog>
  )
}
