import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { FieldValue, Validation } from '../api'
import SourceChip from './SourceChip'

interface Props {
  validation: Validation
  fields: Record<string, FieldValue>
  onSelect: (key: string) => void
}

export default function ValidationCard({ validation, fields, onSelect }: Props) {
  const ok = validation.status === 'document_ok'
  return (
    <div className={`rounded-3xl p-5 ${ok ? 'bg-green-50' : 'bg-amber-50'}`}>
      <div className="flex items-start gap-2">
        {ok ? <CheckCircle2 className="text-green-600 shrink-0" /> : <AlertTriangle className="text-amber-600 shrink-0" />}
        <div className="flex-1">
          <div className="font-semibold">{ok ? 'Предварительная проверка: документ в порядке' : 'Предварительная проверка: не хватает сведений'}</div>
          <div className="text-sm text-ink-700 mt-1">{validation.message}</div>
          {!ok && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {validation.missing_fields.map((k) => (
                <button key={k} className="chip border-red-300 bg-red-50 text-red-900 hover:bg-red-100" onClick={() => onSelect(k)}>
                  {fields[k]?.label ?? k}
                </button>
              ))}
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
