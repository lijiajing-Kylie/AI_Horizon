// The whole site drives its interactive/highlight color off a single CSS
// custom property (--accent, defined in index.css). This module lets the
// "皮肤" (skin) picker in Layout.tsx change that variable at runtime and
// remember the choice across reloads.
//
// Additionally, the site supports full theme switching (default ↔ organic)
// which swaps the entire set of colour/layout tokens.

export interface AccentPreset {
  name: string
  value: string
}

export const ACCENT_PRESETS: AccentPreset[] = [
  { name: '雾紫', value: '#B197C4' },
  { name: '天蓝', value: '#83CBE2' },
  { name: '薄荷绿', value: '#A0C497' },
  { name: '暖金', value: '#E2CA83' },
  { name: '珊瑚粉', value: '#D98A85' },
]

export const DEFAULT_ACCENT = ACCENT_PRESETS[0].value

/** Five earth-toned accent colours that pair with the Organic theme. */
export const ORGANIC_ACCENT_PRESETS: AccentPreset[] = [
  { name: '陶土红', value: '#C66B3D' },
  { name: '琥珀金', value: '#D4944A' },
  { name: '苔藓绿', value: '#6B8F5E' },
  { name: '赤陶橙', value: '#C2824A' },
  { name: '深砖红', value: '#A85D4A' },
]

export const DEFAULT_ORGANIC_ACCENT = ORGANIC_ACCENT_PRESETS[0].value

/** Return the accent colour presets appropriate for the active theme. */
export function getAccentPresets(theme: string): AccentPreset[] {
  return theme === 'organic' ? ORGANIC_ACCENT_PRESETS : ACCENT_PRESETS
}

/** Return the default accent colour for the given theme. */
export function getDefaultAccent(theme: string): string {
  return theme === 'organic' ? DEFAULT_ORGANIC_ACCENT : DEFAULT_ACCENT
}

const ACCENT_STORAGE_KEY = 'horizon-accent'

export function getStoredAccent(): string | null {
  try {
    return localStorage.getItem(ACCENT_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAccent(value: string) {
  document.documentElement.style.setProperty('--accent', value)
  try {
    localStorage.setItem(ACCENT_STORAGE_KEY, value)
  } catch {
    // localStorage unavailable (e.g. private browsing) — color still applies for this session
  }
}

/** Re-apply a previously chosen accent color. Call once, before first paint. */
export function applyStoredAccent() {
  const stored = getStoredAccent()
  if (stored) document.documentElement.style.setProperty('--accent', stored)
}

// ── full theme switching ──────────────────────────────────────────────────

export interface ThemePreset {
  name: string
  /** Value persisted in localStorage and set as `data-theme` on <html>. */
  value: string
  /** Short label shown in the settings dropdown. */
  label: string
}

export const THEME_PRESETS: ThemePreset[] = [
  { name: '默认', value: 'default', label: '默认主题' },
  {
    name: '有机',
    value: 'organic',
    label: '有机主题 — 大地色 · 衬线体 · 颗粒纹理',
  },
]

export const DEFAULT_THEME = THEME_PRESETS[0].value

const THEME_STORAGE_KEY = 'horizon-theme'

export function getStoredTheme(): string | null {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setTheme(value: string) {
  document.documentElement.setAttribute('data-theme', value)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, value)
  } catch {
    // localStorage unavailable — still applies for this session
  }
}

/** Re-apply a previously chosen theme. Call once, before first paint. */
export function applyStoredTheme() {
  const stored = getStoredTheme()
  if (stored) document.documentElement.setAttribute('data-theme', stored)
}
