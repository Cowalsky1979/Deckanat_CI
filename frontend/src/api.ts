// Клиент REST API Django-бэкенда (/api/v1).
import { getProfile, type Profile, type Role } from './profile'

export type BBox = [number, number, number, number]

// почему поле не найдено (из ядра)
export type MissingReason = 'label_not_found' | 'empty_value' | 'anchor_not_found' | 'mark_not_detected'

export const MISSING_REASON_TEXT: Record<MissingReason, string> = {
  label_not_found: 'метка поля не распознана на снимке',
  empty_value: 'в документе поле не заполнено',
  anchor_not_found: 'надпись для отметки не найдена',
  mark_not_detected: 'рядом с надписью нет графической отметки',
}

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
  source: 'ocr' | 'manual'
  ocr_value: string | null
  missing_reason: MissingReason | null
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

// ---------- кабинет ----------

export interface ProfileShort {
  id: string
  role: Role
  name: string
}

export type ReviewStatus = 'pending' | 'accepted' | 'rejected' | 'needs_fix'
export type Decision = 'accepted' | 'rejected' | 'needs_fix'

export interface Review {
  id: number
  status: ReviewStatus
  submitted_at: string
  decided_at: string | null
  reviewer: ProfileShort | null
  comment: string
  reason_source: 'ai' | 'manual' | ''
  seen_by_dean: boolean
}

export interface AiSummary {
  headline: string
  validation_status: 'document_ok' | 'missing_fields' | null
  validation_message: string
  missing: { key: string; label: string; rule: string | null; reason: MissingReason | null; reason_text: string }[]
  low_quality: boolean
  type_mismatch: { detected: string; detected_title: string; score: number } | null
  warnings: string[]
  manual_fields: { key: string; label: string; value: string; ocr_value: string | null }[]
  is_revision: boolean
  suggested_reasons: string[]
}

// другая версия документа: прежняя (parent) или исправленная (revisions)
export interface RevisionShort {
  id: string
  original_name: string
  doc_type: string
  doc_type_title: string
  status: 'processing' | 'done' | 'error'
  created_at: string
  review_status: ReviewStatus | null
  review_comment: string
}

export interface DiffRow {
  key: string
  label: string
  kind: 'text' | 'mark'
  before: string
  after: string
  changed: boolean
  fixed: boolean
  manual: boolean
}

export interface Diff {
  parent_id: string
  parent_created_at: string
  parent_review_status: ReviewStatus | null
  parent_review_comment: string
  before_status: 'document_ok' | 'missing_fields' | null
  after_status: 'document_ok' | 'missing_fields' | null
  before_missing: string[]
  after_missing: string[]
  changed_count: number
  rows: DiffRow[]
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
  owner: ProfileShort | null
  review: Review | null
  ai_summary: AiSummary | null
  parent: RevisionShort | null
  revisions: RevisionShort[]
  answer?: QA | null
}

// строка списка в кабинете (без полного результата OCR)
export interface DocListItem {
  id: string
  original_name: string
  doc_type: string
  doc_type_title: string
  status: 'processing' | 'done' | 'error'
  error: string
  source: string
  created_at: string
  validation_status: 'document_ok' | 'missing_fields' | null
  missing_count: number
  questions_count: number
  last_answer: string | null
  owner: ProfileShort | null
  review: Review | null
  ai_summary: AiSummary | null
  parent: RevisionShort | null
  revisions: RevisionShort[]
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
      detail = j.detail || (j.comment && [j.comment].flat()[0]) || JSON.stringify(j)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

// все запросы идут с X-Profile-Id, если пользователь выбрал роль в кабинете
function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const p = getProfile()
  if (p) headers.set('X-Profile-Id', p.id)
  return fetch(`${BASE}${path}`, { ...init, headers }).then((r) => handle<T>(r))
}

const json = (body: unknown, method = 'POST'): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => req<{ status: string; engines: Record<string, string> }>('/health'),
  docTypes: () => req<DocType[]>('/doc-types'),
  rules: () => req<Rules>('/rules'),
  // async=1: сервер сразу отвечает 202, а статус потом опрашивает страница документа
  // (туннели рвут запросы дольше нескольких секунд)
  upload: (file: File, docType: string, question: string, check: boolean, parent?: string | null) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('doc_type', docType)
    if (question) fd.append('question', question)
    if (check) fd.append('check', 'true')
    if (parent) fd.append('parent', parent)   // исправленная версия прежнего документа
    fd.append('async', '1')
    return req<Doc>('/documents', { method: 'POST', body: fd })
  },
  get: (id: string) => req<Doc>(`/documents/${id}`),
  // ручная правка текстового поля; пустая строка возвращает значение OCR
  updateField: (id: string, key: string, value: string) => req<Doc>(`/documents/${id}/fields/${key}`, json({ value }, 'PATCH')),
  diff: (id: string) => req<Diff>(`/documents/${id}/diff`),
  ask: (id: string, question: string) => req<QA>(`/documents/${id}/ask`, json({ question })),
  check: (id: string) => req<QA>(`/documents/${id}/check`, { method: 'POST' }),
  changeType: (id: string, docType: string) => req<Doc>(`/documents/${id}`, json({ doc_type: docType }, 'PATCH')),
  exportUrl: (id: string) => `${BASE}/documents/${id}/export.json?download=1`,
  cropUrl: (id: string, key: string) => `${BASE}/documents/${id}/fields/${key}/crop.png`,

  // кабинет
  createProfile: (body: { role: Role; name: string }) => req<Profile>('/profiles', json(body)),
  me: () => req<Profile>('/profiles/me'),
  listDocuments: (params: { review?: 'pending' | 'decided' | 'all' } = {}) =>
    req<DocListItem[]>(`/documents${params.review ? `?review=${params.review}` : ''}`),
  submitReview: (id: string) => req<Review>(`/documents/${id}/submit`, { method: 'POST' }),
  reviewSummary: () => req<{ pending: number; unseen: number }>('/reviews/summary'),
  markSeen: (id: string) => req<Review>(`/documents/${id}/review/seen`, { method: 'POST' }),
  decide: (id: string, body: { status: Decision; comment: string; reason_source: 'ai' | 'manual' | '' }) =>
    req<Doc>(`/documents/${id}/review/decide`, json(body)),
  // ссылка на скачивание: заголовок не передать, поэтому профиль идёт параметром
  exportCsvUrl: (mode: 'all' | 'pending' | 'decided') =>
    `${BASE}/reviews/export.csv?review=${mode}&profile_id=${getProfile()?.id ?? ''}`,
}

export const SUGGESTED_QUESTIONS = [
  'Содержит ли документ все обязательные сведения по Положению?',
  'Кто принимает окончательное решение о принятии документа?',
  'Укажи значение поля «Дата выдачи».',
  'Укажи значение поля «ФИО студента».',
  'Есть ли печать?',
  'Какова стоимость обучения за следующий семестр?',
]
