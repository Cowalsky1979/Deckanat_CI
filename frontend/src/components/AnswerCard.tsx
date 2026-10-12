import { AlertTriangle, CheckCircle2, HelpCircle, Info } from 'lucide-react'
import { api, type FieldValue, type QA } from '../api'
import SourceChip from './SourceChip'

interface Props {
  qa: QA
  fields: Record<string, FieldValue>
  docId: string
  onSelect: (key: string) => void
  highlighted?: boolean
}

function tone(qa: QA) {
  if (!qa.answerable) return { cls: 'border-ink-300 bg-ink-50', icon: <HelpCircle className="text-ink-500" size={20} />, title: 'Нет информации' }
  if (qa.value === 'document_ok') return { cls: 'border-green-300 bg-green-50', icon: <CheckCircle2 className="text-green-600" size={20} />, title: 'Документ содержит обязательные сведения' }
  if (qa.value === 'missing_fields') return { cls: 'border-amber-300 bg-amber-50', icon: <AlertTriangle className="text-amber-600" size={20} />, title: 'Не хватает обязательных сведений' }
  return { cls: 'border-brand-200 bg-brand-50', icon: <Info className="text-brand-600" size={20} />, title: 'Ответ' }
}

export default function AnswerCard({ qa, fields, docId, onSelect, highlighted }: Props) {
  const t = tone(qa)
  const showCrop = qa.field_key && fields[qa.field_key]?.bbox
  return (
    <div className={`rounded-2xl border p-4 ${t.cls} ${highlighted ? 'ring-2 ring-brand-300' : ''}`}>
      <div className="text-xs text-ink-500 mb-1">Вопрос: {qa.question}</div>
      <div className="flex items-start gap-2">
        {t.icon}
        <div className="flex-1">
          <div className="font-semibold text-sm">{t.title}</div>
          <div className="text-sm text-ink-800 mt-1">{qa.answer}</div>
          {qa.answerable && qa.value && !['document_ok', 'missing_fields'].includes(qa.value) && (
            <div className="text-xs text-ink-500 mt-1">value: <code>{qa.value}</code></div>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {qa.sources.length === 0 ? (
              <span className="text-xs text-ink-500">источники: нет (ответ не найден в документе и Положении)</span>
            ) : (
              qa.sources.map((s) => <SourceChip key={s} source={s} fields={fields} onSelect={onSelect} />)
            )}
          </div>
          {showCrop && (
            <img src={api.cropUrl(docId, qa.field_key)} alt="фрагмент снимка" className="mt-3 max-h-40 rounded-lg border border-ink-200 bg-surface" />
          )}
        </div>
      </div>
    </div>
  )
}
