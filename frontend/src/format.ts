export function fmtDate(s: string | null | undefined): string {
  if (!s) return ''
  return new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
