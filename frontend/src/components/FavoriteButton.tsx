import { useState, useCallback } from 'react'
import { putFavorite, deleteFavorite, putPaperFavorite, deletePaperFavorite, putReportFavorite, deleteReportFavorite } from '../api/client'

interface FavoriteButtonProps {
  itemId: string
  initialFavorited: boolean
  size?: 'sm' | 'md'
  /** Which API to call — defaults to 'news' so existing call sites don't change. */
  type?: 'news' | 'paper' | 'report'
}

export default function FavoriteButton({ itemId, initialFavorited, size = 'sm', type = 'news' }: FavoriteButtonProps) {
  const [favorited, setFavorited] = useState(initialFavorited)
  const [pending, setPending] = useState(false)

  const toggle = useCallback(async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (pending) return
    const next = !favorited
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
    } catch {
      setFavorited(!next) // revert on failure
    } finally {
      setPending(false)
    }
  }, [favorited, itemId, pending, type])

  const textSize = size === 'md' ? 'text-xl' : 'text-base'

  return (
    <button
      onClick={toggle}
      disabled={pending}
      aria-pressed={favorited}
      aria-label={favorited ? '取消收藏' : '收藏'}
      title={favorited ? '取消收藏' : '收藏'}
      className={`${textSize} leading-none transition-colors disabled:opacity-50 cursor-pointer ${
        favorited ? 'text-amber-500 hover:text-amber-600' : 'text-gray-300 hover:text-amber-500'
      }`}
    >
      {favorited ? '★' : '☆'}
    </button>
  )
}
