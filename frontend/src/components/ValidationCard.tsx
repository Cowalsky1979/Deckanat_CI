import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { MISSING_REASON_TEXT, type FieldValue, type Validation } from '../api'
import SourceChip from './SourceChip'

interface Props {
  validation: Validation
  fields: Record<string, FieldValue>
  onSelect: (key: string) => void
}

export default function ValidationCard({ validation, fields, onSelect }: Props) {
  const ok = validation.status === 'document_ok'
  const missing = validation.missing_fields.map((k) => fields[k]).filter(Boolean)
  const unreadable = missing.filter((f) => f.missing_reason === 'label_not_found' || f.missing_reason === 'anchor_not_found')
  return (
    <div className={`rounded-3xl p-5 ${ok ? 'bg-green-50' : 'bg-amber-50'}`}>
      <div className="flex items-start gap-2">
        {ok ? <CheckCircle2 className="text-green-600 shrink-0" /> : <AlertTriangle className="text-amber-600 shrink-0" />}
        <div className="flex-1">
          <div className="font-semibold">{ok ? 'Предварительная проверка: документ в порядке' : 'Предварительная проверка: не хватает сведений'}</div>
          <div className="text-sm text-ink-700 mt-1">{validation.message}</div>
          {!ok && (
            <ul className="mt-2 space-y-1">
              {validation.missing_fields.map((k) => {
                const f = fields[k]
                const reason = f?.missing_reason ? MISSING_REASON_TEXT[f.missing_reason] : ''
                return (
                  <li key={k} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
                    <button className="chip border-red-300 bg-red-50 text-red-900 hover:bg-red-100" onClick={() => onSelect(k)}>
                      {f?.label ?? k}
                    </button>
                    {reason && <span className="text-xs text-ink-600">{reason}</span>}
                  </li>
                )
              })}
            </ul>
          )}
          {unreadable.length > 0 && (
            <div className="mt-2 text-xs text-red-800">
              Часть меток не распознана на снимке: возможно, дело в качестве фото, а не в документе. Переснимите документ
              ближе и ровно или загрузите скан, а если значение в документе есть, исправьте его в карточке полей.
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {validation.sources.map((s) => <SourceChip key={s} source={s} fields={fields} onSelect={onSelect} />)}
          </div>
          <div className="mt-2 text-xs text-ink-500">Окончательное решение принимает сотрудник деканата (п. 1.3).</div>
        </div>
      </div>
    </div>
  )
}
