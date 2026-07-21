import { useState, type FormEvent } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Search, Settings, Check } from 'lucide-react'
import { ACCENT_PRESETS, DEFAULT_ACCENT, getStoredAccent, setAccent } from '../utils/theme'

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
  const [accent, setAccentState] = useState(() => getStoredAccent() ?? DEFAULT_ACCENT)

  const isActive = (to: string) => (to === '/' ? pathname === '/' : pathname.startsWith(to))

  function chooseAccent(value: string) {
    setAccent(value)
    setAccentState(value)
  }

  function submitSearch(e: FormEvent) {
    e.preventDefault()
    const q = query.trim()
    navigate(q ? `/search?q=${encodeURIComponent(q)}` : '/search')
  }

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Header */}
      <header className="sticky top-0 z-20 h-[48px] bg-white/92 backdrop-blur border-b border-[var(--line)] shadow-[0_8px_28px_rgba(67,83,105,.05)]">
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
                    isActive(to) ? 'text-[var(--accent)]' : 'text-[#657186] hover:text-[var(--accent)]'
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
            <form onSubmit={submitSearch} className="flex items-center gap-2 w-[210px] focus-within:w-[260px] h-[28px] px-3 rounded-full bg-[#f7f8f9] border border-[#e7eaee] transition-all focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(131,203,226,.12)]">
              <Search className="w-4 h-4 text-[#8793a3] shrink-0" strokeWidth={1.8} />
              <input
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="搜索标题或主题"
                aria-label="搜索标题或主题"
                className="w-full bg-transparent text-xs text-[#38465a] placeholder:text-[#9aa6b6] outline-none"
              />
            </form>

            <div className="relative group py-2 shrink-0">
              <button
                type="button"
                className="flex items-center gap-1.5 h-[38px] px-3 rounded-xl text-sm font-medium text-[#657186] hover:text-[var(--accent)] hover:bg-[#f5f7fa] transition-colors whitespace-nowrap"
              >
                <Settings className="w-4 h-4 shrink-0" strokeWidth={1.8} />
                设置
              </button>
              {/* Plain opaque bg (not .glass) — Safari mis-renders a backdrop-filter
                  element nested inside the header's own backdrop-blur ancestor. */}
              <div className="hidden group-hover:block absolute right-0 top-[44px] z-30 w-[180px] p-2 rounded-2xl bg-white border border-[var(--line)] shadow-[0_16px_42px_rgba(55,72,99,.14)]">
                {/* Skin: pick the site's single shared accent color (--accent in index.css) */}
                <div className="px-2.5 py-2.5">
                  <p className="text-sm text-[#59677c] mb-2">皮肤</p>
                  <div className="flex items-center gap-2">
                    {ACCENT_PRESETS.map(preset => (
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
                  className="flex items-center justify-between px-2.5 py-2.5 rounded-xl text-sm text-[#59677c] hover:text-[var(--accent)] hover:bg-[#edf3fa] transition-colors"
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
