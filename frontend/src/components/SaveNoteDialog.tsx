import { useEffect, useRef, useState } from 'react'

interface SaveNoteDialogProps {
  open: boolean
  /** 该内容已有的收藏笔记（有值时第一步询问"是/重写/取消"）。 */
  existingNote?: string | null
  /** 用户点「跳过笔记」/「是」/「确认下载」时调用；空字符串 = 无笔记（等价跳过）。 */
  onDownload: (note: string) => void
  /** 取消 / Escape / 点击遮罩时调用，不触发下载。 */
  onClose: () => void
}

/**
 * 两步「保存到知识库」对话框：先问是否添加笔记，选择「添加笔记」后展开
 * textarea 输入心得，最后确认下载或取消。已有收藏笔记时第一步改为
 * 「是 / 重写 / 取消」——「是」直接带现有笔记下载，「重写」进入编辑。
 *
 * 用原生 <dialog>.showModal()（本项目第一个 modal）：走 top layer，脱离
 * .glass 祖先的 stacking context / overflow 裁剪，且免费获得焦点陷阱、
 * Escape 关闭（cancel → close）与 ::backdrop 遮罩。
 */
export default function SaveNoteDialog({ open, existingNote, onDownload, onClose }: SaveNoteDialogProps) {
  const hasNote = !!existingNote && existingNote.trim().length > 0
  const [step, setStep] = useState<'choose' | 'note'>('choose')
  const [note, setNote] = useState('')
  const dialogRef = useRef<HTMLDialogElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // open ↔ showModal()/close()；每次打开都重置到第一步并清空输入
  useEffect(() => {
    if (open) {
      setStep('choose')
      setNote('')
      if (dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal()
      // showModal() 后 autoFocus 已错过（挂载时 dialog 尚未 open、不可聚焦），
      // 否则焦点会落到 dialog 内第一个可聚焦元素（「取消」）上。显式聚焦主操作。
      dialogRef.current?.querySelector<HTMLButtonElement>('[data-primary]')?.focus()
    } else if (dialogRef.current?.open) {
      dialogRef.current.close()
    }
  }, [open])

  // 进入输入步骤时聚焦 textarea
  useEffect(() => {
    if (open && step === 'note') textareaRef.current?.focus()
  }, [open, step])

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        // :modal 下点击 ::backdrop 区域时事件目标就是 <dialog> 本身
        if (e.target === dialogRef.current) onClose()
      }}
      aria-labelledby="save-note-title"
      className="m-auto w-[min(90vw,420px)] rounded-2xl border border-[var(--line)] bg-[var(--dropdown-bg)] p-5 shadow-[var(--dropdown-shadow)]"
    >
      <h2 id="save-note-title" className="text-base font-semibold text-[var(--ink)]">
        导出 Markdown
      </h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        {step === 'choose'
          ? (hasNote ? '已有笔记，是否添加到导出的文件中？' : '是否在导出的文件中添加笔记？')
          : '笔记只写入导出的文件，不会保存到收藏。'}
      </p>

      {step === 'choose' ? (
        hasNote ? (
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
              onClick={() => { setNote(''); setStep('note') }}
              className="min-h-[44px] inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors"
            >
              重写
            </button>
            <button
              type="button"
              data-primary
              onClick={() => onDownload(existingNote ?? '')}
              className="min-h-[44px] px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80"
            >
              是
            </button>
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap gap-2 justify-end">
            <button
              type="button"
              onClick={() => onDownload('')}
              className="min-h-[44px] inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors"
            >
              跳过笔记
            </button>
            <button
              type="button"
              data-primary
              onClick={() => setStep('note')}
              className="min-h-[44px] px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80"
            >
              添加笔记
            </button>
          </div>
        )
      ) : (
        <>
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
              onClick={() => onDownload(note)}
              className="min-h-[44px] px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80"
            >
              确认下载
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
