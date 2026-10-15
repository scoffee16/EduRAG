export type FileType = 'pdf' | 'pptx' | string

export interface DocumentSummary {
  document_id: string
  filename: string
  course_code: string
  file_type: FileType
  status: string
  page_count: number
  chunk_count: number
  created_at: string
}

export interface UploadResponse {
  document_id: string
  filename: string
  pages: number
  chunks: number
  course_code: string
  status: string
}

export interface Citation {
  document_id?: string | null
  filename?: string | null
  page?: number | string | null
  snippet?: string | null
  score?: number | null
  modality?: string | null
  file_type?: string | null
  block_type?: string | null
  page_used_ocr?: boolean | null
  text_sources?: string[] | null
}

export interface QueryResponse {
  answer: string
  citations: Citation[]
  model: string
  latency_ms: number
  request_id: string
}

export interface OcrHealth {
  status: 'disabled' | 'ok' | 'unavailable' | string
  engine?: string
  error?: string | null
  missing_languages?: string[]
}

export class ApiError extends Error {
  status: number
  requestId?: string
  code?: string

  constructor(message: string, status: number, requestId?: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.requestId = requestId
    this.code = code
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = body?.error
    const message = error?.message ?? body?.detail ?? `请求失败（HTTP ${response.status}）`
    throw new ApiError(message, response.status, body?.request_id, error?.code)
  }
  return body as T
}

export async function getDocuments(courseCode: string, signal?: AbortSignal) {
  const query = courseCode ? `?course_code=${encodeURIComponent(courseCode)}` : ''
  return parseResponse<DocumentSummary[]>(await fetch(`/api/v1/documents${query}`, { signal }))
}

export async function uploadDocument(file: File, courseCode: string, signal?: AbortSignal) {
  const form = new FormData()
  form.append('file', file)
  form.append('course_code', courseCode)
  return parseResponse<UploadResponse>(
    await fetch('/api/v1/upload', { method: 'POST', body: form, signal }),
  )
}

export async function deleteDocument(documentId: string) {
  return parseResponse<{ document_id: string; status: string }>(
    await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' }),
  )
}

export async function askQuestion(
  body: { question: string; course_code?: string; document_id?: string; top_k: number },
  signal?: AbortSignal,
) {
  return parseResponse<QueryResponse>(
    await fetch('/api/v1/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  )
}

export async function getOcrHealth(signal?: AbortSignal) {
  const response = await fetch('/api/v1/health/ocr', { signal })
  const body = await response.json().catch(() => ({}))
  if (response.status === 503 && body?.status) return body as OcrHealth
  if (!response.ok) {
    const error = body?.error
    throw new ApiError(
      error?.message ?? body?.detail ?? `请求失败（HTTP ${response.status}）`,
      response.status,
      body?.request_id,
      error?.code,
    )
  }
  return body as OcrHealth
}
