import { AlertTriangle, CheckCircle2, Loader2, XCircle } from 'lucide-react'
import type { DocListItem } from '../api'

// итог предварительной проверки одной строкой для списков кабинета
export default function ValidationChip({ doc }: { doc: Pick<DocListItem, 'status' | 'validation_status' | 'missing_count'> }) {
  if (doc.status === 'processing') return <span className="chip border-ink-300 text-ink-600"><Loader2 size={12} className="animate-spin" /> Обрабатывается</span>
  if (doc.status === 'error') return <span className="chip border-red-300 bg-red-50 text-red-800"><XCircle size={12} /> Ошибка обработки</span>
  if (doc.validation_status === 'document_ok') return <span className="chip border-green-300 bg-green-50 text-green-800"><CheckCircle2 size={12} /> Все сведения на месте</span>
  return (
    <span className="chip border-amber-300 bg-amber-50 text-amber-800">
      <AlertTriangle size={12} /> Не хватает {doc.missing_count === 1 ? 'поля' : 'полей'}: {doc.missing_count}
    </span>
  )
}
