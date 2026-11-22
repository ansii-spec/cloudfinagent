const KEY = 'ec2opt.theme'
export type Theme = 'light' | 'dark'

export function initialTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY)
    if (t === 'light' || t === 'dark') return t
  } catch { /* ignore */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
  try { localStorage.setItem(KEY, t) } catch { /* ignore */ }
}
