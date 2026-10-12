// Telegram Mini App (telegram-web-app.js подключён в index.html)
// вне телеграма функции ничего не делают
import type { Theme } from './theme'

interface TgWebApp {
  ready: () => void
  expand: () => void
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  initDataUnsafe?: { user?: { id: number; first_name?: string } }
  setHeaderColor?: (c: string) => void
  setBackgroundColor?: (c: string) => void
  BackButton?: { show: () => void; hide: () => void; onClick: (cb: () => void) => void; offClick: (cb: () => void) => void }
  onEvent?: (ev: string, cb: () => void) => void
  isExpanded?: boolean
  version?: string
  openLink?: (url: string, opts?: { try_instant_view?: boolean }) => void
  downloadFile?: (params: { url: string; file_name: string }, cb?: (accepted: boolean) => void) => void
  isVersionAtLeast?: (v: string) => boolean
}

// в Telegram <a download> не работает, поэтому downloadFile (Bot API 8.0+) или openLink
export function downloadFile(url: string, fileName: string): boolean {
  const w = tg()
  if (!w) return false
  const abs = new URL(url, window.location.origin).toString()
  try {
    if (w.downloadFile && (!w.isVersionAtLeast || w.isVersionAtLeast('8.0'))) {
      w.downloadFile({ url: abs, file_name: fileName })
      return true
    }
    w.openLink?.(abs)
    return true
  } catch {
    return false
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TgWebApp }
  }
}

export function tg(): TgWebApp | null {
  const w = window.Telegram?.WebApp
  // объект есть и вне Telegram, поэтому смотрим на initData и платформу
  return w && (w.initDataUnsafe?.user || Object.keys(w.themeParams || {}).length > 0) ? w : null
}

export const inTelegram = () => tg() !== null

export function tgTheme(): Theme | null {
  const w = tg()
  return w ? (w.colorScheme === 'dark' ? 'dark' : 'light') : null
}

export function tgInit(onThemeChange: (t: Theme) => void) {
  const w = tg()
  if (!w) return
  w.ready()
  w.expand()
  document.documentElement.dataset.tg = '1'
  w.onEvent?.('themeChanged', () => onThemeChange(w.colorScheme === 'dark' ? 'dark' : 'light'))
}

export function tgSyncChrome(theme: Theme) {
  const w = tg()
  if (!w) return
  try {
    w.setHeaderColor?.(theme === 'dark' ? '#1b1e24' : '#ffffff')
    w.setBackgroundColor?.(theme === 'dark' ? '#121417' : '#f8f9fc')
  } catch {
    /* старые клиенты */
  }
}
