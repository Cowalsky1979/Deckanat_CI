// Клиент REST API Django-бэкенда (/api/v1).

export type BBox = [number, number, number, number]

export interface FieldValue {
  key: string
  label: string
  value: string | boolean
  raw: string
  bbox: BBox | null
  label_bbox: BBox | null
  confidence: number
  found: boolean
  kind: 'text' | 'mark'
}

export interface Validation {
  status: 'document_ok' | 'missing_fields'
  missing_fields: string[]
  sources: string[]
  message: string
}

export interface DocResult {
  doc_type: string
  doc_type_title: string
  type_confidence: number
  type_auto: boolean
  type_candidates: { key: string; title: string; score: number }[]
  fields: Record<string, FieldValue>
  validation: Validation
  ocr_text: string
  image_size: [number, number]
  quality: Record<string, unknown> & { readability?: { mean_ocr_conf: number; labels_found_ratio: number; low_quality: boolean } }
  timings: Record<string, number>
  warnings: string[]
  type_mismatch: { detected: string; detected_title: string; score: number } | null
  transform: number[][]
  original_size: [number, number]
}

export interface QA {
  id: number
  question: string
  answerable: boolean
  value: string | null
  answer: string
  sources: string[]
  intent: string
  field_key: string
  created_at: string
}

export interface Doc {
  id: string
  original_name: string
  mime: string
  size: number
  selected_type: string
  doc_type: string
  type_confidence: number
  status: 'processing' | 'done' | 'error'
  error: string
  pending_question: string
  pending_check: boolean
  source: string
  timings: Record<string, number>
  created_at: string
  result: DocResult | null
  questions: QA[]
  images: { original: string; original_preview: string; normalized: string; preview: string; annotated: string }
  answer?: QA | null
}

export interface DocType {
  key: string
  title: string
  rules_section: string
  complete_message_rules: string[]
  fields: { key: string; label: string; type: string; rule: string; is_mark: boolean }[]
}

export interface Rules {
  title: string
  sections: { id: string; title: string; rules: { id: string; text: string }[] }[]
}

const BASE = '/api/v1'

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      detail = j.detail || JSON.stringify(j)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

export const api = {
  health: () => fetch(`${BASE}/health`).then((r) => handle<{ status: string; engines: Record<string, string> }>(r)),
  docTypes: () => fetch(`${BASE}/doc-types`).then((r) => handle<DocType[]>(r)),
  rules: () => fetch(`${BASE}/rules`).then((r) => handle<Rules>(r)),
  // async=1: сервер сразу отвечает 202, а статус потом опрашивает страница документа
  // (туннели рвут запросы дольше нескольких секунд)
  upload: (file: File, docType: string, question: string, check: boolean) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('doc_type', docType)
    if (question) fd.append('question', question)
    if (check) fd.append('check', 'true')
    fd.append('async', '1')
    return fetch(`${BASE}/documents`, { method: 'POST', body: fd }).then((r) => handle<Doc>(r))
  },
  get: (id: string) => fetch(`${BASE}/documents/${id}`).then((r) => handle<Doc>(r)),
  ask: (id: string, question: string) =>
    fetch(`${BASE}/documents/${id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }).then((r) => handle<QA>(r)),
  check: (id: string) => fetch(`${BASE}/documents/${id}/check`, { method: 'POST' }).then((r) => handle<QA>(r)),
  changeType: (id: string, docType: string) =>
    fetch(`${BASE}/documents/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_type: docType }),
    }).then((r) => handle<Doc>(r)),
  exportUrl: (id: string) => `${BASE}/documents/${id}/export.json?download=1`,
  cropUrl: (id: string, key: string) => `${BASE}/documents/${id}/fields/${key}/crop.png`,
}

export const SUGGESTED_QUESTIONS = [
  'Содержит ли документ все обязательные сведения по Положению?',
  'Кто принимает окончательное решение о принятии документа?',
  'Укажи значение поля «Дата выдачи».',
  'Укажи значение поля «ФИО студента».',
  'Есть ли печать?',
  'Какова стоимость обучения за следующий семестр?',
]
