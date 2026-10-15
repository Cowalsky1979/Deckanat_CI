import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Bot, CheckCircle2, FileUp, Loader2, Pencil, Send, UserRound, XCircle } from 'lucide-react'
import { api, type Decision, type Doc } from '../api'
import { fmtDate } from '../format'
import { useProfile } from '../profile'
import { revisionLink } from '../links'
import ReviewStatusChip from './ReviewStatusChip'

// Карточка заявки на странице документа: студент отправляет в деканат и видит решение,
// деканат видит анализ ИИ и принимает, отклоняет или возвращает на доработку.
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

const DECISION_STYLE = {
  accepted: { box: 'border-green-300 bg-green-50', text: 'text-green-800', title: 'Документ принят', Icon: CheckCircle2 },
  rejected: { box: 'border-red-300 bg-red-50', text: 'text-red-800', title: 'Документ отклонён', Icon: XCircle },
  needs_fix: { box: 'border-orange-300 bg-orange-50', text: 'text-orange-800', title: 'Нужно исправить и прислать снова', Icon: Pencil },
  pending: { box: 'border-amber-300 bg-amber-50', text: 'text-amber-800', title: 'На рассмотрении', Icon: Send },
} as const

function DecisionBox({ doc }: { doc: Doc }) {
  const r = doc.review!
  const s = DECISION_STYLE[r.status]
  return (
    <div className={`mt-3 rounded-xl border p-3 text-sm ${s.box}`}>
      <div className={`flex items-center gap-2 font-semibold ${s.text}`}>
        <s.Icon size={16} />
        {s.title}
      </div>
      {r.comment && <div className={`mt-1 ${s.text}/90`}>{r.comment}</div>}
      <div className="mt-1 text-xs text-ink-500">
        {r.reviewer?.name ?? 'Деканат'} · {fmtDate(r.decided_at)}
        {r.reason_source === 'ai' && ' · причина предложена ИИ'}
      </div>
    </div>
  )
}

// другие версии документа
function Versions({ doc }: { doc: Doc }) {
  if (!doc.parent && doc.revisions.length === 0) return null
  return (
    <div className="mt-3 space-y-1 text-sm text-ink-700">
      {doc.parent && (
        <div>
          Это исправленная версия документа от {fmtDate(doc.parent.created_at)}.{' '}
          <Link to={`/d/${doc.parent.id}`} className="text-brand-700 hover:underline">Открыть прежнюю версию</Link>
        </div>
      )}
      {doc.revisions.map((rv, i) => (
        <div key={rv.id}>
          Исправленная версия {doc.revisions.length > 1 ? i + 1 : ''} от {fmtDate(rv.created_at)}:{' '}
          <Link to={`/d/${rv.id}`} className="text-brand-700 hover:underline">открыть</Link>
          {rv.review_status && <> · <ReviewStatusChip review={{ status: rv.review_status } as Doc['review'] & object} /></>}
        </div>
      ))}
    </div>
  )
}

function StudentPanel({ doc }: { doc: Doc }) {
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const submit = useMutation({
    mutationFn: () => api.submitReview(doc.id),
    onSuccess: () => {
      setConfirm(false)
      qc.invalidateQueries({ queryKey: ['doc', doc.id] })
      qc.invalidateQueries({ queryKey: ['documents'] })
    },
  })
  const r = doc.review
  const result = doc.result
  const missing = result ? result.validation.missing_fields.map((k) => result.fields[k]?.label ?? k) : []
  const lowQuality = !!result?.quality?.readability?.low_quality
  const risky = missing.length > 0 || lowQuality
  const canRevise = r && (r.status === 'needs_fix' || r.status === 'rejected') && doc.revisions.length === 0

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold">Заявка в деканат</div>
        <ReviewStatusChip review={r} />
      </div>
      <Versions doc={doc} />
      {!r && (
        <>
          <div className="mt-2 text-sm text-ink-600">
            Сотрудник деканата увидит документ, результат проверки ИИ и примет решение. Ответ появится здесь, в вашем кабинете
            и в Telegram, если документ загружен через бота.
          </div>
          {submit.error && <div className="mt-2 text-sm text-red-700">{(submit.error as Error).message}</div>}
          {confirm ? (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-amber-900"><AlertTriangle size={16} /> Проверьте документ перед отправкой</div>
              {missing.length > 0 && (
                <div className="mt-1 text-amber-900/90">
                  По предварительной проверке не хватает: <b>{missing.join(', ')}</b>. Деканат, скорее всего, вернёт документ на доработку.
                </div>
              )}
              {lowQuality && <div className="mt-1 text-amber-900/90">Снимок низкого качества: поля могли распознаться неверно.</div>}
              <div className="mt-1 text-xs text-amber-900/80">
                Если значение в документе есть, а OCR его не прочитал, исправьте поле в карточке полей или переснимите документ.
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="btn-primary !py-2 text-sm" disabled={submit.isPending} onClick={() => submit.mutate()}>
                  {submit.isPending ? <Loader2 className="animate-spin" size={14} /> : <Send size={14} />} Отправить всё равно
                </button>
                <button className="btn-ghost !py-2 text-sm" onClick={() => setConfirm(false)}>Сначала исправить</button>
              </div>
            </div>
          ) : (
            <button className="btn-primary mt-3" disabled={submit.isPending} onClick={() => (risky ? setConfirm(true) : submit.mutate())}>
              {submit.isPending ? <Loader2 className="animate-spin" size={16} /> : <Send size={16} />} Отправить в деканат
            </button>
          )}
        </>
      )}
      {r?.status === 'pending' && (
        <div className="mt-2 text-sm text-ink-600">Отправлено {fmtDate(r.submitted_at)}. Ожидает решения сотрудника деканата.</div>
      )}
      {r && r.status !== 'pending' && <DecisionBox doc={doc} />}
      {canRevise && (
        <div className="mt-3">
          <Link to={revisionLink(doc)} className="btn-primary">
            <FileUp size={16} /> Загрузить исправленную версию
          </Link>
          <div className="mt-1.5 text-xs text-ink-500">Новая версия будет связана с этой заявкой и сразу уйдёт в деканат; деканат увидит, что изменилось.</div>
        </div>
      )}
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
  const canReturn = reason.length > 0
  const send = (status: Decision) =>
    decide.mutate({
      status,
      comment: status === 'accepted' ? (choice === 'custom' ? custom.trim() : '') : reason,
      reason_source: status === 'accepted' ? '' : choice === 'custom' ? 'manual' : 'ai',
    })

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold">Решение деканата</div>
        <ReviewStatusChip review={r} />
        {r && <span className="text-xs text-ink-500">от {doc.owner?.name ?? 'студента'} · {fmtDate(r.submitted_at)}</span>}
        {doc.parent && <span className="chip border-brand-300 bg-brand-50 text-brand-700">исправленная версия</span>}
      </div>
      <Versions doc={doc} />

      {!r && <div className="mt-2 text-sm text-ink-600">Студент не отправлял этот документ в деканат.</div>}

      {r && ai && (
        <div className="mt-3 rounded-xl bg-surface p-3 text-sm">
          <div className="flex items-center gap-2 font-semibold text-ink-900"><Bot size={16} className="text-brand-500" /> Анализ ИИ</div>
          <div className="mt-1 text-ink-800">{ai.headline}</div>
          {ai.missing.length > 0 && (
            <ul className="mt-2 space-y-1">
              {ai.missing.map((m) => (
                <li key={m.key} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="chip border-red-300 bg-red-50 text-red-900">
                    {m.label}{m.rule && <span className="text-red-700/70">п. {m.rule}</span>}
                  </span>
                  {m.reason_text && <span className="text-xs text-ink-600">{m.reason_text}</span>}
                </li>
              ))}
            </ul>
          )}
          {ai.manual_fields.length > 0 && (
            <div className="mt-2 rounded-lg border border-orange-300 bg-orange-50 p-2 text-orange-900">
              <div className="flex items-center gap-1.5 font-medium"><Pencil size={13} /> Студент исправил поля вручную — сверьте с оригиналом</div>
              <ul className="mt-1 space-y-0.5 text-xs">
                {ai.manual_fields.map((m) => (
                  <li key={m.key}>
                    <b>{m.label}</b>: {m.value} <span className="text-orange-900/70">(OCR: {m.ocr_value || 'не найдено'})</span>
                  </li>
                ))}
              </ul>
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
          <div className="text-sm font-medium text-ink-900">Причина возврата или отказа</div>
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
            <button className="btn-primary" disabled={decide.isPending} onClick={() => send('accepted')}>
              {decide.isPending ? <Loader2 className="animate-spin" size={16} /> : <CheckCircle2 size={16} />} Принять
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-[15px] font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed bg-orange-500 text-white hover:bg-orange-600"
              disabled={!canReturn || decide.isPending}
              title={canReturn ? 'Студент получит замечание и сможет прислать исправленную версию' : 'Выберите или напишите причину'}
              onClick={() => send('needs_fix')}
            >
              <Pencil size={16} /> Вернуть на доработку
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-[15px] font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed bg-red-600 text-white hover:bg-red-700"
              disabled={!canReturn || decide.isPending}
              title={canReturn ? '' : 'Выберите или напишите причину'}
              onClick={() => send('rejected')}
            >
              <XCircle size={16} /> Отклонить
            </button>
            {editing && <button className="btn-ghost" onClick={() => setEditing(false)}>Отмена</button>}
          </div>
          <div className="mt-2 text-xs text-ink-500">
            «Вернуть на доработку» — студент исправит и пришлёт новую версию, она появится во входящих со сравнением полей.
            Решение уйдёт студенту в кабинет и в Telegram.
          </div>
        </div>
      )}
    </div>
  )
}
