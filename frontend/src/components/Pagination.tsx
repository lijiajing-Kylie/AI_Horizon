interface PaginationProps {
  page: number
  pages: number
  onPageChange: (page: number) => void
}

function ArrowIcon({ direction }: { direction: 'prev' | 'next' }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
    >
      {direction === 'prev' ? (
        <path d="M9 3L5 7L9 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M5 3L9 7L5 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  )
}

export default function Pagination({ page, pages, onPageChange }: PaginationProps) {
  if (pages <= 1) return null

  return (
    <div className="flex justify-center items-center gap-3 py-6">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="inline-flex items-center gap-1.5 px-4 py-2.5 sm:py-2 min-h-[44px] text-sm font-medium border border-[var(--line)] rounded-xl text-[var(--ink)] bg-transparent hover:bg-white/60 hover:border-[var(--accent)]/30 disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:border-[var(--line)] transition-all duration-200 active:scale-95"
      >
        <ArrowIcon direction="prev" />
        <span>上一页</span>
      </button>

      <span className="text-sm text-[var(--muted)] tabular-nums">{page} / {pages}</span>

      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= pages}
        className="inline-flex items-center gap-1.5 px-4 py-2.5 sm:py-2 min-h-[44px] text-sm font-medium border border-[var(--line)] rounded-xl text-[var(--ink)] bg-transparent hover:bg-white/60 hover:border-[var(--accent)]/30 disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:border-[var(--line)] transition-all duration-200 active:scale-95"
      >
        <span>下一页</span>
        <ArrowIcon direction="next" />
      </button>
    </div>
  )
}
