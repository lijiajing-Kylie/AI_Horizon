// The whole site drives its interactive/highlight color off a single CSS
// custom property (--accent, defined in index.css). This module lets the
// "皮肤" (skin) picker in Layout.tsx change that variable at runtime and
// remember the choice across reloads.

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

const STORAGE_KEY = 'horizon-accent'

export function getStoredAccent(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAccent(value: string) {
  document.documentElement.style.setProperty('--accent', value)
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // localStorage unavailable (e.g. private browsing) — color still applies for this session
  }
}

/** Re-apply a previously chosen accent color. Call once, before first paint. */
export function applyStoredAccent() {
  const stored = getStoredAccent()
  if (stored) document.documentElement.style.setProperty('--accent', stored)
}
