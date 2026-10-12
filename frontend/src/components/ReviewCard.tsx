import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, CheckCircle2, Loader2, Pencil, Send, UserRound, XCircle } from 'lucide-react'
import { api, type Doc } from '../api'
import { fmtDate } from '../format'
import { useProfile } from '../profile'
import ReviewStatusChip from './ReviewStatusChip'

// Карточка заявки на странице документа: студент отправляет в деканат и видит решение,
// деканат видит анализ ИИ и принимает или отклоняет.
export default function ReviewCard({ doc }: { doc: Doc }) {
  const profile = useProfile()
  if (!profile) {
    return (
      <div className="card p-5 text-sm text-ink-600">
        Чтобы отправить документ в деканат и следить за решением, выберите роль в{' '}
        <Link to="/cabinet" className="text-brand-700 font-medium hover:underline">кабинете</Link>.
      </div>
    )
  }
  return profile.role === 'dean' ? <DeanPanel doc={doc} /> : <StudentPanel doc={doc} />
}

function DecisionBox({ doc }: { doc: Doc }) {
  const r = doc.review!
  const accepted = r.status === 'accepted'
  return (
    <div className={`mt-3 rounded-xl border p-3 text-sm ${accepted ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'}`}>
      <div className={`flex items-center gap-2 font-semibold ${accepted ? 'text-green-800' : 'text-red-800'}`}>
        {accepted ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
        {accepted ? 'Документ принят' : 'Документ отклонён'}
      </div>
      {r.comment && <div className={`mt-1 ${accepted ? 'text-green-800/90' : 'text-red-800/90'}`}>{r.comment}</div>}
      <div className="mt-1 text-xs text-ink-500">
        {r.reviewer?.name ?? 'Деканат'} · {fmtDate(r.decided_at)}
        {r.reason_source === 'ai' && ' · причина предложена ИИ'}
      </div>
    </div>
  )
}

function StudentPanel({ doc }: { doc: Doc }) {
  const qc = useQueryClient()
  const submit = useMutation({
    mutationFn: () => api.submitReview(doc.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['doc', doc.id] })
      qc.invalidateQueries({ queryKey: ['documents'] })
    },
  })
  const r = doc.review
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold">Заявка в деканат</div>
        <ReviewStatusChip review={r} />
      </div>
      {!r && (
        <>
          <div className="mt-2 text-sm text-ink-600">
            Сотрудник деканата увидит документ, результат проверки ИИ и примет решение. Ответ появится здесь и в вашем кабинете.
          </div>
          {submit.error && <div className="mt-2 text-sm text-red-700">{(submit.error as Error).message}</div>}
          <button className="btn-primary mt-3" disabled={submit.isPending} onClick={() => submit.mutate()}>
            {submit.isPending ? <Loader2 className="animate-spin" size={16} /> : <Send size={16} />} Отправить в деканат
          </button>
        </>
      )}
      {r?.status === 'pending' && (
        <div className="mt-2 text-sm text-ink-600">Отправлено {fmtDate(r.submitted_at)}. Ожидает решения сотрудника деканата.</div>
      )}
      {r && r.status !== 'pending' && <DecisionBox doc={doc} />}
    </div>
  )
}

function DeanPanel({ doc }: { doc: Doc }) {
  const qc = useQueryClient()
  const r = doc.review
  const ai = doc.ai_summary
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState<number | 'custom' | null>(null)
  const [custom, setCustom] = useState('')
  const seenSent = useRef<string | null>(null)

  const seen = useMutation({
    mutationFn: () => api.markSeen(doc.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reviews', 'summary'] }),
  })
  // открыли новую заявку: снимаем отметку «не просмотрено»
  useEffect(() => {
    if (r?.status === 'pending' && !r.seen_by_dean && seenSent.current !== doc.id) {
      seenSent.current = doc.id
      seen.mutate()
    }
  }, [doc.id, r?.status, r?.seen_by_dean, seen])

  const decide = useMutation({
    mutationFn: (body: Parameters<typeof api.decide>[1]) => api.decide(doc.id, body),
    onSuccess: (d) => {
      qc.setQueryData(['doc', doc.id], d)
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['reviews', 'summary'] })
      setEditing(false)
      setChoice(null)
      setCustom('')
    },
  })

  const reason = choice === 'custom' ? custom.trim() : choice !== null ? ai?.suggested_reasons[choice] ?? '' : ''
  const canReject = reason.length > 0

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold">Решение деканата</div>
        <ReviewStatusChip review={r} />
        {r && <span className="text-xs text-ink-500">от {doc.owner?.name ?? 'студента'} · {fmtDate(r.submitted_at)}</span>}
      </div>

      {!r && <div className="mt-2 text-sm text-ink-600">Студент не отправлял этот документ в деканат.</div>}

      {r && ai && (
        <div className="mt-3 rounded-xl bg-surface p-3 text-sm">
          <div className="flex items-center gap-2 font-semibold text-ink-900"><Bot size={16} className="text-brand-500" /> Анализ ИИ</div>
          <div className="mt-1 text-ink-800">{ai.headline}</div>
          {ai.missing.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ai.missing.map((m) => (
                <span key={m.key} className="chip border-red-300 bg-red-50 text-red-900">
                  {m.label}{m.rule && <span className="text-red-700/70">п. {m.rule}</span>}
                </span>
              ))}
            </div>
          )}
          {ai.type_mismatch && <div className="mt-2 text-amber-800">Похоже на «{ai.type_mismatch.detected_title}», а не на выбранный тип.</div>}
          {ai.low_quality && <div className="mt-1 text-red-800">Снимок низкого качества: поля могли распознаться неверно.</div>}
        </div>
      )}

      {r && r.status !== 'pending' && !editing && (
        <>
          <DecisionBox doc={doc} />
          <button className="btn-ghost mt-3 !py-2 text-sm" onClick={() => setEditing(true)}><Pencil size={14} /> Изменить решение</button>
        </>
      )}

      {r && (r.status === 'pending' || editing) && (
        <div className="mt-3">
          <div className="text-sm font-medium text-ink-900">Причина отказа</div>
          <div className="mt-2 space-y-1.5">
            {(ai?.suggested_reasons ?? []).map((text, i) => (
              <label key={i} className="flex items-start gap-2 text-sm cursor-pointer">
                <input type="radio" name="reason" className="mt-1 accent-brand-500" checked={choice === i} onChange={() => setChoice(i)} />
                <span><Bot size={12} className="inline text-brand-500 mr-1" />{text}</span>
              </label>
            ))}
            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input type="radio" name="reason" className="mt-1 accent-brand-500" checked={choice === 'custom'} onChange={() => setChoice('custom')} />
              <span><UserRound size={12} className="inline text-ink-500 mr-1" />Своя причина</span>
            </label>
          </div>
          {choice === 'custom' && (
            <textarea className="input mt-2 min-h-20 text-sm" placeholder="Что нужно исправить студенту…" value={custom} onChange={(e) => setCustom(e.target.value)} />
          )}
          {decide.error && <div className="mt-2 text-sm text-red-700">{(decide.error as Error).message}</div>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="btn-primary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ status: 'accepted', comment: choice === 'custom' ? custom.trim() : '', reason_source: '' })}
            >
              {decide.isPending ? <Loader2 className="animate-spin" size={16} /> : <CheckCircle2 size={16} />} Принять
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-[15px] font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed bg-red-600 text-white hover:bg-red-700"
              disabled={!canReject || decide.isPending}
              title={canReject ? '' : 'Выберите или напишите причину'}
              onClick={() => decide.mutate({ status: 'rejected', comment: reason, reason_source: choice === 'custom' ? 'manual' : 'ai' })}
            >
              <XCircle size={16} /> Отклонить
            </button>
            {editing && <button className="btn-ghost" onClick={() => setEditing(false)}>Отмена</button>}
          </div>
        </div>
      )}
    </div>
  )
}
