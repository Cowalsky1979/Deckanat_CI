// тема: data-theme на <html>, выбор хранится в localStorage, по умолчанию prefers-color-scheme
export type Theme = 'light' | 'dark'
const KEY = 'dekanat-theme'

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* localStorage недоступен (приватный режим) */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#1b1e24' : '#50b848')
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
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    try {
      if (!localStorage.getItem(KEY)) applyTheme(getTheme())
    } catch {
      applyTheme(getTheme())
    }
  })
}
