import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, RefreshCw, Search, Send, Upload } from 'lucide-react'
import { api, type Doc, type QA, SUGGESTED_QUESTIONS } from '../api'
import { downloadFile, inTelegram } from '../telegram'
import ImageViewer from '../components/ImageViewer'
import AnswerCard from '../components/AnswerCard'
import FieldsTable from '../components/FieldsTable'
import ValidationCard from '../components/ValidationCard'

type Tab = 'answer' | 'fields' | 'ocr'

export default function DocumentPage() {
  const { id = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [highlight, setHighlight] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('answer')
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<QA[]>([])
  const [variant, setVariant] = useState<'normalized' | 'original'>('normalized')

  // пока документ обрабатывается, опрашиваем статус
  const doc = useQuery({
    queryKey: ['doc', id],
    queryFn: () => api.get(id),
    refetchInterval: (q) => (q.state.data?.status === 'processing' ? 1200 : false),
  })
  const types = useQuery({ queryKey: ['doc-types'], queryFn: api.docTypes })

  useEffect(() => {
    if (doc.data) {
      const initial = (location.state as { answer?: QA } | null)?.answer
      const qs = doc.data.questions ?? []
      setHistory(initial && !qs.find((q) => q.id === initial.id) ? [...qs, initial] : qs)
      const last = qs[qs.length - 1]
      if (last?.field_key) setHighlight(last.field_key)
    }
  }, [doc.data, location.state])

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(id, q),
    onSuccess: (qa) => {
      setHistory((h) => [...h, qa])
      setQuestion('')
      setTab('answer')
      if (qa.field_key) setHighlight(qa.field_key)
    },
  })
  const check = useMutation({
    mutationFn: () => api.check(id),
    onSuccess: (qa) => {
      setHistory((h) => [...h, qa])
      setTab('answer')
    },
  })
  const retype = useMutation({
    mutationFn: (t: string) => api.changeType(id, t),
    onSuccess: (d: Doc) => {
      qc.setQueryData(['doc', id], d)
      setHistory([])
      setHighlight(null)
    },
  })

  const last = history[history.length - 1]
  const result = doc.data?.result
  const fields = useMemo(() => (result ? Object.values(result.fields) : []), [result])

  if (doc.isLoading) return <div className="flex items-center gap-2 text-ink-600"><Loader2 className="animate-spin" /> Загрузка…</div>
  if (doc.data?.status === 'processing')
    return (
      <div className="card p-6 max-w-xl mx-auto text-center">
        <Loader2 className="animate-spin mx-auto text-brand-500" size={36} />
        <div className="mt-3 font-semibold">Обрабатываем документ…</div>
        <div className="text-sm text-ink-600 mt-1">
          Выравниваем снимок, распознаём текст, извлекаем поля и проверяем по Положению. Обычно 5–10 секунд.
        </div>
        <div className="text-xs text-ink-500 mt-3 truncate">{doc.data.original_name}</div>
      </div>
    )
  if (doc.error || !doc.data) return <div className="card p-5 text-red-700">Документ не найден: {(doc.error as Error)?.message}</div>
  if (doc.data.status === 'error' || !result)
    return (
      <div className="card p-5">
        <div className="text-red-700 font-medium">Ошибка обработки</div>
        <div className="text-sm text-ink-600 mt-1">{doc.data.error}</div>
        <button className="btn-primary mt-4" onClick={() => navigate('/')}><Upload size={16} /> Загрузить другой документ</button>
      </div>
    )

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1fr] xl:grid-cols-[1.05fr_1fr]">
      {/* ---------- снимок ---------- */}
      <section className="card p-3 sm:p-4 lg:sticky lg:top-[86px] self-start">
        <div className="flex items-center justify-between gap-2 px-1 pb-2">
          <div className="text-sm text-ink-600 truncate">{doc.data.original_name}</div>
          <div className="flex gap-1 text-xs">
            <button className={`chip ${variant === 'normalized' ? 'bg-brand-500 text-white border-brand-500' : 'border-ink-300'}`} onClick={() => setVariant('normalized')}>выровненный</button>
            <button className={`chip ${variant === 'original' ? 'bg-brand-500 text-white border-brand-500' : 'border-ink-300'}`} onClick={() => setVariant('original')}>исходный</button>
          </div>
        </div>
        <ImageViewer
          src={variant === 'normalized' ? doc.data.images.preview : doc.data.images.original_preview}
          size={variant === 'normalized' ? result.image_size : result.original_size}
          fields={fields}
          transform={variant === 'original' ? result.transform : null}
          highlight={highlight}
          onSelect={setHighlight}
          isPdfOriginal={false}
        />
        <div className="mt-2 flex flex-wrap gap-3 px-1 text-xs text-ink-500">
          <span><i className="inline-block w-3 h-3 rounded-sm bg-brand-500 mr-1 align-middle" />поле найдено</span>
          <span><i className="inline-block w-3 h-3 rounded-sm bg-red-500 mr-1 align-middle" />не найдено</span>
          <span><i className="inline-block w-3 h-3 rounded-sm bg-blue-600 mr-1 align-middle" />подпись / печать</span>
          <span className="ml-auto">клик по полю — подсветка</span>
        </div>
      </section>

      {/* ---------- карточки ---------- */}
      <section className="space-y-4">
        <div className="card p-5">
          <div className="flex flex-wrap items-center gap-2">
            <div>
              <div className="text-xs text-ink-500">Тип документа {result.type_auto && '(определён автоматически)'}</div>
              <div className="font-semibold">{result.doc_type_title}</div>
            </div>
            {result.type_auto && (
              <span className={`chip ${result.type_confidence >= 0.5 ? 'border-green-300 bg-green-50 text-green-800' : 'border-amber-300 bg-amber-50 text-amber-800'}`}>
                уверенность {(result.type_confidence * 100).toFixed(0)}%
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <select
                className="input !w-auto !py-1.5 text-xs"
                value={result.doc_type}
                disabled={retype.isPending}
                onChange={(e) => retype.mutate(e.target.value)}
              >
                {types.data?.map((t) => (
                  <option key={t.key} value={t.key}>{t.title}</option>
                ))}
              </select>
              {retype.isPending && <Loader2 className="animate-spin" size={16} />}
            </div>
          </div>
          {result.quality?.readability?.low_quality && (
            <div className="mt-3 rounded-xl border border-red-300 bg-red-50 p-3 text-sm">
              <div className="font-semibold text-red-800">Снимок низкого качества — результат ненадёжен</div>
              <div className="text-red-800/90 mt-0.5">
                Текст мелкий или нечёткий (уверенность OCR {Math.round((result.quality.readability.mean_ocr_conf ?? 0) * 100)}%,
                найдено меток {Math.round((result.quality.readability.labels_found_ratio ?? 0) * 100)}%). Сфотографируйте документ ближе,
                ровно и при хорошем освещении или загрузите скан/PDF. Поля с низкой уверенностью помечены знаком «?».
              </div>
            </div>
          )}
          {result.type_mismatch && (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
              <div className="font-semibold text-amber-800">Похоже, выбран неправильный тип документа</div>
              <div className="text-amber-800/90 mt-0.5">
                Загруженный документ больше похож на «{result.type_mismatch.detected_title}», поэтому большинство полей не найдено.
              </div>
              <button className="btn-primary mt-2 !py-1.5 text-xs" disabled={retype.isPending} onClick={() => retype.mutate(result.type_mismatch!.detected)}>
                Сменить тип на «{result.type_mismatch.detected_title}»
              </button>
            </div>
          )}
          {result.warnings?.filter((w) => !w.startsWith('Похоже, выбран') && !w.startsWith('Снимок низкого')).map((w) => (
            <div key={w} className="mt-2 rounded-lg bg-amber-50 text-amber-800 text-xs p-2">{w}</div>
          ))}
        </div>

        <ValidationCard validation={result.validation} fields={result.fields} onSelect={setHighlight} />

        <div className="card">
          <div role="tablist" className="flex gap-6 px-5 pt-4 border-b border-ink-200 overflow-x-auto no-scrollbar">
            {([['answer', 'Ответы'], ['fields', 'Карточка полей'], ['ocr', 'Распознанный текст']] as [Tab, string][]).map(([k, t]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className="tab-upper !text-[14px] !pb-3.5">
                {t}
              </button>
            ))}
          </div>
          <div className="p-5">
            {tab === 'answer' && (
              <div className="space-y-3">
                {history.length === 0 && (
                  <div className="text-sm text-ink-500">Задайте вопрос о документе или нажмите «Проверить комплектность».</div>
                )}
                {history.map((qa) => (
                  <AnswerCard key={qa.id} qa={qa} fields={result.fields} docId={id} onSelect={setHighlight} highlighted={last?.id === qa.id} />
                ))}
                <form
                  id="ask"
                  className="pt-2 flex gap-2 scroll-mt-28"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (question.trim()) ask.mutate(question.trim())
                  }}
                >
                  <input className="input" placeholder="Вопрос по документу или Положению…" value={question} onChange={(e) => setQuestion(e.target.value)} />
                  <button className="btn-accent" disabled={!question.trim() || ask.isPending}>
                    {ask.isPending ? <Loader2 className="animate-spin" size={16} /> : <Send size={16} />}
                  </button>
                </form>
                <div className="flex flex-wrap gap-1.5">
                  <button className="chip border-brand-500 bg-brand-500 text-white" onClick={() => check.mutate()} disabled={check.isPending}>
                    <Search size={12} /> Проверить комплектность
                  </button>
                  {SUGGESTED_QUESTIONS.filter((q) => !q.startsWith('Содержит')).map((q) => (
                    <button key={q} className="chip border-ink-300 bg-surface hover:bg-ink-100" onClick={() => ask.mutate(q)}>{q}</button>
                  ))}
                </div>
              </div>
            )}
            {tab === 'fields' && <FieldsTable fields={result.fields} highlight={highlight} onSelect={setHighlight} docId={id} />}
            {tab === 'ocr' && (
              <div>
                <pre className="whitespace-pre-wrap text-xs leading-5 bg-surface rounded-xl p-3 max-h-96 overflow-auto">{result.ocr_text}</pre>
                <div className="mt-2 text-xs text-ink-500">
                  OCR: {String((result.quality as { ocr?: { engines?: string[] } })?.ocr?.engines?.join(' + ') ?? '')} · предобработка:{' '}
                  {String(((result.quality as { steps?: string[] })?.steps ?? []).join(', ') || 'не требовалась')} · время:{' '}
                  {Object.entries(result.timings).map(([k, v]) => `${k} ${v}s`).join(', ')}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {inTelegram() ? (
            <button className="btn-ghost" onClick={() => downloadFile(api.exportUrl(id), `${id}.json`)}>
              <Download size={16} /> Скачать JSON
            </button>
          ) : (
            <a className="btn-ghost" href={api.exportUrl(id)} download={`${id}.json`}><Download size={16} /> Скачать JSON</a>
          )}
          <button
            className="btn-ghost"
            disabled={doc.isFetching}
            onClick={async () => {
              setHighlight(null)
              const r = await doc.refetch()
              if (r.data) setHistory(r.data.questions ?? [])
            }}
          >
            {doc.isFetching ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
            {doc.isFetching ? 'Обновляем…' : 'Обновить'}
          </button>
          <button className="btn-primary ml-auto" onClick={() => navigate('/')}><Upload size={16} /> Другой документ</button>
        </div>
      </section>
    </div>
  )
}
