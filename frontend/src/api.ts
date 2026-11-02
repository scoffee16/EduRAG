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

/** 问答各阶段耗时（毫秒）；流式/非流式接口都可能缺失部分字段，值也可能为 null。 */
export interface QueryTimings {
  retrieve_ms?: number | null
  llm_ms?: number | null
  query_embedding_ms?: number | null
  vector_search_ms?: number | null
  keyword_search_ms?: number | null
  fusion_ms?: number | null
  rerank_ms?: number | null
  context_chars?: number | null
  dropped_hits?: number | null
  /** 首字延迟（仅流式 done 事件提供）。 */
  first_token_ms?: number | null
  /** 端到端总耗时（仅流式 done 事件提供）。 */
  total_ms?: number | null
}

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
  /** 各阶段耗时明细（旧版非流式接口可能没有）。 */
  timings?: QueryTimings | null
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

/* ------------------------------------------------------------------ */
/* 流式问答（POST /api/v1/query/stream，SSE）                         */
/* ------------------------------------------------------------------ */

/** 流式应答 `meta` 事件：检索阶段完成、开始生成前的上下文信息。 */
export interface QueryStreamMeta {
  request_id: string
  model: string
  knowledge_sources?: KnowledgeSource[]
  citations?: Citation[]
  web_results?: WebSearchResult[]
  timings?: QueryTimings | null
}

/** 流式应答 `done` 事件：生成结束后的完整答案与最终耗时。 */
export interface QueryStreamDone {
  answer?: string
  latency_ms?: number
  first_token_ms?: number
  timings?: QueryTimings | null
}

export interface QueryStreamHandlers {
  /** meta 事件到达（此时 citations / knowledge_sources / 检索耗时已知）。 */
  onMeta?: (meta: QueryStreamMeta) => void
  /** 每收到一段 token 增量回调，调用方负责累积成 answer。 */
  onToken?: (text: string) => void
  /** done 事件到达；随后 Promise 会以完整结果 resolve。 */
  onDone?: (done: QueryStreamDone) => void
}

/** 当前环境无法读取流式响应体（`response.body` 不可用）时抛出，调用方可回退到非流式接口。 */
export class StreamingUnsupportedError extends Error {
  constructor(message = '当前环境不支持流式响应') {
    super(message)
    this.name = 'StreamingUnsupportedError'
  }
}

interface SseEvent {
  event: string
  data: string
}

/**
 * 增量 SSE 解析器：容忍 \r\n / \r / \n 换行、跨 chunk 的半帧、
 * `:` 开头的注释行（心跳）与未知字段；空行触发事件派发。
 */
class SseParser {
  private buffer = ''
  private eventName = ''
  private dataLines: string[] = []

  /** 追加一块文本，返回本次可派发的事件。 */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk
    const events: SseEvent[] = []
    let start = 0
    for (let index = 0; index < this.buffer.length; index += 1) {
      const char = this.buffer[index]
      if (char !== '\n' && char !== '\r') continue
      // 末尾单独的 \r 可能是被拆开的 \r\n，等下一块再判断
      if (char === '\r' && index + 1 === this.buffer.length) break
      const line = this.buffer.slice(start, index)
      const consumed = char === '\r' && this.buffer[index + 1] === '\n' ? 2 : 1
      this.consumeLine(line, events)
      start = index + consumed
      index = start - 1
    }
    this.buffer = this.buffer.slice(start)
    return events
  }

  /** 流结束：把缓冲区里没有以空行结尾的最后一帧补派发。 */
  flush(): SseEvent[] {
    const events: SseEvent[] = []
    const remaining = this.buffer.replace(/\r\n?/g, '\n')
    if (remaining) {
      for (const line of remaining.split('\n')) this.consumeLine(line, events)
    }
    this.buffer = ''
    this.dispatch(events)
    return events
  }

  private consumeLine(line: string, events: SseEvent[]): void {
    if (line === '') {
      this.dispatch(events)
      return
    }
    // 注释行（心跳/调试），按 SSE 规范忽略
    if (line.startsWith(':')) return
    const colon = line.indexOf(':')
    const field = colon >= 0 ? line.slice(0, colon) : line
    let value = colon >= 0 ? line.slice(colon + 1) : ''
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') {
      this.eventName = value
    } else if (field === 'data') {
      this.dataLines.push(value)
    }
    // 其余字段（id / retry）忽略
  }

  private dispatch(events: SseEvent[]): void {
    if (this.dataLines.length > 0) {
      events.push({ event: this.eventName || 'message', data: this.dataLines.join('\n') })
    }
    this.eventName = ''
    this.dataLines = []
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 构造取消异常：优先用 DOMException('AbortError')，与非流式 fetch 行为保持一致。 */
function abortError(): Error {
  if (typeof DOMException === 'function') return new DOMException('请求已取消', 'AbortError')
  const error = new Error('请求已取消')
  error.name = 'AbortError'
  return error
}

function normalizeMeta(payload: Record<string, unknown>, headerRequestId: string): QueryStreamMeta {
  return {
    request_id: typeof payload.request_id === 'string' ? payload.request_id : headerRequestId,
    model: typeof payload.model === 'string' ? payload.model : '',
    knowledge_sources: Array.isArray(payload.knowledge_sources)
      ? (payload.knowledge_sources as KnowledgeSource[])
      : [],
    citations: Array.isArray(payload.citations) ? (payload.citations as Citation[]) : [],
    web_results: Array.isArray(payload.web_results) ? (payload.web_results as WebSearchResult[]) : [],
    timings: isRecord(payload.timings) ? (payload.timings as QueryTimings) : null,
  }
}

function normalizeDone(payload: Record<string, unknown>): QueryStreamDone {
  return {
    ...(typeof payload.answer === 'string' ? { answer: payload.answer } : {}),
    ...(typeof payload.latency_ms === 'number' ? { latency_ms: payload.latency_ms } : {}),
    ...(typeof payload.first_token_ms === 'number' ? { first_token_ms: payload.first_token_ms } : {}),
    timings: isRecord(payload.timings) ? (payload.timings as QueryTimings) : null,
  }
}

/** 合并 meta / done 的耗时明细，done 中的最终值优先。 */
function mergeTimings(
  meta: QueryStreamMeta | null,
  done: QueryStreamDone | null,
): QueryTimings | undefined {
  const merged: QueryTimings = { ...(meta?.timings ?? {}), ...(done?.timings ?? {}) }
  if (merged.first_token_ms == null && done?.first_token_ms != null) merged.first_token_ms = done.first_token_ms
  if (merged.total_ms == null && done?.latency_ms != null) merged.total_ms = done.latency_ms
  return Object.keys(merged).length > 0 ? merged : undefined
}

/**
 * 流式提问：POST /api/v1/query/stream，边读 SSE 边回调 token，返回聚合后的完整结果。
 * 非 2xx（推流开始前的失败）与流内 `error` 事件都抛 ApiError；signal 取消时抛 AbortError。
 */
export async function askQuestionStream(
  body: QueryPayload,
  handlers: QueryStreamHandlers = {},
  signal?: AbortSignal,
): Promise<QueryResponse> {
  const response = await fetch('/api/v1/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    // 开始推流前的失败仍是普通 JSON 错误信封，与 askQuestion 保持一致
    const payload = await response.json().catch(() => ({}))
    const error = payload?.error
    throw new ApiError(
      error?.message ?? payload?.detail ?? `请求失败（HTTP ${response.status}）`,
      response.status,
      payload?.request_id ?? responseRequestId(response) ?? undefined,
      error?.code,
    )
  }

  const stream = response.body
  if (!stream || typeof stream.getReader !== 'function') {
    throw new StreamingUnsupportedError()
  }

  const headerRequestId = responseRequestId(response) ?? ''
  const reader = stream.getReader()
  // 外部中止（如切换课程、组件卸载）时立即取消底层读取，
  // 避免读取循环阻塞在 reader.read() 上直到下一块数据到达。
  const cancelReader = () => {
    void reader.cancel().catch(() => {})
  }
  if (signal) {
    if (signal.aborted) cancelReader()
    else signal.addEventListener('abort', cancelReader, { once: true })
  }
  const decoder = new TextDecoder()
  const parser = new SseParser()
  const state: {
    meta: QueryStreamMeta | null
    done: QueryStreamDone | null
    streamed: string
    completed: boolean
  } = { meta: null, done: null, streamed: '', completed: false }

  /** 处理一个 SSE 事件；返回 true 表示已收到终止事件（done），应停止读取。 */
  const handleFrame = (frame: SseEvent): boolean => {
    if (!frame.data) return false
    let payload: unknown
    try {
      payload = JSON.parse(frame.data)
    } catch {
      // 无法解析的帧直接跳过，避免单帧异常中断整个回答
      return false
    }
    if (!isRecord(payload)) return false
    switch (frame.event) {
      case 'meta': {
        const meta = normalizeMeta(payload, headerRequestId)
        state.meta = meta
        handlers.onMeta?.(meta)
        return false
      }
      case 'token': {
        const text = payload.text
        if (typeof text !== 'string' || !text) return false
        state.streamed += text
        handlers.onToken?.(text)
        return false
      }
      case 'done': {
        const done = normalizeDone(payload)
        state.done = done
        state.completed = true
        handlers.onDone?.(done)
        return true
      }
      case 'error': {
        const error = isRecord(payload.error) ? payload.error : {}
        const eventRequestId = typeof payload.request_id === 'string' ? payload.request_id : null
        throw new ApiError(
          typeof error.message === 'string' ? error.message : '问答生成失败',
          response.status,
          eventRequestId ?? state.meta?.request_id ?? headerRequestId ?? undefined,
          typeof error.code === 'string' ? error.code : undefined,
        )
      }
      default:
        // 未知事件（如 ping）忽略，保证前后端版本兼容
        return false
    }
  }

  try {
    for (;;) {
      const next = await reader.read()
      if (signal?.aborted) throw abortError()
      if (next.done) break
      if (!next.value) continue
      const frames = parser.push(decoder.decode(next.value, { stream: true }))
      let stop = false
      for (const frame of frames) {
        if (handleFrame(frame)) {
          stop = true
          break
        }
      }
      if (stop) {
        // done 之后服务端会结束流，这里主动取消剩余读取
        await reader.cancel().catch(() => {})
        break
      }
    }
    if (!state.completed) {
      const tail = decoder.decode()
      if (tail) {
        for (const frame of parser.push(tail)) {
          if (handleFrame(frame)) break
        }
      }
    }
    if (!state.completed) {
      for (const frame of parser.flush()) {
        if (handleFrame(frame)) break
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => {})
    throw error
  } finally {
    signal?.removeEventListener('abort', cancelReader)
    reader.releaseLock()
  }

  if (!state.meta && !state.done && !state.streamed) {
    throw new ApiError(
      '流式响应异常结束，未收到任何数据',
      response.status,
      headerRequestId || undefined,
      'stream_incomplete',
    )
  }

  const timings = mergeTimings(state.meta, state.done)
  const answer = state.done?.answer ? state.done.answer : state.streamed
  const latency = state.done?.latency_ms ?? timings?.total_ms ?? 0
  return {
    answer,
    citations: state.meta?.citations ?? [],
    model: state.meta?.model ?? '',
    latency_ms: latency,
    request_id: state.meta?.request_id || headerRequestId,
    knowledge_sources: state.meta?.knowledge_sources,
    web_results: state.meta?.web_results,
    ...(timings ? { timings } : {}),
  }
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
