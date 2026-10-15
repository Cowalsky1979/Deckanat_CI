import { useState } from 'react'
import { Check, Loader2, Pencil, RotateCcw, X } from 'lucide-react'
import { MISSING_REASON_TEXT, type FieldValue } from '../api'

interface Props {
  fields: Record<string, FieldValue>
  highlight: string | null
  onSelect: (key: string | null) => void
  docId: string
  // ручная правка текстовых полей (студент, пока документ не на рассмотрении)
  editable?: boolean
  onEdit?: (key: string, value: string) => Promise<unknown>
}

// подсказка к причине «не найдено»: отличаем пустое поле в документе от нераспознанной метки
function MissingHint({ f }: { f: FieldValue }) {
  if (!f.missing_reason) return null
  const bad = f.missing_reason === 'label_not_found' || f.missing_reason === 'anchor_not_found'
  return (
    <div className={`mt-1 text-[11px] ${bad ? 'text-red-700' : 'text-ink-500'}`}>
      {MISSING_REASON_TEXT[f.missing_reason]}
      {bad && ' — проверьте снимок или переснимите документ'}
    </div>
  )
}

export default function FieldsTable({ fields, highlight, onSelect, editable, onEdit }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const save = async (key: string, value: string) => {
    if (!onEdit) return
    setSaving(key)
    setError(null)
    try {
      await onEdit(key, value)
      setEditing(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <div>
      {editable && (
        <div className="mb-3 text-xs text-ink-500">
          Если OCR ошибся, исправьте значение кнопкой <Pencil size={11} className="inline" />. Исходное распознанное значение сохранится
          и будет видно деканату; подпись и печать вручную отметить нельзя (п. 2.3).
        </div>
      )}
      <table className="w-full text-sm break-words">
        <thead className="text-xs text-ink-500">
          <tr>
            <th className="text-left font-medium pb-2">Поле</th>
            <th className="text-left font-medium pb-2">Значение</th>
            <th className="text-right font-medium pb-2">OCR</th>
            {editable && <th className="pb-2" />}
          </tr>
        </thead>
        <tbody>
          {Object.values(fields).map((f) => {
            const active = highlight === f.key
            const isEditing = editing === f.key
            const canEdit = !!editable && f.kind === 'text'
            return (
              <tr
                key={f.key}
                onClick={() => !isEditing && onSelect(active ? null : f.key)}
                className={`cursor-pointer border-t border-ink-100 ${active ? 'bg-brand-50' : 'hover:bg-ink-50'}`}
              >
                <td className="py-2 pr-2 align-top">
                  <div className="font-medium">{f.label}</div>
                  <div className="text-[11px] text-ink-400">{f.key}</div>
                </td>
                <td className="py-2 pr-2 align-top min-w-0 [overflow-wrap:anywhere]">
                  {isEditing ? (
                    <form
                      className="flex flex-wrap items-center gap-1.5"
                      onClick={(e) => e.stopPropagation()}
                      onSubmit={(e) => {
                        e.preventDefault()
                        void save(f.key, draft)
                      }}
                    >
                      <input
                        className="input !py-1.5 !w-auto min-w-[200px] text-sm"
                        value={draft}
                        autoFocus
                        placeholder={f.label.toLowerCase().includes('дата') || f.key.endsWith('_date') || f.key.endsWith('_start') || f.key.endsWith('_end') ? 'ДД.ММ.ГГГГ' : 'значение'}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => e.key === 'Escape' && setEditing(null)}
                      />
                      <button type="submit" className="btn-primary !px-2.5 !py-1.5 text-xs" disabled={saving === f.key || !draft.trim()}>
                        {saving === f.key ? <Loader2 className="animate-spin" size={12} /> : <Check size={12} />} Сохранить
                      </button>
                      <button type="button" className="btn-ghost !px-2.5 !py-1.5 text-xs" onClick={() => setEditing(null)}>
                        <X size={12} /> Отмена
                      </button>
                      {error && <div className="w-full text-xs text-red-700">{error}</div>}
                    </form>
                  ) : f.kind === 'mark' ? (
                    <>
                      {f.found ? (
                        <span className="chip border-blue-300 bg-blue-50 text-blue-800"><Check size={12} /> есть</span>
                      ) : (
                        <span className="chip border-red-300 bg-red-50 text-red-800"><X size={12} /> отсутствует</span>
                      )}
                      {!f.found && <MissingHint f={f} />}
                    </>
                  ) : f.found ? (
                    <span>
                      {String(f.value)}
                      {f.source === 'manual' ? (
                        <span className="chip ml-1 border-orange-300 bg-orange-50 text-orange-800" title="Значение введено вручную">
                          <Pencil size={10} /> исправлено вручную
                        </span>
                      ) : (
                        f.confidence > 0 && f.confidence < 0.75 && (
                          <span className="chip ml-1 border-amber-300 bg-amber-50 text-amber-800" title="Низкая уверенность OCR — проверьте значение">? низкая уверенность</span>
                        )
                      )}
                    </span>
                  ) : (
                    <>
                      <span className="chip border-ink-300 bg-ink-100 text-ink-600">не найдено</span>
                      <MissingHint f={f} />
                    </>
                  )}
                  {!isEditing && f.kind === 'text' && f.source === 'manual' && (
                    <div className="text-[11px] text-ink-400">OCR: {f.ocr_value || 'не найдено'}</div>
                  )}
                  {!isEditing && f.kind === 'text' && f.source !== 'manual' && f.raw && f.raw !== f.value && f.found && (
                    <div className="text-[11px] text-ink-400">OCR: {f.raw}</div>
                  )}
                </td>
                <td className="py-2 text-right align-top text-xs text-ink-500">{f.confidence ? `${(f.confidence * 100).toFixed(0)}%` : '—'}</td>
                {editable && (
                  <td className="py-2 pl-2 text-right align-top whitespace-nowrap">
                    {canEdit && !isEditing && (
                      <span className="inline-flex gap-1">
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-900"
                          title="Исправить значение"
                          aria-label={`Исправить поле ${f.label}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            setError(null)
                            setDraft(f.found && f.kind === 'text' ? String(f.value) : '')
                            setEditing(f.key)
                          }}
                        >
                          <Pencil size={14} />
                        </button>
                        {f.source === 'manual' && (
                          <button
                            type="button"
                            className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-900"
                            title="Вернуть значение OCR"
                            aria-label={`Вернуть OCR для поля ${f.label}`}
                            disabled={saving === f.key}
                            onClick={(e) => {
                              e.stopPropagation()
                              void save(f.key, '')
                            }}
                          >
                            {saving === f.key ? <Loader2 className="animate-spin" size={14} /> : <RotateCcw size={14} />}
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
