import { useState, useEffect, useRef, type FormEvent } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Search, Settings, Check } from 'lucide-react'
import {
  DEFAULT_THEME,
  getAccentPresets,
  getDefaultAccent,
  getStoredAccent,
  getStoredTheme,
  setAccent,
  setTheme,
  THEME_PRESETS,
} from '../utils/theme'
import { globalSearch } from '../api/client'
import type { NewsItem, Paper, Report } from '../api/types'

const NAV_LINKS = [
  { to: '/', label: '首页' },
  { to: '/daily', label: '日报' },
  { to: '/papers', label: '论文' },
  { to: '/reports', label: '报告' },
  { to: '/favorites', label: '收藏' },
]

export default function Layout() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [accent, setAccentState] = useState(() => {
    const stored = getStoredAccent()
    if (stored) return stored
    const t = getStoredTheme() ?? DEFAULT_THEME
    return getDefaultAccent(t)
  })
  const [theme, setThemeState] = useState(() => getStoredTheme() ?? DEFAULT_THEME)

  // Autocomplete
  const [suggestions, setSuggestions] = useState<{ news: NewsItem[]; papers: Paper[]; reports: Report[]; total: number } | null>(null)
  const [showDropdown, setShowDropdown] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) { setSuggestions(null); setShowDropdown(false); return }

    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await globalSearch({ q, per_page: 3, news_page: 1, papers_page: 1, reports_page: 1 })
        if (!res) return
        const total = (res.news?.total ?? 0) + (res.papers?.total ?? 0) + (res.reports?.total ?? 0)
        setSuggestions({
          news: (res.news?.items ?? []) as NewsItem[],
          papers: (res.papers?.items ?? []) as Paper[],
          reports: (res.reports?.items ?? []) as Report[],
          total,
        })
        setShowDropdown(true)
      } catch { /* ignore */ }
    }, 300)

    return () => clearTimeout(debounceRef.current)
  }, [query])

  // Close dropdown on outside click
  useEffect(() => {
    if (!showDropdown) return
    const handleClick = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showDropdown])

  const totalHits = (suggestions?.news.length ?? 0) + (suggestions?.papers.length ?? 0) + (suggestions?.reports.length ?? 0)

  const isActive = (to: string) => (to === '/' ? pathname === '/' : pathname.startsWith(to))

  function chooseAccent(value: string) {
    setAccent(value)
    setAccentState(value)
  }

  function chooseTheme(value: string) {
    setTheme(value)
    setThemeState(value)
    const newDefault = getDefaultAccent(value)
    chooseAccent(newDefault)
  }

  function submitSearch(e: FormEvent) {
    e.preventDefault()
    const q = query.trim()
    navigate(q ? `/search?q=${encodeURIComponent(q)}` : '/search')
  }

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Header */}
      <header
        className="sticky top-0 z-20 h-[48px] backdrop-blur border-b border-[var(--line)] transition-colors"
        style={{
          backgroundColor: 'var(--header-bg)',
          boxShadow: 'var(--header-shadow)',
        }}
      >
        <div className="w-[min(1280px,calc(100%-48px))] h-full mx-auto flex items-center justify-between gap-6">
          <div className="flex items-center gap-8">
            <Link to="/" className="text-xl font-bold text-[var(--ink)] hover:text-[var(--accent)] transition-colors shrink-0" style={{ fontFamily: 'Homenaje, Arial, sans-serif', letterSpacing: '0.04em' }}>
              Horizon
            </Link>
            <nav className="flex items-center gap-7">
              {NAV_LINKS.map(({ to, label }) => (
                <Link
                  key={to}
                  to={to}
                  className={`relative py-4 text-sm font-medium transition-colors ${
                    isActive(to) ? 'text-[var(--accent)]' : 'text-[var(--nav-text)] hover:text-[var(--accent)]'
                  }`}
                >
                  {label}
                  {isActive(to) && (
                    <span className="absolute left-0 right-0 -bottom-px h-0.5 rounded-full bg-[var(--accent)]" />
                  )}
                </Link>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-3">
          <div ref={searchRef} className="relative">
            <form onSubmit={submitSearch} className="flex items-center gap-2 w-[210px] focus-within:w-[260px] h-[28px] px-3 rounded-full transition-all focus-within:shadow-[0_0_0_3px_var(--input-focus-ring)]"
              style={{
                backgroundColor: 'var(--input-bg)',
                borderColor: 'var(--input-border)',
              }}
            >
              <Search className="w-4 h-4 shrink-0" strokeWidth={1.8} style={{ color: 'var(--input-icon)' }} />
              <input
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="搜索标题或主题"
                aria-label="搜索标题或主题"
                className="w-full bg-transparent text-xs outline-none"
                style={{ color: 'var(--input-text)' }}
                onFocus={e => {
                  const bg = getComputedStyle(document.documentElement).getPropertyValue('--input-focus-bg').trim()
                  e.currentTarget.parentElement!.style.backgroundColor = bg || 'white'
                }}
                onBlur={e => {
                  const bg = getComputedStyle(document.documentElement).getPropertyValue('--input-bg').trim()
                  e.currentTarget.parentElement!.style.backgroundColor = bg || '#f7f8f9'
                }}
              />
            </form>

            {showDropdown && suggestions && totalHits > 0 && (
              <div className="absolute top-[36px] left-0 z-40 w-[360px] p-2 rounded-2xl border border-[var(--line)] transition-colors"
                style={{
                  backgroundColor: 'var(--dropdown-bg)',
                  boxShadow: 'var(--dropdown-shadow)',
                }}
              >
                {[/* news */ ...(suggestions.news.length > 0 ? [{ key: 'news', label: '新闻', items: suggestions.news }] : []),
                  /* papers */ ...(suggestions.papers.length > 0 ? [{ key: 'papers', label: '论文', items: suggestions.papers }] : []),
                  /* reports */ ...(suggestions.reports.length > 0 ? [{ key: 'reports', label: '报告', items: suggestions.reports }] : []),
                ].map(section => (
                  <div key={section.key} className="mb-1 last:mb-0">
                    <p className="text-[10px] font-bold tracking-[.14em] text-[#8ea0b6] px-2 py-1">{section.label}</p>
                    {section.items.map((item: any) => (
                      <Link
                        key={item.id}
                        to={section.key === 'news' ? `/items/${item.id}` : section.key === 'papers' ? `/papers/${item.id}` : `/reports/${item.id}`}
                        onClick={() => setShowDropdown(false)}
                        className="block px-2 py-1.5 rounded-lg text-xs transition-colors truncate"
                        style={{
                          color: 'var(--ink)',
                          backgroundColor: 'transparent',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--dropdown-hover)' }}
                        onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
                      >
                        {item.title}
                      </Link>
                    ))}
                  </div>
                ))}
                <div className="border-t border-[var(--line)] mt-1 pt-1">
                  <Link
                    to={`/search?q=${encodeURIComponent(query.trim())}`}
                    onClick={() => setShowDropdown(false)}
                    className="block px-2 py-1.5 text-xs font-medium text-[var(--accent)] hover:opacity-80 transition-colors"
                  >
                    查看全部 {suggestions.total} 条结果
                  </Link>
                </div>
              </div>
            )}
          </div>

            <div className="relative group py-2 shrink-0">
              <button
                type="button"
                className="flex items-center gap-1.5 h-[38px] sm:h-auto px-3 py-2 min-h-[44px] rounded-xl text-sm font-medium transition-colors whitespace-nowrap"
                style={{
                  color: 'var(--nav-text)',
                }}
                onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.backgroundColor = 'var(--dropdown-hover)' }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--nav-text)'; e.currentTarget.style.backgroundColor = 'transparent' }}
              >
                <Settings className="w-4 h-4 shrink-0" strokeWidth={1.8} />
                设置
              </button>
              {/* Plain opaque bg (not .glass) — Safari mis-renders a backdrop-filter
                  element nested inside the header's own backdrop-blur ancestor. */}
              <div className="hidden group-hover:block absolute right-0 top-[44px] z-30 w-[200px] p-2 rounded-2xl border border-[var(--line)] transition-colors"
                style={{
                  backgroundColor: 'var(--dropdown-bg)',
                  boxShadow: 'var(--dropdown-shadow)',
                }}
              >
                {/* Theme: default vs organic */}
                <div className="px-2.5 py-2.5 border-b border-[var(--line)] mb-2">
                  <p className="text-sm mb-2 transition-colors" style={{ color: 'var(--settings-text)' }}>主题</p>
                  <div className="flex flex-col gap-1">
                    {THEME_PRESETS.map(p => (
                      <button
                        key={p.value}
                        type="button"
                        onClick={() => chooseTheme(p.value)}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors"
                        style={{
                          color: theme === p.value ? 'var(--accent)' : 'var(--settings-text)',
                          backgroundColor: theme === p.value ? 'var(--settings-hover-bg)' : 'transparent',
                        }}
                      >
                        <span className="w-3.5 h-3.5 rounded-full border flex items-center justify-center shrink-0"
                          style={{
                            borderColor: theme === p.value ? (p.value === 'organic' ? '#C66B3D' : 'var(--accent)') : 'var(--line)',
                            backgroundColor: theme === p.value ? (p.value === 'organic' ? '#C66B3D' : 'var(--accent)') : 'transparent',
                          }}
                        >
                          {theme === p.value && <Check className="w-2 h-2 text-white" strokeWidth={4} />}
                        </span>
                        {p.name}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Skin: pick the accent colour */}
                <div className="px-2.5 py-1.5">
                  <p className="text-sm mb-2 transition-colors" style={{ color: 'var(--settings-text)' }}>强调色</p>
                  <div className="flex items-center gap-2">
                    {getAccentPresets(theme).map(preset => (
                      <button
                        key={preset.value}
                        type="button"
                        onClick={() => chooseAccent(preset.value)}
                        title={preset.name}
                        aria-label={preset.name}
                        className="w-5 h-5 rounded-full border border-black/10 flex items-center justify-center shrink-0"
                        style={{ backgroundColor: preset.value }}
                      >
                        {accent === preset.value && <Check className="w-3 h-3 text-white" strokeWidth={3} />}
                      </button>
                    ))}
                  </div>
                </div>
                <Link
                  to="/preferences"
                  className="flex items-center justify-between px-2.5 py-2.5 rounded-xl text-sm transition-colors mt-1"
                  style={{
                    color: 'var(--settings-text)',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.backgroundColor = 'var(--settings-hover-bg)' }}
                  onMouseLeave={e => { e.currentTarget.style.color = 'var(--settings-text)'; e.currentTarget.style.backgroundColor = 'transparent' }}
                >
                  偏好设置 <span>›</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="w-[min(1280px,calc(100%-48px))] mx-auto py-8">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--line)] mt-12">
        <div className="w-[min(1280px,calc(100%-48px))] mx-auto py-6 text-center text-sm text-[var(--muted)]">
          关注科技前沿，理解正在发生的未来
        </div>
      </footer>
    </div>
  )
}
