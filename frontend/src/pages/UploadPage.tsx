import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Camera, ChevronLeft, ChevronRight, FileUp, Loader2, Search, Sparkles } from 'lucide-react'
import { api, SUGGESTED_QUESTIONS } from '../api'
import HeroIllustration from '../components/HeroIllustration'

const MAX_MB = 20
const STEPS = ['Загружаем файл…', 'Распознаём текст (OCR)…', 'Извлекаем поля…', 'Проверяем по Положению…']

const SLIDES = [
  {
    title: 'Цифровой секретарь для студента',
    text: 'Загрузите фото справки или заявления — сервис заполнит карточку полей и проверит комплектность по Положению',
  },
  {
    title: 'Ответы со ссылкой на Положение',
    text: 'Каждый ответ опирается на поле документа или пункт Положения. Если данных нет — честно скажем об этом',
  },
  {
    title: 'Плохой снимок — не проблема',
    text: 'Наклон до 30°, тени, блики и низкое разрешение: выравниваем снимок и читаем текст локально, без внешних API',
  },
]

const HOW = [
  ['Распознаём текст', 'OCR читает снимок локально: PaddleOCR, Tesseract — резерв.'],
  ['Заполняем карточку', 'Поля раскладываются по типу документа, пустые — «не найдено».'],
  ['Ищем отметки', 'Подпись и печать проверяются как графические элементы (п. 2.3).'],
  ['Отвечаем по Положению', 'Только по документу и Положению, со ссылками на источники (п. 2.1, 6.3).'],
]

function Hero({ onUpload }: { onUpload: () => void }) {
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const go = (d: number) => setI((x) => (x + d + SLIDES.length) % SLIDES.length)
  useEffect(() => {
    if (paused) return
    const t = setTimeout(() => go(1), 7000)
    return () => clearTimeout(t)
  }, [i, paused])
  const s = SLIDES[i]
  const arrow =
    'absolute top-1/2 -translate-y-1/2 z-10 hidden md:inline-flex h-16 w-16 items-center justify-center rounded-full bg-surface text-ink-800 shadow-[0_6px_20px_rgba(35,35,35,0.10)] ring-[6px] ring-[var(--paper)] hover:text-brand-700 transition'
  return (
    <section className="relative" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} aria-roledescription="карусель">
      <div className="hero-bg rounded-[28px] overflow-hidden grid lg:grid-cols-[1.15fr_1fr] items-center min-h-[380px] lg:min-h-[560px]">
        <div key={i} className="px-6 py-10 sm:px-12 lg:pl-[128px] lg:pr-4 animate-[fade-in_.5s_ease]">
          <h1 className="text-[34px] sm:text-[48px] lg:text-[58px] font-bold leading-[1.08] tracking-[-0.02em] text-ink-900">{s.title}</h1>
          <p className="mt-5 text-lg sm:text-[21px] leading-snug text-ink-700 max-w-[560px]">{s.text}</p>
          <div className="mt-8 flex flex-wrap gap-4">
            <button type="button" className="btn-primary btn-lg" onClick={onUpload}>Загрузить документ</button>
            <Link to="/about" className="btn-ghost btn-lg">Подробнее</Link>
          </div>
        </div>
        <div className="hidden lg:flex items-center justify-center pr-16 py-8">
          <HeroIllustration variant={i} />
        </div>
      </div>
      <button type="button" className={`${arrow} -left-8`} onClick={() => go(-1)} aria-label="Предыдущий слайд">
        <ChevronLeft size={26} strokeWidth={1.6} />
      </button>
      <button type="button" className={`${arrow} -right-8`} onClick={() => go(1)} aria-label="Следующий слайд">
        <ChevronRight size={26} strokeWidth={1.6} />
      </button>
      <div className="absolute bottom-5 left-6 sm:left-12 lg:left-[128px] flex gap-2">
        {SLIDES.map((_, k) => (
          <button
            key={k}
            type="button"
            onClick={() => setI(k)}
            className={`h-1.5 rounded-full transition-all ${k === i ? 'w-8 bg-brand-500' : 'w-3 bg-ink-300 hover:bg-ink-400'}`}
            aria-label={`Слайд ${k + 1}`}
          />
        ))}
      </div>
    </section>
  )
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const docType = params.get('type') ?? 'auto'
  const setDocType = (t: string) => setParams(t === 'auto' ? {} : { type: t }, { replace: true, preventScrollReset: true })
  const [file, setFile] = useState<File | null>(null)
  const [question, setQuestion] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const types = useQuery({ queryKey: ['doc-types'], queryFn: api.docTypes })
  const selected = types.data?.find((t) => t.key === docType)

  const preview = useMemo(() => (file && file.type.startsWith('image/') ? URL.createObjectURL(file) : null), [file])

  const onDrop = useCallback((accepted: File[], rejected: unknown[]) => {
    setError(null)
    if (rejected.length) setError('Поддерживаются JPG, PNG и одностраничный PDF до 20 МБ')
    if (accepted[0]) setFile(accepted[0])
  }, [])

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    multiple: false,
    noClick: true,
    maxSize: MAX_MB * 1024 * 1024,
    accept: { 'image/jpeg': ['.jpg', '.jpeg'], 'image/png': ['.png'], 'application/pdf': ['.pdf'] },
  })

  const mutation = useMutation({
    mutationFn: async ({ check }: { check: boolean }) => {
      if (!file) throw new Error('Выберите файл')
      setStep(0)
      const timer = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1500)
      try {
        return await api.upload(file, docType, check ? '' : question.trim(), check)
      } finally {
        clearInterval(timer)
      }
    },
    onSuccess: (doc) => navigate(`/d/${doc.id}`, { state: { answer: doc.answer } }),
    onError: (e: Error) => setError(e.message),
  })

  const tabs: [string, string][] = [['auto', 'Автоматически'], ...(types.data?.map((t) => [t.key, t.title] as [string, string]) ?? [])]

  return (
    <div>
      <Hero
        onUpload={() => {
          document.getElementById('upload')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          open()
        }}
      />

      <section id="upload" className="mt-12 sm:mt-20 scroll-mt-28">
        <h2 className="section-title">Проверить документ</h2>
        <div role="tablist" aria-label="Тип документа" className="mt-7 flex gap-8 sm:gap-12 overflow-x-auto no-scrollbar border-b border-ink-200">
          {tabs.map(([key, title]) => (
            <button key={key} type="button" role="tab" aria-selected={docType === key} className="tab-upper" onClick={() => setDocType(key)}>
              {title}
            </button>
          ))}
        </div>
        <p className="mt-4 text-[15px] text-ink-600">
          {selected ? (
            <>
              Раздел {selected.rules_section} Положения · {selected.fields.length} полей:{' '}
              {selected.fields.map((f) => f.label).join(', ')}
            </>
          ) : (
            <>Тип определится по заголовку и меткам полей; при низкой уверенности сервис предложит выбрать его вручную.</>
          )}
        </p>

        <div className="mt-7 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
          <div className="card p-5 sm:p-8">
            <div
              {...getRootProps()}
              className={`h-full min-h-[300px] rounded-2xl border-2 border-dashed p-6 flex items-center justify-center text-center transition ${
                isDragActive ? 'border-brand-400 bg-brand-50' : 'border-ink-300 bg-surface'
              }`}
            >
              <input {...getInputProps()} />
              {file ? (
                <div className="flex flex-col items-center gap-3">
                  {preview ? (
                    <img src={preview} alt="превью" className="max-h-64 max-w-full object-contain rounded-xl shadow" />
                  ) : (
                    <div className="h-24 w-20 rounded-lg bg-panel border border-ink-200 flex items-center justify-center text-xs text-ink-500">PDF</div>
                  )}
                  <div className="text-sm">
                    <b>{file.name}</b> · {(file.size / 1024).toFixed(0)} КБ
                  </div>
                  <button type="button" className="btn-ghost" onClick={open}>
                    Выбрать другой файл
                  </button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-4">
                  <div className="h-16 w-16 rounded-2xl bg-brand-50 text-brand-500 flex items-center justify-center">
                    <FileUp size={32} />
                  </div>
                  <div className="text-[17px] text-ink-800 font-medium">Перетащите фото или скан документа</div>
                  <div className="flex flex-wrap gap-3 justify-center">
                    <button type="button" className="btn-primary" onClick={open}>
                      <FileUp size={18} /> Выбрать файл
                    </button>
                    <label className="btn-ghost cursor-pointer">
                      <Camera size={18} /> Сфотографировать
                      <input
                        type="file"
                        accept="image/*"
                        capture="environment"
                        className="hidden"
                        onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
                      />
                    </label>
                  </div>
                  <div className="text-sm text-ink-500">JPG, PNG или одностраничный PDF, до {MAX_MB} МБ</div>
                </div>
              )}
            </div>
          </div>

          <div id="ask" className="card p-5 sm:p-8 flex flex-col scroll-mt-28">
            <label className="block">
              <span className="block mb-2 text-[17px] font-semibold text-ink-900">Вопрос <span className="font-normal text-ink-500">(необязательно)</span></span>
              <textarea
                className="input min-h-[96px]"
                placeholder="Например: Хватит ли этой справки для перевода? Какова дата выдачи?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button key={q} type="button" className="chip border-ink-300 bg-surface hover:border-brand-400 hover:text-brand-700" onClick={() => setQuestion(q)}>
                  {q}
                </button>
              ))}
            </div>

            {error && <div className="mt-4 rounded-xl bg-red-50 text-red-700 text-sm p-3">{error}</div>}

            <div className="mt-auto pt-6 flex flex-wrap gap-3">
              <button className="btn-primary" disabled={!file || mutation.isPending} onClick={() => mutation.mutate({ check: false })}>
                {mutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Sparkles size={18} />}
                {question.trim() ? 'Задать вопрос' : 'Распознать документ'}
              </button>
              <button className="btn-ghost" disabled={!file || mutation.isPending} onClick={() => mutation.mutate({ check: true })}>
                <Search size={18} /> Проверить без вопроса
              </button>
            </div>
            {mutation.isPending && (
              <div className="mt-3 text-sm text-ink-600 flex items-center gap-2">
                <Loader2 className="animate-spin" size={14} /> {STEPS[step]} (обычно 3–8 секунд)
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="mt-16 sm:mt-20">
        <h2 className="section-title">Как это работает</h2>
        <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {HOW.map(([title, text], k) => (
            <div key={title} className="card p-6 sm:p-7">
              <div className="text-[40px] font-bold leading-none text-brand-500">{k + 1}</div>
              <div className="mt-5 text-[19px] font-semibold text-ink-900">{title}</div>
              <div className="mt-2 text-[15px] leading-relaxed text-ink-600">{text}</div>
            </div>
          ))}
        </div>
        <p className="mt-5 text-sm text-ink-500">
          Новый тип документа добавляется YAML-файлом в <code>config/doc_types/</code> без изменения кода.
        </p>
      </section>
    </div>
  )
}
