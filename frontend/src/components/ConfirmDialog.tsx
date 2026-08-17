import { useEffect, useRef } from 'react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  /** 确认按钮文字，默认「确认」。 */
  confirmLabel?: string
  /** 点「确认」时回调。 */
  onConfirm: () => void
  /** 取消 / Escape / 点击遮罩时回调。 */
  onClose: () => void
}

/**
 * 通用确认对话框：复用项目里 <dialog>.showModal() 模式（top layer、焦点陷阱、
 * Escape 关闭、::backdrop 遮罩已在 index.css 定义）。用于"是否确认执行"这类
 * 轻量确认，不含输入框。
 */
export default function ConfirmDialog({ open, title, description, confirmLabel = '确认', onConfirm, onClose }: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  // open ↔ showModal()/close()
  useEffect(() => {
    if (open) {
      if (dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal()
    } else if (dialogRef.current?.open) {
      dialogRef.current.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        // :modal 下点击 ::backdrop 区域时事件目标就是 <dialog> 本身
        if (e.target === dialogRef.current) onClose()
      }}
      aria-labelledby="confirm-dialog-title"
      className="m-auto w-[min(90vw,380px)] rounded-2xl border border-[var(--line)] bg-[var(--dropdown-bg)] p-5 shadow-[var(--dropdown-shadow)]"
    >
      <h2 id="confirm-dialog-title" className="text-base font-semibold text-[var(--ink)]">
        {title}
      </h2>
      {description && <p className="mt-1 text-sm text-[var(--muted)]">{description}</p>}
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
          onClick={onConfirm}
          className="min-h-[44px] px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-80"
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
