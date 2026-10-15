import { CheckCircle2, Clock, Pencil, Send, XCircle } from 'lucide-react'
import type { Review } from '../api'

const STYLES = {
  pending: ['На рассмотрении', 'border-amber-300 bg-amber-50 text-amber-800', Clock],
  accepted: ['Принято', 'border-green-300 bg-green-50 text-green-800', CheckCircle2],
  rejected: ['Отклонено', 'border-red-300 bg-red-50 text-red-800', XCircle],
  needs_fix: ['Нужно исправить', 'border-orange-300 bg-orange-50 text-orange-800', Pencil],
} as const

export default function ReviewStatusChip({ review }: { review: Review | null }) {
  if (!review) {
    return <span className="chip border-ink-300 text-ink-600"><Send size={12} /> Не отправлено</span>
  }
  const [title, cls, Icon] = STYLES[review.status]
  return <span className={`chip ${cls}`}><Icon size={12} /> {title}</span>
}
