// тема: data-theme на <html>, выбор хранится в localStorage
// по умолчанию берём prefers-color-scheme, в Telegram тему клиента
import { tgInit, tgSyncChrome, tgTheme } from './telegram'

export type Theme = 'light' | 'dark'
const KEY = 'dekanat-theme'

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* localStorage недоступен (приватный режим) */
  }
  const fromTg = tgTheme()
  if (fromTg) return fromTg
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#1b1e24' : '#50b848')
  tgSyncChrome(theme)
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* ignore */
  }
  applyTheme(theme)
}

export function initTheme() {
  applyTheme(getTheme())
  tgInit((t) => {
    try {
      if (!localStorage.getItem(KEY)) applyTheme(t)
    } catch {
      applyTheme(t)
    }
  })
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    try {
      if (!localStorage.getItem(KEY)) applyTheme(getTheme())
    } catch {
      applyTheme(getTheme())
    }
  })
}
