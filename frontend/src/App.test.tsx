import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import AnswerMarkdown, { sanitizeAnswerText } from './components/AnswerMarkdown'
import type { CourseSummary, DocumentDetail, DocumentSummary, HistoryItem } from './api'

/* -------------------------------------------------------------------------- */
/*  测试数据                                                                   */
/* -------------------------------------------------------------------------- */

const COURSES: CourseSummary[] = [
  {
    code: 'CS-COMP-ORG',
    name: '计算机组成原理',
    document_count: 2,
    chunk_count: 24,
    origin: 'config',
    deletable: false,
  },
  {
    code: 'CS-OS',
    name: '操作系统',
    document_count: 0,
    chunk_count: 0,
    origin: 'config',
    deletable: false,
  },
]

function makeDocuments(): DocumentSummary[] {
  return [
    {
      document_id: 'doc-1',
      filename: '讲义.pdf',
      course_code: 'CS-COMP-ORG',
      course_name: '计算机组成原理',
      file_type: 'pdf',
      status: 'indexed',
      page_count: 3,
      chunk_count: 4,
      created_at: '2026-10-15T00:00:00Z',
    },
    {
      document_id: 'doc-2',
      filename: '课件.pptx',
      course_code: 'CS-COMP-ORG',
      course_name: '计算机组成原理',
      file_type: 'pptx',
      status: 'indexed',
      page_count: 12,
      chunk_count: 20,
      created_at: '2026-10-15T00:00:00Z',
    },
  ]
}

function courseDocuments(courseCode: string): DocumentSummary[] {
  return courseCode === 'CS-COMP-ORG' ? makeDocuments() : []
}

const DEFAULT_ANSWER = {
  answer: '**重点**：ADD 指令的微地址序列。\n\n| 步骤 | 说明 |\n| --- | --- |\n| T1 | 取指 |\n\n公式 $E=mc^2$。',
  citations: [
    {
      document_id: 'doc-1',
      filename: '讲义.pdf',
      file_type: 'pdf',
      page: 2,
      snippet: '<不应执行>',
      score: 0.81,
      modality: 'text',
      block_type: 'text',
    },
  ],
  model: 'mock-model',
  latency_ms: 21,
  request_id: 'req-answer-1',
  knowledge_sources: ['course_materials'],
  web_results: [],
}

/** 历史问答记录：全课程检索（document_scope 为空数组）。 */
const HISTORY_ALL_COURSE: HistoryItem = {
  history_id: 'hist-1',
  course_code: 'CS-COMP-ORG',
  course_name: '计算机组成原理',
  question: 'ADD 指令的微地址序列是什么？',
  answer: '**历史答案**：ADD 指令分为取指、译码两步。',
  document_scope: [],
  citations: [
    {
      document_id: 'doc-1',
      filename: '讲义.pdf',
      file_type: 'pdf',
      page: 2,
      snippet: 'ADD 指令的微地址序列如下……',
      score: 0.812,
    },
  ],
  knowledge_sources: ['course_materials'],
  web_results: [],
  model: 'mock-model',
  latency_ms: 34,
  request_id: 'req-history-1',
  created_at: '2026-10-15T08:30:00',
}

/** 历史问答记录：限定 2 篇文档，带联网来源。 */
const HISTORY_LIMITED: HistoryItem = {
  history_id: 'hist-2',
  course_code: 'CS-COMP-ORG',
  course_name: '计算机组成原理',
  question: '这两份资料的重点是什么？',
  answer: '**限定范围答案**：两篇文档的重点都在这。',
  document_scope: [
    { document_id: 'doc-1', filename: '讲义.pdf' },
    { document_id: 'doc-2', filename: '课件.pptx' },
  ],
  citations: [],
  knowledge_sources: [],
  web_results: [
    {
      title: '指令周期 - 维基百科',
      url: 'https://example.com/instruction-cycle',
      snippet: '指令周期包含取指、译码、执行等阶段。',
    },
  ],
  model: 'mock-model',
  latency_ms: 52,
  request_id: 'req-history-2',
  created_at: '2026-10-15T09:00:00',
}

/* -------------------------------------------------------------------------- */
/*  fetch 路由 mock：覆盖 /health/ocr、/courses、/documents、/upload、/query、/history */
/* -------------------------------------------------------------------------- */

interface JsonInit {
  status?: number
  headers?: Record<string, string>
}

function json(body: unknown, init: JsonInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
}

interface QueryBody {
  question: string
  course_code?: string
  document_id?: string
  document_ids?: string[]
  top_k: number
}

interface CreateCourseBody {
  code: string
  name: string
  description?: string
}

interface RecordedRequest {
  url: string
  method: string
  body: BodyInit | null | undefined
}

interface MockHandlers {
  courses?: () => Response | Promise<Response>
  createCourse?: (body: CreateCourseBody) => Response | Promise<Response>
  deleteCourse?: (code: string) => Response | Promise<Response>
  documents?: (courseCode: string) => Response | Promise<Response>
  upload?: (file: File | null) => Response | Promise<Response>
  documentDetail?: (documentId: string) => Response | Promise<Response>
  deleteDocument?: (documentId: string) => Response | Promise<Response>
  query?: (body: QueryBody) => Response | Promise<Response>
  history?: () => Response | Promise<Response>
  ocr?: () => Response | Promise<Response>
}

interface MockServer {
  requests: RecordedRequest[]
  /** 符合片段（包含匹配）的请求列表。 */
  matching: (fragment: string) => RecordedRequest[]
  /** 符合片段的请求数量。 */
  count: (fragment: string) => number
}

function installFetch(handlers: MockHandlers = {}): MockServer {
  const requests: RecordedRequest[] = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ?? null
    requests.push({ url, method, body })

    const parsed = new URL(url, 'http://localhost')
    const path = parsed.pathname

    if (path.includes('/health/ocr')) {
      return handlers.ocr?.() ?? json({ status: 'ok', engine: 'tesseract' })
    }

    if (path.includes('/courses')) {
      if (method === 'POST') {
        const createBody =
          typeof body === 'string' ? (JSON.parse(body) as CreateCourseBody) : ({} as CreateCourseBody)
        return (
          handlers.createCourse?.(createBody) ??
          json(
            {
              code: createBody.code,
              name: createBody.name,
              document_count: 0,
              chunk_count: 0,
              origin: 'manual',
              deletable: true,
            },
            { status: 201 },
          )
        )
      }
      if (method === 'DELETE') {
        const code = decodeURIComponent(path.split('/courses/')[1] ?? '')
        return handlers.deleteCourse?.(code) ?? new Response(null, { status: 204 })
      }
      return handlers.courses?.() ?? json(COURSES)
    }

    if (path.includes('/upload')) {
      if (handlers.upload) return handlers.upload(body instanceof FormData ? (body.get('file') as File) : null)
      return json(
        {
          document_id: 'doc-new',
          filename: '绪论.docx',
          course_code: 'CS-COMP-ORG',
          status: 'processing',
        },
        { status: 202, headers: { 'X-Request-ID': 'req-upload-1' } },
      )
    }

    if (path.includes('/documents/')) {
      const documentId = decodeURIComponent(path.split('/documents/')[1] ?? '')
      if (method === 'DELETE') {
        return handlers.deleteDocument?.(documentId) ?? json({ document_id: documentId, status: 'deleted' })
      }
      if (handlers.documentDetail) return handlers.documentDetail(documentId)
      const found = makeDocuments().find((document) => document.document_id === documentId)
      if (!found) return json({ error: { code: 'not_found', message: '文档不存在' } }, { status: 404 })
      return json({ ...found, status: 'indexed', progress: null, request_id: 'req-detail-1' })
    }

    if (path.includes('/documents')) {
      const courseCode = parsed.searchParams.get('course_code') ?? ''
      return handlers.documents?.(courseCode) ?? json(courseDocuments(courseCode))
    }

    if (path.includes('/history')) {
      return handlers.history?.() ?? json([])
    }

    if (path.includes('/query')) {
      const queryBody =
        typeof body === 'string' ? (JSON.parse(body) as QueryBody) : ({} as QueryBody)
      return handlers.query?.(queryBody) ?? json(DEFAULT_ANSWER)
    }

    return json({ error: { code: 'not_found', message: `未 mock 的接口：${url}` } }, { status: 404 })
  })

  vi.stubGlobal('fetch', fetchMock)

  const matching = (fragment: string) => requests.filter((request) => request.url.includes(fragment))
  return { requests, matching, count: (fragment: string) => matching(fragment).length }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function uploadInput(): HTMLInputElement {
  const input = document.getElementById('file-upload')
  if (!(input instanceof HTMLInputElement)) throw new Error('未找到文件上传输入框')
  return input
}

function chooseFile(file: File) {
  fireEvent.change(uploadInput(), { target: { files: [file] } })
}

const PDF_FILE = () =>
  new File(['pdf'], '绪论.pdf', { type: 'application/pdf' })
const DOCX_FILE = () =>
  new File(['docx'], '绪论.docx', {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })

function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------------- */
/*  页面级交互                                                                 */
/* -------------------------------------------------------------------------- */

describe('EduRAG 前端工作流', () => {
  it('加载课程与文档：默认选中第一门课程、展示课程名+代码与 OCR 状态', async () => {
    const server = installFetch()
    render(<App />)

    expect(await screen.findByText('讲义.pdf')).toBeInTheDocument()
    expect(await screen.findByText('课件.pptx')).toBeInTheDocument()
    expect(screen.getByTestId('ocr-status')).toHaveTextContent('OCR 可用')
    expect(screen.getByText('计算机组成原理（CS-COMP-ORG）')).toBeInTheDocument()
    expect(screen.getAllByText('计算机组成原理 · CS-COMP-ORG')).toHaveLength(2)
    expect(
      screen.getByRole('option', { name: '计算机组成原理（CS-COMP-ORG）· 2 篇文档' }),
    ).toBeInTheDocument()
    expect(server.count('/api/v1/documents?course_code=CS-COMP-ORG')).toBe(1)
    // 全课程模式的使用说明：所有文档可检索 + 如何切换成限定模式
    expect(screen.getByTestId('scope-help')).toHaveTextContent(
      '所有归属于该课程的文档都可被检索；想切换成限定文档模式，请点击您想限定的课程文档。',
    )
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('全课程')
  })

  it('切换课程会重新加载文档、清空限定选择与上一次回答', async () => {
    const user = userEvent.setup()
    const server = installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.click(screen.getByText('讲义.pdf'))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('限定 1 篇文档')
    expect(screen.getByText(/问答将限定在/)).toBeInTheDocument()
    expect(screen.getByTestId('scope-help')).toHaveTextContent('仅检索已选 1 篇文档')
    expect(screen.getByRole('button', { name: '恢复全课程' })).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText(/ADD 指令/), '这个问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))

    expect(await screen.findByText('重点')).toBeInTheDocument()
    expect(screen.getByText('req-answer-1')).toBeInTheDocument()
    const queryRequest = server.matching('/api/v1/query')[0]
    const queryBody = JSON.parse(String(queryRequest.body)) as QueryBody
    expect(queryBody).toMatchObject({
      question: '这个问题',
      course_code: 'CS-COMP-ORG',
      document_ids: ['doc-1'],
      top_k: 5,
    })
    // 不再发送旧的单文档字段
    expect(queryBody).not.toHaveProperty('document_id')

    await user.selectOptions(screen.getByLabelText('课程'), 'CS-OS')

    await waitFor(() => expect(screen.getByText(/全课程/)).toBeInTheDocument())
    expect(screen.queryByTestId('answer-markdown')).not.toBeInTheDocument()
    expect(screen.queryByText(/问答将限定在/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '恢复全课程' })).not.toBeInTheDocument()
    expect(await screen.findByText('该课程还没有文档')).toBeInTheDocument()
    expect(server.count('/api/v1/documents?course_code=CS-OS')).toBe(1)
  })

  it('手动新建课程：双输入框填写代码与名称，创建前不会用输入值加载文档', async () => {
    const user = userEvent.setup()
    const server = installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.selectOptions(screen.getByLabelText('课程'), '__manual__')

    const codeInput = await screen.findByLabelText('课程代码')
    const nameInput = screen.getByLabelText('课程名称')
    expect(screen.getByRole('button', { name: '创建课程' })).toBeDisabled()

    await user.type(codeInput, 'cs-sys')
    expect(codeInput).toHaveValue('CS-SYS')
    await user.type(nameInput, '计算机系统')
    expect(screen.getByRole('button', { name: '创建课程' })).toBeEnabled()

    // 创建成功前：不按输入值请求文档，上传/问答都不可用
    expect(server.count('/api/v1/documents?course_code=CS-SYS')).toBe(0)
    expect(screen.getByText('请先创建课程')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始问答' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.getByLabelText('课程')).toHaveValue('CS-COMP-ORG')
  })

  it('课程列表为空时进入手动新建课程模式', async () => {
    installFetch({ courses: () => json([]) })
    render(<App />)

    expect(await screen.findByLabelText('课程代码')).toBeInTheDocument()
    expect(screen.getByLabelText('课程名称')).toBeInTheDocument()
    expect(screen.getByText('请先创建课程')).toBeInTheDocument()
    expect(screen.getByText('该课程还没有文档')).toBeInTheDocument()
  })

  it('文档列表加载中展示骨架屏，返回后渲染列表', async () => {
    const pendingDocuments = deferred<Response>()
    installFetch({ documents: () => pendingDocuments.promise })
    render(<App />)

    expect(await screen.findByTestId('document-skeleton')).toBeInTheDocument()

    await act(async () => {
      pendingDocuments.resolve(json(makeDocuments()))
    })

    expect(await screen.findByText('讲义.pdf')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('document-skeleton')).not.toBeInTheDocument())
  })

  it('上传返回 202 后轮询进度：展示阶段进度条，indexed 后刷新课程与文档', async () => {
    const user = userEvent.setup()
    let documents = makeDocuments()
    let detailCalls = 0
    const indexedDetail: DocumentDetail = {
      document_id: 'doc-new',
      filename: '绪论.docx',
      course_code: 'CS-COMP-ORG',
      file_type: 'docx',
      status: 'indexed',
      progress: null,
      page_count: 5,
      chunk_count: 30,
    }
    const server = installFetch({
      documents: () => json(documents),
      upload: () =>
        json(
          {
            document_id: 'doc-new',
            filename: '绪论.docx',
            course_code: 'CS-COMP-ORG',
            status: 'processing',
          },
          { status: 202, headers: { 'X-Request-ID': 'req-upload-1' } },
        ),
      documentDetail: () => {
        detailCalls += 1
        if (detailCalls === 1) {
          return json(
            {
              document_id: 'doc-new',
              filename: '绪论.docx',
              course_code: 'CS-COMP-ORG',
              file_type: 'docx',
              status: 'processing',
              progress: { stage: 'embed', done: 3, total: 10 },
            },
            { headers: { 'X-Request-ID': 'req-detail-1' } },
          )
        }
        documents = [...documents, indexedDetail as unknown as DocumentSummary]
        return json(indexedDetail, { headers: { 'X-Request-ID': 'req-detail-2' } })
      },
    })

    render(<App pollIntervalMs={150} />)
    await screen.findByText('讲义.pdf')

    chooseFile(DOCX_FILE())
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))

    expect(
      await screen.findByRole('button', { name: '正在解析并向量化，大文件可能需要数分钟' }),
    ).toBeDisabled()
    expect(await screen.findByText('向量化 3/10')).toBeInTheDocument()
    const progressBar = document.querySelector('.progress-bar') as HTMLElement
    expect(progressBar.style.width).toBe('56%')

    expect(await screen.findByText('文档已建立索引')).toBeInTheDocument()
    expect(await screen.findByText('绪论.docx')).toBeInTheDocument()
    expect(screen.getByText('5 节 · 30 chunks · indexed')).toBeInTheDocument()
    await waitFor(() => expect(server.count('/api/v1/courses')).toBeGreaterThanOrEqual(2))
    expect(server.count('/api/v1/documents?course_code=CS-COMP-ORG')).toBeGreaterThanOrEqual(2)
  })

  it('文档处理 failed 时展示 error_code 与 request_id，并允许重试上传', async () => {
    const user = userEvent.setup()
    installFetch({
      upload: () =>
        json(
          {
            document_id: 'doc-bad',
            filename: '坏文档.pdf',
            course_code: 'CS-COMP-ORG',
            status: 'processing',
          },
          { status: 202, headers: { 'X-Request-ID': 'req-upload-bad' } },
        ),
      documentDetail: () =>
        json(
          {
            document_id: 'doc-bad',
            filename: '坏文档.pdf',
            course_code: 'CS-COMP-ORG',
            file_type: 'pdf',
            status: 'failed',
            progress: null,
            error_code: 'parse_error',
          },
          { headers: { 'X-Request-ID': 'req-detail-fail' } },
        ),
    })
    render(<App pollIntervalMs={10} />)

    await screen.findByText('讲义.pdf')
    chooseFile(PDF_FILE())
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))

    expect(await screen.findByText('文档处理失败（parse_error）')).toBeInTheDocument()
    expect(screen.getByText('req-detail-fail')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试上传' })).toBeEnabled()
  })

  it('轮询超时后展示 10 分钟超时提示与 request_id', async () => {
    const user = userEvent.setup()
    installFetch({
      upload: () =>
        json(
          {
            document_id: 'doc-slow',
            filename: '慢文档.pdf',
            course_code: 'CS-COMP-ORG',
            status: 'processing',
          },
          { status: 202, headers: { 'X-Request-ID': 'req-upload-timeout' } },
        ),
      documentDetail: () =>
        json({
          document_id: 'doc-slow',
          filename: '慢文档.pdf',
          course_code: 'CS-COMP-ORG',
          file_type: 'pdf',
          status: 'processing',
          progress: { stage: 'parse', done: 0, total: 0 },
        }),
    })
    render(<App pollIntervalMs={15} uploadTimeoutMs={60} />)

    await screen.findByText('讲义.pdf')
    chooseFile(PDF_FILE())
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))

    expect(
      await screen.findByText('处理超时（超过 10 分钟）', {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(screen.getByText('req-upload-timeout')).toBeInTheDocument()
  })

  it('可以中止上传进度轮询', async () => {
    const user = userEvent.setup()
    const server = installFetch({
      upload: () =>
        json(
          {
            document_id: 'doc-slow',
            filename: '慢文档.pdf',
            course_code: 'CS-COMP-ORG',
            status: 'processing',
          },
          { status: 202 },
        ),
      documentDetail: () =>
        json({
          document_id: 'doc-slow',
          filename: '慢文档.pdf',
          course_code: 'CS-COMP-ORG',
          file_type: 'pdf',
          status: 'processing',
          progress: { stage: 'chunk', done: 0, total: 0 },
        }),
    })
    render(<App pollIntervalMs={300} />)

    await screen.findByText('讲义.pdf')
    chooseFile(PDF_FILE())
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))
    await screen.findByText('切分文本块中…')

    await user.click(screen.getByRole('button', { name: '中止轮询' }))
    expect(await screen.findByText('已中止进度轮询')).toBeInTheDocument()

    const callsAfterCancel = server.count('/api/v1/documents/doc-slow')
    await sleep(450)
    expect(server.count('/api/v1/documents/doc-slow')).toBe(callsAfterCancel)
  })

  it('上传接口报错时展示错误信息、错误码与 request_id', async () => {
    const user = userEvent.setup()
    installFetch({
      upload: () =>
        json(
          {
            error: { code: 'unsupported_file', message: '不支持的文件类型' },
            request_id: 'req-upload-error',
          },
          { status: 400 },
        ),
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    chooseFile(PDF_FILE())
    await user.click(screen.getByRole('button', { name: '上传并建立索引' }))

    expect(await screen.findByText('上传失败')).toBeInTheDocument()
    expect(screen.getByText('不支持的文件类型')).toBeInTheDocument()
    expect(screen.getByText('错误码 unsupported_file')).toBeInTheDocument()
    expect(screen.getByText('req-upload-error')).toBeInTheDocument()
  })

  it('上传区域支持 PDF / PPTX / DOCX，旧版 .doc 给出另存为 .docx 的引导', async () => {
    installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    expect(screen.getByText('选择或拖入 PDF / PPTX / DOCX')).toBeInTheDocument()
    expect(uploadInput().accept).toContain('.docx')
    // 解析能力说明：PDF 扫描页自动 OCR；PPTX / DOCX 仅解析文字段落
    expect(screen.getByText('PDF 扫描页可自动 OCR（依赖 OCR 引擎）')).toBeInTheDocument()
    expect(
      screen.getByText('PPTX / DOCX 只解析文字段落，图片中的文字暂不识别'),
    ).toBeInTheDocument()
    expect(screen.queryByText('PPTX / DOCX 仅解析文本内容')).not.toBeInTheDocument()

    chooseFile(new File(['doc'], '旧讲义.doc', { type: 'application/msword' }))
    expect(await screen.findByText('暂不支持旧版 .doc')).toBeInTheDocument()
    expect(screen.getByText('请用 Word / WPS 另存为 .docx 后再上传。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上传并建立索引' })).toBeDisabled()
  })

  it('删除文档需要确认，确认后调用 DELETE 并刷新列表', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const server = installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.click(screen.getByTitle('删除 讲义.pdf'))

    expect(confirm).toHaveBeenCalled()
    expect(server.matching('/api/v1/documents/doc-1').some((request) => request.method === 'DELETE')).toBe(false)

    confirm.mockReturnValue(true)
    await user.click(screen.getByTitle('删除 讲义.pdf'))

    await waitFor(() =>
      expect(
        server.matching('/api/v1/documents/doc-1').some((request) => request.method === 'DELETE'),
      ).toBe(true),
    )
    expect(server.count('/api/v1/courses')).toBeGreaterThanOrEqual(2)
  })

  it('问答失败（429）展示错误与 request_id，并提示稍后重试', async () => {
    const user = userEvent.setup()
    installFetch({
      query: () =>
        json(
          { error: { code: 'busy', message: '服务繁忙' }, request_id: 'req-429' },
          { status: 429 },
        ),
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.type(screen.getByPlaceholderText(/ADD 指令/), '这个问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))

    expect(await screen.findByText('问答失败')).toBeInTheDocument()
    expect(screen.getByText('服务繁忙 请稍后重试。')).toBeInTheDocument()
    expect(screen.getByText('req-429')).toBeInTheDocument()
  })

  it('OCR 健康检查返回 503 时展示 OCR 不可用警告', async () => {
    installFetch({
      ocr: () => json({ status: 'unavailable', error: 'tesseract missing' }, { status: 503 }),
    })
    render(<App />)

    const warnings = await screen.findAllByText(/OCR 不可用/)
    expect(warnings.length).toBeGreaterThan(0)
    expect(screen.getByTestId('ocr-status')).toHaveTextContent('OCR 不可用')
  })

  it('创建课程：POST 课程代码与名称，成功后选中新课程并加载其文档', async () => {
    const user = userEvent.setup()
    let courses = [...COURSES]
    const server = installFetch({
      courses: () => json(courses),
      createCourse: (body) => {
        const created: CourseSummary = {
          code: body.code,
          name: body.name,
          document_count: 0,
          chunk_count: 0,
          origin: 'manual',
          deletable: true,
        }
        courses = [...courses, created]
        return json(created, { status: 201 })
      },
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.selectOptions(screen.getByLabelText('课程'), '__manual__')
    await user.type(screen.getByLabelText('课程代码'), 'cs-ai')
    await user.type(screen.getByLabelText('课程名称'), '人工智能导论')
    await user.click(screen.getByRole('button', { name: '创建课程' }))

    expect(await screen.findByText('课程已创建')).toBeInTheDocument()
    const post = server.matching('/api/v1/courses').find((request) => request.method === 'POST')
    expect(JSON.parse(String(post?.body))).toEqual({ code: 'CS-AI', name: '人工智能导论' })
    await waitFor(() => expect(screen.getByLabelText('课程')).toHaveValue('CS-AI'))
    await waitFor(() => expect(server.count('/api/v1/documents?course_code=CS-AI')).toBe(1))
  })

  it('创建课程返回 409 course_exists 时自动切换到已有课程', async () => {
    const user = userEvent.setup()
    installFetch({
      courses: () =>
        json([
          ...COURSES,
          {
            code: 'CS-SYS',
            name: '计算机系统',
            document_count: 0,
            chunk_count: 0,
            origin: 'manual',
            deletable: true,
          },
        ]),
      createCourse: () =>
        json(
          {
            error: { code: 'course_exists', message: '课程已存在' },
            request_id: 'req-create-409',
          },
          { status: 409 },
        ),
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.selectOptions(screen.getByLabelText('课程'), '__manual__')
    await user.type(screen.getByLabelText('课程代码'), 'cs-sys')
    await user.type(screen.getByLabelText('课程名称'), '计算机系统')
    await user.click(screen.getByRole('button', { name: '创建课程' }))

    expect(await screen.findByText('课程已存在，已切换')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('课程')).toHaveValue('CS-SYS'))
  })

  it('删除可删除课程：确认提示级联删除文档，调用 force DELETE 并刷新列表', async () => {
    const user = userEvent.setup()
    let courses: CourseSummary[] = [
      { ...COURSES[0], origin: 'manual', deletable: true, document_count: 3 },
      COURSES[1],
    ]
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const server = installFetch({
      courses: () => json(courses),
      deleteCourse: (code) => {
        courses = courses.filter((course) => course.code !== code)
        return new Response(null, { status: 204 })
      },
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.click(await screen.findByRole('button', { name: '删除课程' }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('3 篇文档'))
    await waitFor(() =>
      expect(
        server
          .matching('/api/v1/courses/CS-COMP-ORG')
          .some((request) => request.method === 'DELETE'),
      ).toBe(true),
    )
    const deleteRequest = server
      .matching('/api/v1/courses/CS-COMP-ORG')
      .find((request) => request.method === 'DELETE')
    expect(deleteRequest?.url).toContain('force=true')

    expect(await screen.findByText('课程已删除')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('课程')).toHaveValue('CS-OS'))
    expect(screen.queryByText('讲义.pdf')).not.toBeInTheDocument()
  })

  it('配置同步的课程不可删除：删除按钮禁用并说明原因', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    const deleteButton = screen.getByRole('button', { name: '删除课程' })
    expect(deleteButton).toBeDisabled()
    expect(deleteButton).toHaveAttribute(
      'title',
      '示例课程由配置文件同步生成，不能删除',
    )
    expect(screen.getByTestId('config-course-note')).toHaveTextContent(
      '示例课程由配置文件同步生成，不能删除',
    )

    await user.selectOptions(screen.getByLabelText('课程'), 'CS-OS')
    expect(await screen.findByText('该课程还没有文档')).toBeInTheDocument()
    // 切换到另一门 config 课程：同样保留禁用的删除按钮与说明
    expect(screen.getByRole('button', { name: '删除课程' })).toBeDisabled()
    expect(screen.getByTestId('config-course-note')).toHaveTextContent(
      '示例课程由配置文件同步生成，不能删除',
    )
  })

  it('问答展示知识来源 badge、非课程资料警示与联网搜索来源', async () => {
    const user = userEvent.setup()
    installFetch({
      query: () =>
        json({
          ...DEFAULT_ANSWER,
          citations: [],
          knowledge_sources: ['course_materials', 'web_search'],
          web_results: [
            {
              title: '指令周期 - 维基百科',
              url: 'https://example.com/instruction-cycle',
              snippet: '指令周期包含取指、译码、执行等阶段。',
            },
          ],
        }),
    })
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.type(screen.getByPlaceholderText(/ADD 指令/), '指令周期是什么？')
    await user.click(screen.getByRole('button', { name: '开始问答' }))

    expect(await screen.findByText('知识来源')).toBeInTheDocument()
    expect(screen.getByText('课程资料')).toBeInTheDocument()
    expect(screen.getByText('联网搜索')).toBeInTheDocument()
    expect(screen.getByText('包含课程资料之外的内容')).toBeInTheDocument()
    expect(
      screen.getByText('本回答包含课程资料之外的内容，请谨慎参考并核实来源。'),
    ).toBeInTheDocument()
    expect(screen.getByText('本回答未使用课程资料引用。')).toBeInTheDocument()

    const link = screen.getByRole('link', { name: '指令周期 - 维基百科' })
    expect(link).toHaveAttribute('href', 'https://example.com/instruction-cycle')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(screen.getByText(/取指、译码、执行/)).toBeInTheDocument()
  })

  it('刷新文档列表成功后展示带时间的 transient 提示，并自动消失', async () => {
    const user = userEvent.setup()
    const server = installFetch()
    // 缩短提示时长，验证「展示后自动消失」的行为
    render(<App refreshNoticeMs={60} />)

    await screen.findByText('讲义.pdf')
    expect(screen.queryByText(/文档列表已刷新/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '刷新文档列表' }))
    const notice = await screen.findByText(/^文档列表已刷新（\d{2}:\d{2}:\d{2}）$/)
    expect(notice).toHaveAttribute('aria-live', 'polite')
    expect(server.count('/api/v1/documents?course_code=CS-COMP-ORG')).toBeGreaterThanOrEqual(2)

    await waitFor(
      () => expect(screen.queryByText(/文档列表已刷新/)).not.toBeInTheDocument(),
      { timeout: 3000 },
    )
  })

  it('文档列表不再有与刷新重复的「查询」按钮，刷新按钮提供无障碍名称', async () => {
    installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    expect(screen.getByRole('button', { name: '刷新文档列表' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /查询/ })).not.toBeInTheDocument()
  })

  it('限定模式支持多选：两篇文档的问答请求体携带 document_ids 数组', async () => {
    const user = userEvent.setup()
    const server = installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.click(screen.getByText('讲义.pdf'))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('限定 1 篇文档')
    await user.click(screen.getByText('课件.pptx'))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('限定 2 篇文档')
    expect(screen.getByTestId('selection-note')).toHaveTextContent('问答将限定在 2 篇文档')
    expect(screen.getByText('已选 2')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText(/ADD 指令/), '这两份资料的重点是什么？')
    await user.click(screen.getByRole('button', { name: '开始问答' }))

    expect(await screen.findByText('重点')).toBeInTheDocument()
    const queryBody = JSON.parse(
      String(server.matching('/api/v1/query')[0].body),
    ) as QueryBody
    expect(queryBody).toMatchObject({
      question: '这两份资料的重点是什么？',
      course_code: 'CS-COMP-ORG',
      document_ids: ['doc-1', 'doc-2'],
      top_k: 5,
    })
    expect(queryBody).not.toHaveProperty('document_id')
  })

  it('再次点击已选文档可取消限定，点「恢复全课程」退出限定模式', async () => {
    const user = userEvent.setup()
    const server = installFetch()
    render(<App />)

    await screen.findByText('讲义.pdf')
    await user.click(screen.getByText('讲义.pdf'))
    await user.click(screen.getByText('课件.pptx'))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('限定 2 篇文档')

    // 再次点击已选文档：取消该文档的限定
    await user.click(screen.getByText('讲义.pdf'))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('限定 1 篇文档')
    expect(screen.getByText('已选 1')).toBeInTheDocument()

    // 恢复全课程：清空全部限定
    await user.click(screen.getByRole('button', { name: '恢复全课程' }))
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('全课程')
    expect(screen.queryByTestId('selection-note')).not.toBeInTheDocument()
    expect(screen.queryByText('已选 1')).not.toBeInTheDocument()

    await user.type(screen.getByPlaceholderText(/ADD 指令/), '全课程的问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))

    expect(await screen.findByText('重点')).toBeInTheDocument()
    const queryBody = JSON.parse(
      String(server.matching('/api/v1/query')[0].body),
    ) as QueryBody
    expect(queryBody).toMatchObject({
      question: '全课程的问题',
      course_code: 'CS-COMP-ORG',
      top_k: 5,
    })
    // 全课程模式两个文档限定字段都不发送
    expect(queryBody).not.toHaveProperty('document_ids')
    expect(queryBody).not.toHaveProperty('document_id')
  })

  it('历史问答为空时展示折叠面板与空状态提示', async () => {
    installFetch()
    render(<App />)

    expect(await screen.findByTestId('history-panel')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /历史问答/ })).toBeInTheDocument()
    expect(await screen.findByText('暂无历史问答，提问后会显示在这里')).toBeInTheDocument()
    expect(screen.getByTestId('history-count')).toHaveTextContent('0')
  })

  it('历史问答默认折叠：显示时间/课程/问题/来源与范围 badge，答案和命中片段隐藏', async () => {
    installFetch({ history: () => json([HISTORY_ALL_COURSE]) })
    render(<App />)

    const panel = await screen.findByTestId('history-panel')
    expect(await within(panel).findByText('ADD 指令的微地址序列是什么？')).toBeInTheDocument()
    expect(within(panel).getByText('10-15 08:30')).toBeInTheDocument()
    expect(within(panel).getByText('计算机组成原理')).toBeInTheDocument()
    expect(within(panel).getByText('全课程')).toBeInTheDocument()
    expect(within(panel).getByText('课程资料')).toBeInTheDocument()
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')

    const summary = within(panel).getByRole('button', {
      name: /ADD 指令的微地址序列是什么/,
    })
    expect(summary).toHaveAttribute('aria-expanded', 'false')
    expect(within(panel).queryByTestId('history-detail')).not.toBeInTheDocument()
    expect(within(panel).queryByText('历史答案')).not.toBeInTheDocument()
    expect(within(panel).queryByText(/ADD 指令的微地址序列如下/)).not.toBeInTheDocument()
  })

  it('展开历史问答：显示完整问题、Markdown 答案、命中片段与 request_id', async () => {
    const user = userEvent.setup()
    installFetch({ history: () => json([HISTORY_ALL_COURSE]) })
    render(<App />)

    const panel = await screen.findByTestId('history-panel')
    const summary = await within(panel).findByRole('button', {
      name: /ADD 指令的微地址序列是什么/,
    })
    await user.click(summary)

    expect(summary).toHaveAttribute('aria-expanded', 'true')
    const detail = within(panel).getByTestId('history-detail')
    expect(within(detail).getByText('计算机组成原理（CS-COMP-ORG）')).toBeInTheDocument()
    expect(within(detail).getByText('全课程：该课程全部文档')).toBeInTheDocument()
    expect(within(detail).getByText('ADD 指令的微地址序列是什么？')).toBeInTheDocument()
    expect(await within(detail).findByText('历史答案')).toBeInTheDocument()
    expect(within(detail).getByText(/score 0\.812/)).toBeInTheDocument()
    expect(within(detail).getByText('ADD 指令的微地址序列如下……')).toBeInTheDocument()
    expect(within(detail).getByText('req-history-1')).toBeInTheDocument()
    expect(within(detail).getByTestId('history-citations')).toBeInTheDocument()
  })

  it('限定文档的历史问答：展开后显示文件名与联网来源链接', async () => {
    const user = userEvent.setup()
    installFetch({ history: () => json([HISTORY_LIMITED]) })
    render(<App />)

    const panel = await screen.findByTestId('history-panel')
    expect(await within(panel).findByText('限定 2 篇文档')).toBeInTheDocument()

    await user.click(within(panel).getByRole('button', { name: /这两份资料的重点是什么/ }))
    const detail = within(panel).getByTestId('history-detail')
    expect(within(detail).getByTestId('history-scope-files')).toHaveTextContent(
      '讲义.pdf、课件.pptx',
    )

    const link = within(detail).getByRole('link', { name: '指令周期 - 维基百科' })
    expect(link).toHaveAttribute('href', 'https://example.com/instruction-cycle')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(within(detail).getByTestId('history-web-results')).toBeInTheDocument()
    expect(within(detail).getByText(/取指、译码、执行/)).toBeInTheDocument()
  })

  it('问答成功后自动刷新历史记录', async () => {
    const user = userEvent.setup()
    let historyCalls = 0
    installFetch({
      history: () => {
        historyCalls += 1
        return json(historyCalls === 1 ? [] : [HISTORY_ALL_COURSE])
      },
    })
    render(<App />)

    const panel = await screen.findByTestId('history-panel')
    expect(await within(panel).findByText('暂无历史问答，提问后会显示在这里')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText(/ADD 指令/), 'ADD 指令是什么？')
    await user.click(screen.getByRole('button', { name: '开始问答' }))
    expect(await screen.findByText('重点')).toBeInTheDocument()

    // 问答成功后重新请求 GET /api/v1/history，折叠行出现新记录
    expect(
      await within(panel).findByText('ADD 指令的微地址序列是什么？'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('history-count')).toHaveTextContent('1')
    expect(historyCalls).toBeGreaterThanOrEqual(2)
  })

  it('历史问答加载失败不打断主流程：面板提示错误，问答仍可用', async () => {
    const user = userEvent.setup()
    installFetch({
      history: () =>
        json(
          { error: { code: 'history_unavailable', message: '历史服务不可用' } },
          { status: 503 },
        ),
    })
    render(<App />)

    expect(await screen.findByText(/历史问答加载失败/)).toBeInTheDocument()
    expect(screen.getByText(/历史服务不可用/)).toBeInTheDocument()

    // 主流程不受影响：文档列表正常、问答仍可提交
    expect(await screen.findByText('讲义.pdf')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText(/ADD 指令/), '资源调度问题')
    await user.click(screen.getByRole('button', { name: '开始问答' }))
    expect(await screen.findByText('重点')).toBeInTheDocument()
    expect(screen.getByTestId('scope-chip')).toHaveTextContent('全课程')
  })
})

/* -------------------------------------------------------------------------- */
/*  Markdown / LaTeX 渲染                                                      */
/* -------------------------------------------------------------------------- */

describe('AnswerMarkdown', () => {
  it('渲染 GFM 表格、Markdown 强调与 LaTeX 公式', async () => {
    render(
      <AnswerMarkdown
        content={
          '**重点** 内容\n\n| 步骤 | 说明 |\n| --- | --- |\n| T1 | 取指 |\n\n公式 $E=mc^2$。'
        }
      />,
    )

    expect(await screen.findByText('重点')).toBeInTheDocument()
    expect(screen.getByText('重点').tagName).toBe('STRONG')
    expect(screen.getByText('取指').tagName).toBe('TD')
    expect(document.querySelector('.katex')).not.toBeNull()
    expect(screen.getByTestId('answer-markdown')).toBeInTheDocument()
  })

  it('skipHtml 禁止答案中的原始 HTML（防 XSS）', () => {
    const { container } = render(
      <AnswerMarkdown
        content={'<script>window.__hacked = 1</script>\n\n<img src="x" onerror="window.__hacked = 2">\n\n**安全文本**'}
      />,
    )

    expect((window as unknown as { __hacked?: number }).__hacked).toBeUndefined()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('安全文本')).toBeInTheDocument()
  })

  it('清洗会破坏渲染管线的控制字符', () => {
    expect(sanitizeAnswerText('A\u0000B\u0001C\u007F')).toBe('A B C ')
    expect(sanitizeAnswerText('保留\t制表与\n换行')).toBe('保留\t制表与\n换行')

    render(<AnswerMarkdown content={'前\u0000后'} />)
    expect(screen.getByText('前 后')).toBeInTheDocument()
  })
})
