import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, Crosshair } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type FieldValue } from '../api'

interface Props {
  source: string
  fields: Record<string, FieldValue>
  onSelect: (key: string) => void
}

// field:key подсвечивает поле на снимке, rule:X.Y показывает текст пункта
export default function SourceChip({ source, fields, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const rules = useQuery({ queryKey: ['rules'], queryFn: api.rules, staleTime: Infinity })

  if (source.startsWith('field:')) {
    const key = source.slice(6)
    const f = fields[key]
    return (
      <button type="button" className="chip border-green-300 bg-green-50 text-green-900 hover:bg-green-100" onClick={() => onSelect(key)} title="Показать на снимке">
        <Crosshair size={12} /> поле «{f?.label ?? key}»
      </button>
    )
  }
  const rid = source.replace('rule:', '')
  const text = rules.data?.sections.flatMap((s) => s.rules).find((r) => r.id === rid)?.text
  return (
    <span className="relative inline-block">
      <button type="button" className="chip border-sun-400 bg-sun-50 text-sun-900 hover:bg-sun-100" onClick={() => setOpen((o) => !o)}>
        <BookOpen size={12} /> п. {rid} Положения
      </button>
      {open && (
        <div className="absolute z-30 left-0 top-full mt-1 w-80 max-w-[85vw] rounded-xl border border-ink-200 bg-surface p-3 text-xs shadow-lg">
          <div className="font-semibold mb-1">Пункт {rid}</div>
          <div className="text-ink-700">{text ?? 'Загрузка…'}</div>
          <Link to={`/rules#rule-${rid.replace('.', '-')}`} className="mt-2 inline-block text-brand-700 underline">
            Открыть в Положении
          </Link>
        </div>
      )}
    </span>
  )
}
