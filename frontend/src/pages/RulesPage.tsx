import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useSearchParams } from 'react-router-dom'
import { Search } from 'lucide-react'
import { api } from '../api'

export default function RulesPage() {
  const rules = useQuery({ queryKey: ['rules'], queryFn: api.rules, staleTime: Infinity })
  const { hash } = useLocation()
  const [params] = useSearchParams()
  const [q, setQ] = useState('')
  useEffect(() => {
    if (hash && rules.data) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [hash, rules.data])
  // поиск по тексту и номеру пункта
  const sections = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!rules.data) return []
    if (!needle) return rules.data.sections
    return rules.data.sections
      .map((s) => ({ ...s, rules: s.rules.filter((r) => r.id.startsWith(needle) || r.text.toLowerCase().includes(needle)) }))
      .filter((s) => s.rules.length)
  }, [rules.data, q])
  if (!rules.data) return <div className="text-ink-500">Загрузка…</div>
  const active = hash.replace('#', '')
  return (
    <div className="max-w-4xl">
      <h1 className="section-title">{rules.data.title}</h1>
      <p className="mt-3 text-[17px] text-ink-600">Единственная база правил сервиса. Ответы ссылаются на пункты этого Положения.</p>
      <label className="mt-7 relative block">
        <Search size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-400" />
        <input
          className="input !pl-12 !py-3.5"
          placeholder="Поиск по Положению: «печать», «3.4», «академический отпуск»…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus={params.get('search') === '1'}
        />
      </label>
      <div className="mt-7 card p-6 sm:p-8">
        {sections.length === 0 && <div className="text-ink-500">Ничего не найдено.</div>}
        {sections.map((s) => (
          <section key={s.id} className="mb-7 last:mb-0">
            <h2 className="font-semibold text-xl text-ink-900 mb-3">{s.id}. {s.title}</h2>
            <ol className="space-y-1">
              {s.rules.map((r) => {
                const id = `rule-${r.id.replace('.', '-')}`
                return (
                  <li key={r.id} id={id} className={`rounded-xl px-3 py-2 text-[15px] leading-6 ${active === id ? 'bg-brand-50 ring-1 ring-brand-300' : ''}`}>
                    <b className="mr-1">{r.id}.</b>{r.text}
                  </li>
                )
              })}
            </ol>
          </section>
        ))}
      </div>
    </div>
  )
}
