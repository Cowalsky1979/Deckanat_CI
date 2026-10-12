import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Loader2, MessageSquareText, Upload } from 'lucide-react'
import { api } from '../../api'
import { fmtDate } from '../../format'
import type { Profile } from '../../profile'
import ReviewStatusChip from '../../components/ReviewStatusChip'
import ValidationChip from '../../components/ValidationChip'

export default function StudentCabinet({ profile }: { profile: Profile }) {
  const docs = useQuery({ queryKey: ['documents', 'student'], queryFn: () => api.listDocuments(), refetchInterval: 15000 })

  return (
    <div className="max-w-4xl">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="section-title">Мои документы</h1>
          <p className="mt-2 text-ink-600">{profile.name} · история проверок и решения деканата</p>
        </div>
        <Link to="/#upload" className="btn-primary"><Upload size={16} /> Загрузить документ</Link>
      </div>

      <div className="mt-7 space-y-3">
        {docs.isLoading && <div className="flex items-center gap-2 text-ink-600"><Loader2 className="animate-spin" /> Загрузка…</div>}
        {docs.error && <div className="card p-5 text-red-700">{(docs.error as Error).message}</div>}
        {docs.data?.length === 0 && (
          <div className="card p-8 text-center">
            <div className="font-semibold text-ink-900">Документов пока нет</div>
            <div className="mt-1 text-sm text-ink-600">Загрузите справку или заявление: ИИ проверит его, а потом можно отправить в деканат.</div>
            <Link to="/#upload" className="btn-primary mt-4"><Upload size={16} /> Загрузить документ</Link>
          </div>
        )}
        {docs.data?.map((d) => {
          const r = d.review
          const decided = r && r.status !== 'pending'
          return (
            <Link key={d.id} to={`/d/${d.id}`} className="card block p-4 sm:p-5 hover:bg-ink-100 transition">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink-900">{d.doc_type_title || 'Документ'}</div>
                  <div className="text-xs text-ink-500 truncate">{d.original_name} · {fmtDate(d.created_at)}{d.source === 'telegram' && ' · из Telegram'}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <ValidationChip doc={d} />
                    <ReviewStatusChip review={r} />
                  </div>
                  {d.last_answer && (
                    <div className="mt-2 flex items-start gap-1.5 text-sm text-ink-600">
                      <MessageSquareText size={14} className="mt-0.5 shrink-0 text-brand-500" />
                      <span className="line-clamp-2">{d.last_answer}</span>
                    </div>
                  )}
                  {decided && (
                    <div className={`mt-2 rounded-xl border p-2.5 text-sm ${r.status === 'accepted' ? 'border-green-300 bg-green-50 text-green-800' : 'border-red-300 bg-red-50 text-red-800'}`}>
                      <span className="font-semibold">Ответ деканата: </span>
                      {r.comment || (r.status === 'accepted' ? 'документ принят' : 'документ отклонён')}
                      <div className="text-xs opacity-70 mt-0.5">{r.reviewer?.name ?? 'Деканат'} · {fmtDate(r.decided_at)}</div>
                    </div>
                  )}
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
