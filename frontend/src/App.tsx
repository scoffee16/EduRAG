import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { FileText, Server } from 'lucide-react'
import {
  ApiError,
  askQuestion,
  deleteDocument,
  getCourses,
  getDocument,
  getDocuments,
  getOcrHealth,
  uploadDocument,
  type CourseSummary,
  type DocumentDetail,
  type DocumentProgress,
  type DocumentSummary,
  type OcrHealth,
  type QueryResponse,
} from './api'
import { fileExtension } from './format'
import AskPanel from './components/AskPanel'
import CourseSelect from './components/CourseSelect'
import DocumentList from './components/DocumentList'
import StatusNotice from './components/StatusNotice'
import UploadPanel, { type UploadPhase } from './components/UploadPanel'

const DEFAULT_POLL_INTERVAL_MS = 1500
const DEFAULT_UPLOAD_TIMEOUT_MS = 10 * 60 * 1000

export interface AppProps {
  /** 上传进度轮询间隔，测试可调小；生产默认 1.5s。 */
  pollIntervalMs?: number
  /** 上传进度超时时间，测试可调小；生产默认 10 分钟。 */
  uploadTimeoutMs?: number
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
}: AppProps = {}) {
  const [courses, setCourses] = useState<CourseSummary[]>([])
  const [coursesState, setCoursesState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [coursesError, setCoursesError] = useState('')
  const [manualCourse, setManualCourse] = useState(false)
  const [courseCode, setCourseCode] = useState('')

  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [listState, setListState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [listError, setListError] = useState('')
  const [selectedDocument, setSelectedDocument] = useState('')

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

  const listRequest = useRef<AbortController | null>(null)
  const queryRequest = useRef<AbortController | null>(null)
  const courseRef = useRef(courseCode)
  courseRef.current = courseCode
  const uploadBusy = BUSY_PHASES.includes(uploadPhase)

  const loadCourses = useCallback(async () => {
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
    } catch (error) {
      setCoursesState('error')
      setCoursesError(errorText(error))
      setManualCourse(true)
    }
  }, [])

  const loadDocuments = useCallback(async (course: string) => {
    listRequest.current?.abort()
    if (!course.trim()) {
      setDocuments([])
      setSelectedDocument('')
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
      setSelectedDocument((current) =>
        next.some((document) => document.document_id === current) ? current : '',
      )
      setListState('idle')
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      setListState('error')
      setListError(errorText(error))
    }
  }, [])

  // 首次挂载：课程列表 + OCR 状态
  useEffect(() => {
    const controller = new AbortController()
    void loadCourses()
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
  }, [loadCourses])

  // 课程列表就绪后默认选中第一门课程；没有课程则进入手动新建模式
  const initializedCourse = useRef(false)
  useEffect(() => {
    if (initializedCourse.current || coursesState !== 'ready') return
    initializedCourse.current = true
    if (courses.length > 0) setCourseCode(courses[0].code)
    else setManualCourse(true)
  }, [coursesState, courses])

  // 切换课程：立即重载文档列表，并清空选中文档与上一次回答
  useEffect(() => {
    setSelectedDocument('')
    setAnswer(null)
    setQueryState('idle')
    setQueryError({ message: '' })
    if (!courseCode.trim()) {
      void loadDocuments('')
      return
    }
    if (!manualCourse) {
      void loadDocuments(courseCode)
      return
    }
    // 手动输入课程代码时防抖，避免每输入一个字符都请求一次
    const timer = window.setTimeout(() => void loadDocuments(courseCode), 400)
    return () => window.clearTimeout(timer)
  }, [courseCode, manualCourse, loadDocuments])

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
    try {
      const result = await askQuestion(
        {
          question: question.trim(),
          course_code: code,
          ...(selectedDocument ? { document_id: selectedDocument } : {}),
          top_k: topK,
        },
        controller.signal,
      )
      if (!controller.signal.aborted) {
        setAnswer(result)
        setQueryState('success')
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
      setSelectedDocument((current) =>
        current === document.document_id ? '' : current,
      )
      void loadCourses()
      await loadDocuments(courseRef.current)
    } catch (error) {
      setListState('error')
      setListError(errorText(error))
    }
  }

  const selectDocument = (documentId: string) => {
    setSelectedDocument((current) => (current === documentId ? '' : documentId))
  }

  const selectedDocumentSummary = documents.find(
    (document) => document.document_id === selectedDocument,
  )
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
          onSelectCourse={(code) => {
            setManualCourse(false)
            setCourseCode(code)
          }}
          onStartManual={() => {
            setManualCourse(true)
            setCourseCode('')
          }}
          onManualCodeChange={(code) => setCourseCode(code)}
        />
        <div className="topbar-status" data-testid="ocr-status">
          <Server size={14} aria-hidden="true" />
          <span className={`live-dot ${ocr?.status === 'ok' ? 'ok' : 'idle'}`} />
          <span>{ocrLabel}</span>
        </div>
      </header>

      <main className="workspace">
        <section className="grid-layout">
          <div className="main-column">
            <AskPanel
              question={question}
              onQuestionChange={setQuestion}
              topK={topK}
              onTopKChange={setTopK}
              courseCode={courseCode}
              courseName={currentCourse?.name}
              selectedFilename={selectedDocumentSummary?.filename}
              queryState={queryState}
              queryError={queryError}
              answer={answer}
              onSubmit={(event) => void submitQuery(event)}
            />
          </div>

          <aside className="side-column">
            {coursesState === 'error' && (
              <StatusNotice tone="warning" title="课程列表加载失败">
                {coursesError} 可在上方「手动新建课程」里输入已有课程代码继续使用。
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
              selectedDocument={selectedDocument}
              listState={listState}
              listError={listError}
              onSelect={selectDocument}
              onDelete={(document) => void removeDocument(document)}
              onRefresh={() => void loadDocuments(courseRef.current)}
            />
          </aside>
        </section>
      </main>
    </div>
  )
}
