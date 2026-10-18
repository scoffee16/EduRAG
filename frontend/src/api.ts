export type FileType = 'pdf' | 'pptx' | 'docx' | string

/** 课程列表项，对应 `GET /api/v1/courses`。 */
export interface CourseSummary {
  code: string
  name: string
  description?: string | null
  /** 课程来源：`config`（配置文件同步）或 `manual`（页面新建）。 */
  origin: string
  /** 是否允许删除；config 同步来的课程不可删除。 */
  deletable: boolean
  document_count: number
  chunk_count: number
  updated_at?: string | null
}

/** 新建课程请求体，对应 `POST /api/v1/courses`。 */
export interface CreateCourseBody {
  code: string
  name: string
  description?: string
}

export interface DocumentSummary {
  document_id: string
  filename: string
  course_code: string
  course_name?: string | null
  file_type: FileType
  status: string
  page_count: number
  chunk_count: number
  created_at: string
}

/** 上传现在是异步接口：202 + 4 字段，随后轮询文档详情。 */
export interface UploadResponse {
  document_id: string
  filename: string
  course_code: string
  status: string
  /** 响应头 `X-Request-ID`，用于失败/超时排查。 */
  request_id?: string | null
}

export type DocumentStatus = 'processing' | 'indexed' | 'failed' | string

export interface DocumentProgress {
  stage: 'parse' | 'chunk' | 'embed' | 'store' | string
  done: number
  total: number
}

/** 文档详情/进度，对应 `GET /api/v1/documents/{document_id}`。 */
export interface DocumentDetail {
  document_id: string
  filename: string
  course_code: string
  file_type: FileType
  status: DocumentStatus
  progress: DocumentProgress | null
  error_code?: string | null
  page_count?: number | null
  chunk_count?: number | null
  created_at?: string | null
  /** 响应头 `X-Request-ID`，便于失败时定位日志。 */
  request_id?: string | null
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

/** 联网搜索来源，对应问答响应中的 `web_results`。 */
export interface WebSearchResult {
  title: string
  url: string
  snippet?: string | null
}

/** 知识来源取值：课程资料 / 联网搜索 / 模型通用知识。 */
export type KnowledgeSource = 'course_materials' | 'web_search' | 'model_knowledge' | string

export interface QueryResponse {
  answer: string
  citations: Citation[]
  model: string
  latency_ms: number
  request_id: string
  /** 回答实际使用的知识来源，按优先级排列。 */
  knowledge_sources?: KnowledgeSource[]
  /** 联网搜索命中的网页结果（可能为空数组）。 */
  web_results?: WebSearchResult[]
}

/** 历史问答中限定的文档范围（空数组表示全课程检索）。 */
export interface HistoryDocumentScope {
  document_id: string
  filename: string
}

/** 最近一次问答记录，对应 `GET /api/v1/history` 返回数组的元素。 */
export interface HistoryItem {
  history_id: string
  course_code: string
  course_name?: string | null
  question: string
  answer: string
  document_scope: HistoryDocumentScope[]
  citations: Citation[]
  knowledge_sources?: KnowledgeSource[]
  web_results?: WebSearchResult[]
  model: string
  latency_ms: number
  request_id: string
  /** ISO 时间字符串；后端已按倒序返回。 */
  created_at: string
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

function responseRequestId(response: Response): string | null {
  return response.headers.get('X-Request-ID') ?? response.headers.get('x-request-id') ?? null
}

/** 读取响应头里的 request_id，失败时供 UI 显示以便排查后端日志。 */
function withRequestId<T extends object>(body: T, response: Response) {
  const requestId = responseRequestId(response)
  return requestId ? { ...body, request_id: requestId } : body
}

export async function getCourses(signal?: AbortSignal) {
  return parseResponse<CourseSummary[]>(await fetch('/api/v1/courses', { signal }))
}

/** 新建课程；409 时后端返回 `course_exists`。 */
export async function createCourse(body: CreateCourseBody, signal?: AbortSignal) {
  return parseResponse<CourseSummary>(
    await fetch('/api/v1/courses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  )
}

/**
 * 删除课程；`force=true` 时级联删除课程文档、索引与文件。
 * 成功返回 204 无 body，因此不走 parseResponse（空 body 解析会抛错）。
 */
export async function deleteCourse(code: string, opts: { force?: boolean } = {}) {
  const query = opts.force ? '?force=true' : ''
  const response = await fetch(`/api/v1/courses/${encodeURIComponent(code)}${query}`, {
    method: 'DELETE',
  })
  if (response.ok) return
  const body = await response.json().catch(() => ({}))
  const error = body?.error
  throw new ApiError(
    error?.message ?? body?.detail ?? `请求失败（HTTP ${response.status}）`,
    response.status,
    body?.request_id,
    error?.code,
  )
}

export async function getDocuments(courseCode: string, signal?: AbortSignal) {
  const query = courseCode ? `?course_code=${encodeURIComponent(courseCode)}` : ''
  return parseResponse<DocumentSummary[]>(await fetch(`/api/v1/documents${query}`, { signal }))
}

/** 上传文档（异步）：后端立即返回 202，进度通过 getDocument 轮询。 */
export async function uploadDocument(file: File, courseCode: string, signal?: AbortSignal) {
  const form = new FormData()
  form.append('file', file)
  form.append('course_code', courseCode)
  const response = await fetch('/api/v1/upload', { method: 'POST', body: form, signal })
  const body = await parseResponse<UploadResponse>(response)
  return withRequestId(body, response)
}

/** 文档解析/分块/向量化进度。 */
export async function getDocument(documentId: string, signal?: AbortSignal) {
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}`, { signal })
  const body = await parseResponse<DocumentDetail>(response)
  return withRequestId(body, response)
}

export async function deleteDocument(documentId: string) {
  return parseResponse<{ document_id: string; status: string }>(
    await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' }),
  )
}

/** 问答请求体：限定文档优先用 `document_ids`（1..50 篇），`document_id` 仅兼容旧后端。 */
export interface QueryPayload {
  question: string
  course_code?: string
  /** 全课程检索时不传；限定检索时为已选文档 ID（长度 1..N）。 */
  document_ids?: string[]
  /** 旧版单文档字段；前端已不再发送，保留类型以兼容旧后端。 */
  document_id?: string
  top_k: number
}

export async function askQuestion(body: QueryPayload, signal?: AbortSignal) {
  return parseResponse<QueryResponse>(
    await fetch('/api/v1/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  )
}

/** 最近问答记录（后端按 created_at 倒序返回，默认最多 20 条）。 */
export async function getHistory(limit = 20, signal?: AbortSignal) {
  const query = limit > 0 ? `?limit=${encodeURIComponent(String(limit))}` : ''
  return parseResponse<HistoryItem[]>(await fetch(`/api/v1/history${query}`, { signal }))
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
