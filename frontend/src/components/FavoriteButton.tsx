import { useState, useCallback } from 'react'
import { putFavorite, deleteFavorite } from '../api/client'

interface FavoriteButtonProps {
  itemId: string
  initialFavorited: boolean
  size?: 'sm' | 'md'
}

export default function FavoriteButton({ itemId, initialFavorited, size = 'sm' }: FavoriteButtonProps) {
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
      await (next ? putFavorite(itemId) : deleteFavorite(itemId))
    } catch {
      setFavorited(!next) // revert on failure
    } finally {
      setPending(false)
    }
  }, [favorited, itemId, pending])

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
