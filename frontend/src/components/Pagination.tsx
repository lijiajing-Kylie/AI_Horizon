interface PaginationProps {
  page: number
  pages: number
  onPageChange: (page: number) => void
}

export default function Pagination({ page, pages, onPageChange }: PaginationProps) {
  if (pages <= 1) return null

  return (
    <div className="flex justify-center items-center gap-3 py-6">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        ← 上一页
      </button>
      <span className="text-sm text-gray-500">{page} / {pages}</span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= pages}
        className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        下一页 →
      </button>
    </div>
  )
}
