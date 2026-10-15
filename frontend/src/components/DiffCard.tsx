import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, GitCompareArrows, Loader2 } from 'lucide-react'
import { api, type Doc } from '../api'
import { fmtDate } from '../format'

// Что изменилось в исправленной версии по сравнению с прежней (видят и студент, и деканат)
export default function DiffCard({ doc }: { doc: Doc }) {
  const [all, setAll] = useState(false)
  const diff = useQuery({ queryKey: ['diff', doc.id], queryFn: () => api.diff(doc.id), enabled: !!doc.parent })
  if (!doc.parent) return null
  const status = (s: string | null) =>
    s === 'document_ok' ? (
      <span className="chip border-green-300 bg-green-50 text-green-800">в порядке</span>
    ) : s === 'missing_fields' ? (
      <span className="chip border-amber-300 bg-amber-50 text-amber-800">не хватает сведений</span>
    ) : (
      <span className="chip border-ink-300 text-ink-600">—</span>
    )
  const rows = diff.data ? (all ? diff.data.rows : diff.data.rows.filter((r) => r.changed)) : []
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <GitCompareArrows size={18} className="text-brand-500" />
        <div className="font-semibold">Исправленная версия: что изменилось</div>
        <Link to={`/d/${doc.parent.id}`} className="text-xs text-brand-700 hover:underline">
          прежняя версия от {fmtDate(doc.parent.created_at)}
        </Link>
      </div>
      {doc.parent.review_comment && (
        <div className="mt-2 text-sm text-ink-700">
          <span className="font-medium">Замечание деканата: </span>
          {doc.parent.review_comment}
        </div>
      )}
      {diff.isLoading && <div className="mt-3 flex items-center gap-2 text-sm text-ink-600"><Loader2 className="animate-spin" size={14} /> Сравниваем…</div>}
      {diff.error && <div className="mt-3 text-sm text-ink-600">{(diff.error as Error).message}</div>}
      {diff.data && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            {status(diff.data.before_status)}
            <ArrowRight size={14} className="text-ink-400" />
            {status(diff.data.after_status)}
            <span className="text-xs text-ink-500">
              · изменено полей: {diff.data.changed_count}
              {diff.data.after_missing.length > 0 && ` · всё ещё не хватает: ${diff.data.after_missing.length}`}
            </span>
          </div>
          {rows.length === 0 ? (
            <div className="mt-3 text-sm text-ink-600">Значения полей не изменились.</div>
          ) : (
            <table className="mt-3 w-full text-sm">
              <thead className="text-xs text-ink-500">
                <tr><th className="text-left font-medium pb-1">Поле</th><th className="text-left font-medium pb-1">Было</th><th className="text-left font-medium pb-1">Стало</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} className={`border-t border-ink-100 ${r.changed ? '' : 'text-ink-500'}`}>
                    <td className="py-1.5 pr-2 align-top">{r.label}</td>
                    <td className={`py-1.5 pr-2 align-top [overflow-wrap:anywhere] ${r.changed ? 'line-through text-ink-500' : ''}`}>{r.before}</td>
                    <td className="py-1.5 align-top [overflow-wrap:anywhere]">
                      <span className={r.fixed ? 'text-green-800 font-medium' : ''}>{r.after}</span>
                      {r.manual && <span className="chip ml-1 border-orange-300 bg-orange-50 text-orange-800">вручную</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button type="button" className="mt-2 text-xs text-brand-700 hover:underline" onClick={() => setAll((a) => !a)}>
            {all ? 'Показать только изменения' : 'Показать все поля'}
          </button>
        </>
      )}
    </div>
  )
}
