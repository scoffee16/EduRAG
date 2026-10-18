import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { FileText, Server } from 'lucide-react'
import {
  ApiError,
  askQuestion,
  createCourse,
  deleteCourse,
  deleteDocument,
  getCourses,
  getDocument,
  getDocuments,
  getHistory,
  getOcrHealth,
  uploadDocument,
  type CourseSummary,
  type DocumentDetail,
  type DocumentProgress,
  type DocumentSummary,
  type HistoryItem,
  type OcrHealth,
  type QueryResponse,
} from './api'
import { fileExtension, formatClock } from './format'
import AskPanel from './components/AskPanel'
import CourseSelect from './components/CourseSelect'
import DocumentList from './components/DocumentList'
import HistoryPanel from './components/HistoryPanel'
import StatusNotice, { type NoticeTone } from './components/StatusNotice'
import UploadPanel, { type UploadPhase } from './components/UploadPanel'

const DEFAULT_POLL_INTERVAL_MS = 1500
const DEFAULT_UPLOAD_TIMEOUT_MS = 10 * 60 * 1000
/** 文档列表刷新成功提示的展示时长（2-3 秒后自动消失）。 */
const DEFAULT_REFRESH_NOTICE_MS = 2600

export interface AppProps {
  /** 上传进度轮询间隔，测试可调小；生产默认 1.5s。 */
  pollIntervalMs?: number
  /** 上传进度超时时间，测试可调小；生产默认 10 分钟。 */
  uploadTimeoutMs?: number
  /** 文档列表刷新成功提示的展示时长；生产默认 2.6s。 */
  refreshNoticeMs?: number
}

export function errorText(error: unknown) {
  if (error instanceof ApiError) {
    const retry = error.status === 429 || error.status === 503 ? ' 请稍后重试。' : ''
    return `${error.message}${retry}`
  }
  return error instanceof Error ? error.message : '网络请求失败，请检查服务是否运行。'
}

interface UploadJob {
  document_id: string
  filename: string
  course_code: string
  request_id?: string | null
  started_at: number
}

/** 课程创建/删除操作的结果提示（成功或失败）。 */
interface CourseNotice {
  tone: NoticeTone
  title: string
  message: string
}

const BUSY_PHASES: UploadPhase[] = ['uploading', 'processing']

/**
 * 页面状态编排：
 * - 课程下拉（GET /api/v1/courses）→ 切换即重载文档、清空选中与上一次回答；
 * - 上传（POST /api/v1/upload，202）→ 每 1.5s 轮询 GET /api/v1/documents/{id}
 *   展示 parse/chunk/embed/store 阶段进度，indexed 后刷新课程与文档；
 * - 问答（POST /api/v1/query）→ Markdown / LaTeX 渲染答案与来源。
 */
export default function App({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  uploadTimeoutMs = DEFAULT_UPLOAD_TIMEOUT_MS,
  refreshNoticeMs = DEFAULT_REFRESH_NOTICE_MS,
}: AppProps = {}) {
  const [courses, setCourses] = useState<CourseSummary[]>([])
  const [coursesState, setCoursesState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [coursesError, setCoursesError] = useState('')
  const [manualCourse, setManualCourse] = useState(false)
  const [courseCode, setCourseCode] = useState('')
  // 手动新建课程：双输入框 + 创建中/错误提示；创建成功前不把输入值当作 courseCode
  const [manualCode, setManualCode] = useState('')
  const [manualName, setManualName] = useState('')
  const [creatingCourse, setCreatingCourse] = useState(false)
  const [createCourseError, setCreateCourseError] = useState('')
  const [deletingCourse, setDeletingCourse] = useState(false)
  const [courseNotice, setCourseNotice] = useState<CourseNotice | null>(null)

  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [listState, setListState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [listError, setListError] = useState('')
  // 限定检索的文档（多选，1..N 篇；为空表示检索全课程）
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([])
  // 手动刷新文档列表成功后的 transient 提示（2-3 秒自动消失）
  const [listNotice, setListNotice] = useState('')
  const refreshNoticeTimer = useRef<number | null>(null)

  const [ocr, setOcr] = useState<OcrHealth | null>(null)
  const [ocrState, setOcrState] = useState<'loading' | 'ready' | 'error'>('loading')

  const [file, setFile] = useState<File | null>(null)
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>('idle')
  const [uploadProgress, setUploadProgress] = useState<DocumentProgress | null>(null)
  const [uploadDetail, setUploadDetail] = useState<DocumentDetail | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploadErrorCode, setUploadErrorCode] = useState<string | null>(null)
  const [uploadRequestId, setUploadRequestId] = useState<string | null>(null)
  const [uploadJob, setUploadJob] = useState<UploadJob | null>(null)

  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(5)
  const [queryState, setQueryState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [queryError, setQueryError] = useState<{ message: string; requestId?: string }>({
    message: '',
  })
  const [answer, setAnswer] = useState<QueryResponse | null>(null)

  // 历史问答（最近 20 条）：加载失败只在面板内提示，不打断主流程
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')

  const listRequest = useRef<AbortController | null>(null)
  const queryRequest = useRef<AbortController | null>(null)
  const courseRef = useRef(courseCode)
  courseRef.current = courseCode
  const uploadBusy = BUSY_PHASES.includes(uploadPhase)

  /** 立即清除「文档列表已刷新」提示及其定时器。 */
  const clearRefreshNotice = useCallback(() => {
    if (refreshNoticeTimer.current != null) {
      window.clearTimeout(refreshNoticeTimer.current)
      refreshNoticeTimer.current = null
    }
    setListNotice('')
  }, [])

  // 卸载时清理刷新提示定时器，避免对已卸载组件 setState
  useEffect(
    () => () => {
      if (refreshNoticeTimer.current != null) {
        window.clearTimeout(refreshNoticeTimer.current)
        refreshNoticeTimer.current = null
      }
    },
    [],
  )

  const loadCourses = useCallback(async (): Promise<CourseSummary[]> => {
    setCoursesState('loading')
    setCoursesError('')
    try {
      const list = await getCourses()
      setCourses(list)
      setCoursesState('ready')
      setManualCourse((manual) => {
        if (!manual) return manual
        const current = courseRef.current
        return !(current && list.some((course) => course.code === current))
      })
      return list
    } catch (error) {
      setCoursesState('error')
      setCoursesError(errorText(error))
      setManualCourse(true)
      return []
    }
  }, [])

  const loadDocuments = useCallback(
    async (course: string, options: { announce?: boolean } = {}) => {
      clearRefreshNotice()
      listRequest.current?.abort()
      if (!course.trim()) {
        setDocuments([])
        setSelectedDocuments([])
        setListState('idle')
        setListError('')
        return
      }
      const controller = new AbortController()
      listRequest.current = controller
      setListState('loading')
      setListError('')
      try {
        const next = await getDocuments(course.trim(), controller.signal)
        if (controller.signal.aborted) return
        setDocuments(next)
        // 刷新/切换课程后清理已失效的限定选择（如文档已被删除）
        setSelectedDocuments((current) =>
          current.filter((id) => next.some((document) => document.document_id === id)),
        )
        setListState('idle')
        if (options.announce) {
          setListNotice(`文档列表已刷新（${formatClock()}）`)
          refreshNoticeTimer.current = window.setTimeout(() => {
            refreshNoticeTimer.current = null
            setListNotice('')
          }, refreshNoticeMs)
        }
      } catch (error) {
        if ((error as Error).name === 'AbortError') return
        setListState('error')
        setListError(errorText(error))
      }
    },
    [clearRefreshNotice, refreshNoticeMs],
  )

  /** 加载最近问答记录；失败只在历史面板内提示，不打断问答/上传主流程。 */
  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const items = await getHistory(20, signal)
      if (signal?.aborted) return
      setHistory(items)
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      setHistoryError(errorText(error))
    } finally {
      if (!signal?.aborted) setHistoryLoading(false)
    }
  }, [])

  // 首次挂载：课程列表 + OCR 状态 + 历史问答
  useEffect(() => {
    const controller = new AbortController()
    void loadCourses()
    void loadHistory(controller.signal)
    getOcrHealth(controller.signal)
      .then((data) => {
        setOcr(data)
        setOcrState('ready')
      })
      .catch((error: unknown) => {
        if ((error as Error).name !== 'AbortError') setOcrState('error')
      })
    return () => {
      controller.abort()
      listRequest.current?.abort()
      queryRequest.current?.abort()
    }
  }, [loadCourses, loadHistory])

  // 课程列表就绪后默认选中第一门课程；没有课程则进入手动新建模式
  const initializedCourse = useRef(false)
  useEffect(() => {
    if (initializedCourse.current || coursesState !== 'ready') return
    initializedCourse.current = true
    if (courses.length > 0) setCourseCode(courses[0].code)
    else setManualCourse(true)
  }, [coursesState, courses])

  // 切换课程：立即重载文档列表，并清空限定选择与上一次回答。
  // 手动新建模式下 courseCode 为空，创建成功前不会用输入值请求文档。
  useEffect(() => {
    setSelectedDocuments([])
    setAnswer(null)
    setQueryState('idle')
    setQueryError({ message: '' })
    void loadDocuments(courseCode)
  }, [courseCode, loadDocuments])

  // 上传成功后轮询进度（1.5s 一次），indexed 刷新课程+文档，failed/超时给出可操作提示
  useEffect(() => {
    if (!uploadJob) return
    const controller = new AbortController()
    let stopped = false
    let timer: number | undefined
    const deadline = uploadJob.started_at + uploadTimeoutMs

    const stopPolling = () => {
      stopped = true
      if (timer != null) window.clearTimeout(timer)
      setUploadJob(null)
    }

    const poll = async () => {
      if (stopped) return
      if (Date.now() > deadline) {
        stopPolling()
        setUploadPhase('timeout')
        return
      }
      try {
        const detail = await getDocument(uploadJob.document_id, controller.signal)
        if (stopped) return
        setUploadDetail(detail)
        setUploadProgress(detail.progress ?? null)
        if (detail.request_id) setUploadRequestId(detail.request_id)
        if (detail.status === 'indexed') {
          stopped = true
          setUploadPhase('success')
          setUploadJob(null)
          setFile(null)
          void loadCourses()
          void loadDocuments(courseRef.current || uploadJob.course_code)
          return
        }
        if (detail.status === 'failed') {
          stopped = true
          setUploadPhase('failed')
          setUploadErrorCode(detail.error_code ?? null)
          setUploadJob(null)
          void loadDocuments(courseRef.current || uploadJob.course_code)
          return
        }
        timer = window.setTimeout(() => void poll(), pollIntervalMs)
      } catch (error) {
        if (stopped || (error as Error).name === 'AbortError') return
        stopped = true
        setUploadPhase('error')
        setUploadError(errorText(error))
        setUploadErrorCode(error instanceof ApiError ? error.code ?? null : null)
        setUploadRequestId(error instanceof ApiError ? (error.requestId ?? null) : null)
        setUploadJob(null)
      }
    }

    void poll()
    return () => {
      stopped = true
      controller.abort()
      if (timer != null) window.clearTimeout(timer)
    }
  }, [uploadJob, pollIntervalMs, uploadTimeoutMs, loadCourses, loadDocuments])

  const submitUpload = useCallback(async () => {
    if (!file || !courseCode.trim() || uploadBusy) return
    const uploadFile = file
    const course = courseCode.trim()
    setUploadPhase('uploading')
    setUploadProgress(null)
    setUploadDetail(null)
    setUploadError('')
    setUploadErrorCode(null)
    setUploadRequestId(null)
    try {
      const result = await uploadDocument(uploadFile, course)
      const filename = result.filename || uploadFile.name
      const requestId = result.request_id ?? null
      setUploadRequestId(requestId)
      setUploadDetail({
        document_id: result.document_id,
        filename,
        course_code: result.course_code || course,
        file_type: fileExtension(filename),
        status: result.status || 'processing',
        progress: null,
      })
      setUploadPhase('processing')
      setUploadJob({
        document_id: result.document_id,
        filename,
        course_code: result.course_code || course,
        request_id: requestId,
        started_at: Date.now(),
      })
    } catch (error) {
      setUploadPhase('error')
      setUploadError(errorText(error))
      setUploadErrorCode(error instanceof ApiError ? error.code ?? null : null)
      setUploadRequestId(error instanceof ApiError ? error.requestId ?? null : null)
      setUploadJob(null)
    }
  }, [file, courseCode, uploadBusy])

  const cancelPolling = () => {
    setUploadPhase('cancelled')
    setUploadJob(null)
  }

  const refreshLists = () => {
    void loadCourses()
    void loadDocuments(courseRef.current)
  }

  /** 进入手动新建课程：清空旧输入，创建成功前 courseCode 保持为空。 */
  const startManualCourse = () => {
    setManualCourse(true)
    setCourseCode('')
    setManualCode('')
    setManualName('')
    setCreateCourseError('')
    setCourseNotice(null)
  }

  /** 取消手动新建，回到下拉选择（优先恢复第一门课程）。 */
  const cancelManualCourse = () => {
    setManualCourse(false)
    setManualCode('')
    setManualName('')
    setCreateCourseError('')
    setCourseCode((current) => current || courses[0]?.code || '')
  }

  const selectCourse = (code: string) => {
    setManualCourse(false)
    setManualCode('')
    setManualName('')
    setCreateCourseError('')
    setCourseCode(code)
  }

  /** 创建课程：成功后刷新列表并选中；409 course_exists 时切换到已有课程。 */
  const submitCreateCourse = async () => {
    const code = manualCode.trim()
    const name = manualName.trim()
    if (!code || !name || creatingCourse) return
    setCreatingCourse(true)
    setCreateCourseError('')
    setCourseNotice(null)
    try {
      const created = await createCourse({ code, name })
      const list = await loadCourses()
      const selected = list.find((course) => course.code === created.code) ?? created
      setManualCourse(false)
      setManualCode('')
      setManualName('')
      setCourseCode(selected.code)
      setCourseNotice({
        tone: 'success',
        title: '课程已创建',
        message: `课程「${selected.name}（${selected.code}）」已创建，可上传文档并开始问答。`,
      })
    } catch (error) {
      if (error instanceof ApiError && error.code === 'course_exists') {
        const list = await loadCourses()
        const existing = list.find((course) => course.code === code)
        if (existing) {
          setManualCourse(false)
          setManualCode('')
          setManualName('')
          setCourseCode(existing.code)
          setCourseNotice({
            tone: 'info',
            title: '课程已存在，已切换',
            message: `已选中已有课程「${existing.name}（${existing.code}）」。`,
          })
        } else {
          setCreateCourseError(errorText(error))
        }
      } else {
        setCreateCourseError(errorText(error))
      }
    } finally {
      setCreatingCourse(false)
    }
  }

  /** 删除当前课程（force 级联删除文档/索引/文件），成功后选中剩余第一门课程。 */
  const removeCourse = async () => {
    const course = courses.find((item) => item.code === courseCode)
    if (!course || course.deletable !== true || deletingCourse) return
    const label = `${course.name}（${course.code}）`
    const prompt =
      course.document_count > 0
        ? `删除课程「${label}」将同时删除 ${course.document_count} 篇文档及其索引与文件，此操作不可撤销。确定删除？`
        : `确定删除课程「${label}」吗？此操作不可撤销。`
    if (!window.confirm(prompt)) return
    setDeletingCourse(true)
    setCourseNotice(null)
    try {
      await deleteCourse(course.code, { force: true })
      setSelectedDocuments([])
      setAnswer(null)
      setQueryState('idle')
      setQueryError({ message: '' })
      setDocuments([])
      const list = await loadCourses()
      const next = list[0] ?? null
      setCourseCode(next?.code ?? '')
      setManualCourse(false)
      setCourseNotice({
        tone: 'success',
        title: '课程已删除',
        message: `课程「${label}」及其文档、索引与文件已删除。`,
      })
    } catch (error) {
      const detail = errorText(error)
      const code = error instanceof ApiError && error.code ? `（${error.code}）` : ''
      setCourseNotice({
        tone: 'error',
        title: '删除课程失败',
        message: `${detail}${code}`,
      })
    } finally {
      setDeletingCourse(false)
    }
  }

  const submitQuery = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault()
    const code = courseCode.trim()
    if (!question.trim() || !code || queryState === 'loading') return
    queryRequest.current?.abort()
    const controller = new AbortController()
    queryRequest.current = controller
    setQueryState('loading')
    setQueryError({ message: '' })
    setAnswer(null)
    // 限定文档：有选择时传 1..N 个 document_ids；全课程则不传（兼容旧后端字段也不传）
    const documentIds = [...selectedDocuments]
    try {
      const result = await askQuestion(
        {
          question: question.trim(),
          course_code: code,
          ...(documentIds.length > 0 ? { document_ids: documentIds } : {}),
          top_k: topK,
        },
        controller.signal,
      )
      if (!controller.signal.aborted) {
        setAnswer(result)
        setQueryState('success')
        // 问答成功：后台刷新历史记录（失败不影响当前回答）
        void loadHistory()
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      setQueryState('error')
      setQueryError({
        message: errorText(error),
        requestId: error instanceof ApiError ? error.requestId : undefined,
      })
    }
  }

  const removeDocument = async (document: DocumentSummary) => {
    if (!window.confirm(`确定删除“${document.filename}”吗？此操作不可撤销。`)) return
    try {
      await deleteDocument(document.document_id)
      setSelectedDocuments((current) =>
        current.filter((documentId) => documentId !== document.document_id),
      )
      void loadCourses()
      await loadDocuments(courseRef.current)
    } catch (error) {
      setListState('error')
      setListError(errorText(error))
    }
  }

  /** 点击文档行：多选 toggle（限定检索范围）。 */
  const toggleDocument = (documentId: string) => {
    setSelectedDocuments((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    )
  }

  /** 恢复全课程检索：清空所有文档限定选择。 */
  const clearDocumentSelection = () => setSelectedDocuments([])

  /** 手动刷新文档列表：成功后展示 transient 提示（失败保留错误提示）。 */
  const refreshDocuments = useCallback(() => {
    void loadDocuments(courseRef.current, { announce: true })
  }, [loadDocuments])

  // 按选择顺序映射成文档摘要；文档被删除/刷新后自动收缩，保证计数一致
  const selectedDocumentSummaries = selectedDocuments
    .map((id) => documents.find((document) => document.document_id === id))
    .filter((document): document is DocumentSummary => document != null)
  const currentCourse = courses.find((course) => course.code === courseCode)
  const ocrLabel =
    ocrState === 'loading'
      ? 'OCR 检测中…'
      : ocrState === 'error'
        ? 'OCR 无法检测'
        : ocr?.status === 'ok'
          ? 'OCR 可用'
          : ocr?.status === 'disabled'
            ? 'OCR 已关闭'
            : 'OCR 不可用'

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <FileText size={18} aria-hidden="true" />
          </div>
          <div className="brand-text">
            <strong>EduRAG</strong>
            <span>课程知识库</span>
          </div>
        </div>
        <CourseSelect
          courses={courses}
          value={courseCode}
          manual={manualCourse}
          coursesState={coursesState}
          manualCode={manualCode}
          manualName={manualName}
          creating={creatingCourse}
          createError={createCourseError}
          deleting={deletingCourse}
          onSelectCourse={selectCourse}
          onStartManual={startManualCourse}
          onManualCodeChange={setManualCode}
          onManualNameChange={setManualName}
          onCreate={() => void submitCreateCourse()}
          onCancelManual={cancelManualCourse}
          onDeleteCourse={() => void removeCourse()}
        />
        <div className="topbar-status" data-testid="ocr-status">
          <Server size={14} aria-hidden="true" />
          <span className={`live-dot ${ocr?.status === 'ok' ? 'ok' : 'idle'}`} />
          <span>{ocrLabel}</span>
        </div>
      </header>

      <main className="workspace">
        {courseNotice && (
          <StatusNotice
            tone={courseNotice.tone}
            title={courseNotice.title}
            className="course-notice"
          >
            {courseNotice.message}
          </StatusNotice>
        )}
        {manualCourse && !courseCode && (
          <StatusNotice tone="info" title="请先创建课程">
            填写课程代码与课程名称并点击「创建课程」后，才能上传文档或开始问答。
          </StatusNotice>
        )}
        <section className="grid-layout">
          <div className="main-column">
            <AskPanel
              question={question}
              onQuestionChange={setQuestion}
              topK={topK}
              onTopKChange={setTopK}
              courseCode={courseCode}
              courseName={currentCourse?.name}
              selectedFilenames={selectedDocumentSummaries.map(
                (document) => document.filename,
              )}
              queryState={queryState}
              queryError={queryError}
              answer={answer}
              onSubmit={(event) => void submitQuery(event)}
            />
            <HistoryPanel items={history} loading={historyLoading} error={historyError} />
          </div>

          <aside className="side-column">
            {coursesState === 'error' && (
              <StatusNotice tone="warning" title="课程列表加载失败">
                {coursesError} 可在上方「手动新建课程」里输入课程代码与名称后创建或切换课程。
              </StatusNotice>
            )}
            <UploadPanel
              courseCode={courseCode}
              courseName={currentCourse?.name}
              file={file}
              phase={uploadPhase}
              progress={uploadProgress}
              detail={uploadDetail}
              errorMessage={uploadError}
              errorCode={uploadErrorCode}
              requestId={uploadRequestId}
              ocr={ocr}
              ocrState={ocrState}
              onFileChange={(next) => {
                setFile(next)
                if (!BUSY_PHASES.includes(uploadPhase)) {
                  setUploadPhase('idle')
                  setUploadDetail(null)
                  setUploadProgress(null)
                  setUploadError('')
                  setUploadErrorCode(null)
                }
              }}
              onUpload={() => void submitUpload()}
              onRetry={() => void submitUpload()}
              onCancelPolling={cancelPolling}
              onRefreshLists={refreshLists}
            />
            <DocumentList
              documents={documents}
              courses={courses}
              courseCode={courseCode}
              selectedDocuments={selectedDocuments}
              listState={listState}
              listError={listError}
              refreshNotice={listNotice}
              onToggle={toggleDocument}
              onClearSelection={clearDocumentSelection}
              onDelete={(document) => void removeDocument(document)}
              onRefresh={refreshDocuments}
            />
          </aside>
        </section>
      </main>
    </div>
  )
}
