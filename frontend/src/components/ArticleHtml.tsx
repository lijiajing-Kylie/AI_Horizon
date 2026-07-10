import { useEffect, useRef } from 'react'

// Renders sanitized article HTML via dangerouslySetInnerHTML. Only ever pass
// already nh3-sanitized fields here (display_html / display_html_zh) — never
// raw_html, which is explicitly unsanitized (see content_extractor.py).
//
// Images inside raw HTML don't get React's onError handling for free, so a
// broken image (dead link, blocked hotlink) is hidden via a plain DOM
// listener instead.
export default function ArticleHtml({ html, className }: { html: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = ref.current
    if (!container) return
    const imgs = Array.from(container.querySelectorAll('img'))
    const hide = (e: Event) => {
      (e.currentTarget as HTMLImageElement).style.display = 'none'
    }
    imgs.forEach(img => img.addEventListener('error', hide))
    return () => imgs.forEach(img => img.removeEventListener('error', hide))
  }, [html])

  return (
    <div
      ref={ref}
      className={className ?? 'article-html text-sm text-gray-800 leading-[1.7]'}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
