import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bot, ChevronRight, Download, Inbox, Loader2 } from 'lucide-react'
import { api } from '../../api'
import { fmtDate } from '../../format'
import type { Profile } from '../../profile'
import ReviewStatusChip from '../../components/ReviewStatusChip'
import ValidationChip from '../../components/ValidationChip'

type Tab = 'pending' | 'decided'

export default function DeanCabinet({ profile }: { profile: Profile }) {
  const [tab, setTab] = useState<Tab>('pending')
  const summary = useQuery({ queryKey: ['reviews', 'summary'], queryFn: api.reviewSummary, refetchInterval: 15000 })
  const docs = useQuery({
    queryKey: ['documents', 'dean', tab],
    queryFn: () => api.listDocuments({ review: tab }),
    refetchInterval: 10000,
  })

  return (
    <div className="max-w-4xl">
      <h1 className="section-title">Кабинет деканата</h1>
      <p className="mt-2 text-ink-600">
        {profile.name} · заявок на рассмотрении: {summary.data?.pending ?? '…'}
        {summary.data && summary.data.unseen > 0 && <span className="ml-2 chip border-brand-500 bg-brand-500 text-white">новых: {summary.data.unseen}</span>}
      </p>

      <div className="mt-6 flex flex-wrap items-end justify-between gap-3 border-b border-ink-200">
        <div role="tablist" className="flex gap-6">
          {([['pending', 'Входящие'], ['decided', 'Обработанные']] as [Tab, string][]).map(([k, t]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className="tab-upper">
              {t}{k === 'pending' && summary.data ? ` (${summary.data.pending})` : ''}
            </button>
          ))}
        </div>
        <a
          href={api.exportCsvUrl('all')}
          download="reviews.csv"
          className="mb-2 inline-flex items-center gap-1.5 text-sm text-brand-700 hover:underline"
          title="Все заявки: студент, тип, проверка ИИ, решение, комментарий (CSV для Excel)"
        >
          <Download size={14} /> Скачать журнал заявок (CSV)
        </a>
      </div>

      <div className="mt-5 space-y-3">
        {docs.isLoading && <div className="flex items-center gap-2 text-ink-600"><Loader2 className="animate-spin" /> Загрузка…</div>}
        {docs.error && <div className="card p-5 text-red-700">{(docs.error as Error).message}</div>}
        {docs.data?.length === 0 && (
          <div className="card p-8 text-center text-ink-600">
            <Inbox className="mx-auto text-ink-400" size={32} />
            <div className="mt-2">{tab === 'pending' ? 'Новых заявок нет' : 'Обработанных заявок пока нет'}</div>
          </div>
        )}
        {docs.data?.map((d) => {
          const r = d.review!
          const fresh = r.status === 'pending' && !r.seen_by_dean
          return (
            <Link key={d.id} to={`/d/${d.id}`} className={`card block p-4 sm:p-5 hover:bg-ink-100 transition ${fresh ? 'ring-2 ring-brand-300' : ''}`}>
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {fresh && <span className="h-2.5 w-2.5 rounded-full bg-brand-500" title="Новая заявка" />}
                    <span className="font-semibold text-ink-900">{d.owner?.name ?? 'Студент'}</span>
                    <span className="text-xs text-ink-500">· {d.doc_type_title} · {fmtDate(r.submitted_at)}</span>
                    {d.parent && <span className="chip border-brand-300 bg-brand-50 text-brand-700" title="Студент прислал исправленную версию после замечания">исправленная версия</span>}
                    {d.ai_summary && d.ai_summary.manual_fields.length > 0 && (
                      <span className="chip border-orange-300 bg-orange-50 text-orange-800" title="Часть полей студент ввёл вручную">есть ручные правки</span>
                    )}
                  </div>
                  {d.ai_summary && (
                    <div className="mt-1.5 flex items-start gap-1.5 text-sm text-ink-800">
                      <Bot size={14} className="mt-0.5 shrink-0 text-brand-500" />
                      <span>{d.ai_summary.headline}</span>
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <ValidationChip doc={d} />
                    {tab === 'decided' && <ReviewStatusChip review={r} />}
                  </div>
                  {tab === 'decided' && r.comment && <div className="mt-2 text-sm text-ink-600 line-clamp-2">{r.comment}</div>}
                </div>
                <ChevronRight className="shrink-0 text-ink-400 mt-1" />
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
