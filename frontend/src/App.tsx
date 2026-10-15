import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle, Check, ChevronDown, CircleHelp, FileText, LoaderCircle, MessageSquare,
  RefreshCw, Search, Server, Trash2, UploadCloud, X,
} from 'lucide-react'
import {
  ApiError, askQuestion, deleteDocument, DocumentSummary, getDocuments, getOcrHealth,
  QueryResponse, uploadDocument,
} from './api'

const DEFAULT_COURSE = 'CS-COMP-ORG'

function errorText(error: unknown) {
  if (error instanceof ApiError) {
    const retry = error.status === 429 || error.status === 503 ? ' 请稍后重试。' : ''
    return `${error.message}${retry}`
  }
  return error instanceof Error ? error.message : '网络请求失败，请检查服务是否运行。'
}

function formatType(type: string) {
  return type.toLowerCase() === 'pptx' ? 'PPTX' : 'PDF'
}

export default function App() {
  const [courseCode, setCourseCode] = useState(DEFAULT_COURSE)
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [selectedDocument, setSelectedDocument] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploadState, setUploadState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [uploadMessage, setUploadMessage] = useState('')
  const [uploadResult, setUploadResult] = useState<{ id: string; pages: number; chunks: number } | null>(null)
  const [listState, setListState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [listError, setListError] = useState('')
  const [ocr, setOcr] = useState<{ status: string; error?: string | null } | null>(null)
  const [ocrState, setOcrState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(5)
  const [queryState, setQueryState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [queryError, setQueryError] = useState<{ message: string; requestId?: string }>({ message: '' })
  const [answer, setAnswer] = useState<QueryResponse | null>(null)
  const listRequest = useRef<AbortController | null>(null)
  const queryRequest = useRef<AbortController | null>(null)

  const loadDocuments = async (course = courseCode) => {
    listRequest.current?.abort()
    const controller = new AbortController()
    listRequest.current = controller
    setListState('loading')
    setListError('')
    try {
      const next = await getDocuments(course.trim(), controller.signal)
      if (!controller.signal.aborted) {
        setDocuments(next)
        setSelectedDocument((current) => next.some((doc) => doc.document_id === current) ? current : '')
        setListState('idle')
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        setListState('error')
        setListError(errorText(error))
      }
    }
  }

  useEffect(() => {
    void loadDocuments(DEFAULT_COURSE)
    const controller = new AbortController()
    getOcrHealth(controller.signal).then((data) => {
      setOcr(data)
      setOcrState('ready')
    }).catch(() => setOcrState('error'))
    return () => {
      controller.abort()
      listRequest.current?.abort()
      queryRequest.current?.abort()
    }
  }, [])

  const onCourseChange = (value: string) => {
    setCourseCode(value)
    setSelectedDocument('')
    setAnswer(null)
  }

  const submitUpload = async () => {
    if (!file || !courseCode.trim()) return
    setUploadState('loading')
    setUploadMessage('')
    setUploadResult(null)
    try {
      const result = await uploadDocument(file, courseCode.trim())
      setUploadState('success')
      setUploadResult({ id: result.document_id, pages: result.pages, chunks: result.chunks })
      setUploadMessage(`已完成 ${formatType(file.name.split('.').pop() ?? '')} 文本解析`)
      setFile(null)
      await loadDocuments(courseCode.trim())
    } catch (error) {
      setUploadState('error')
      setUploadMessage(errorText(error))
    }
  }

  const submitQuery = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!question.trim() || !courseCode.trim()) return
    queryRequest.current?.abort()
    const controller = new AbortController()
    queryRequest.current = controller
    setQueryState('loading')
    setQueryError({ message: '' })
    setAnswer(null)
    try {
      const result = await askQuestion({
        question: question.trim(),
        course_code: courseCode.trim(),
        ...(selectedDocument ? { document_id: selectedDocument } : {}),
        top_k: topK,
      }, controller.signal)
      if (!controller.signal.aborted) {
        setAnswer(result)
        setQueryState('success')
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        setQueryState('error')
        setQueryError({ message: errorText(error), requestId: error instanceof ApiError ? error.requestId : undefined })
      }
    }
  }

  const removeDocument = async (document: DocumentSummary) => {
    if (!window.confirm(`确定删除“${document.filename}”吗？此操作不可撤销。`)) return
    try {
      await deleteDocument(document.document_id)
      if (selectedDocument === document.document_id) setSelectedDocument('')
      await loadDocuments(courseCode)
    } catch (error) {
      setListState('error')
      setListError(errorText(error))
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark"><FileText size={19} /></div><div><strong>EduRAG</strong><span>课程知识库</span></div></div>
        <div className="topbar-meta"><span className="live-dot" /> 本地服务 <span className="separator">/</span> 文档问答工作台</div>
      </header>
      <main className="workspace">
        <section className="hero">
          <div><p className="eyebrow">COURSE KNOWLEDGE WORKSPACE</p><h1>让课程资料，<em>可被问到。</em></h1><p className="hero-copy">上传课程文档，按课程或单份资料检索，用有来源的回答快速定位知识。</p></div>
          <div className="ocr-panel" data-testid="ocr-status">
            <div className="status-icon"><Server size={17} /></div>
            <div><span className="label">OCR 引擎</span><strong>{ocrState === 'loading' ? '检测中…' : ocrState === 'error' ? '无法检测' : ocr?.status === 'ok' ? '可用' : ocr?.status === 'disabled' ? '已关闭' : '不可用'}</strong></div>
            {ocr?.status === 'ok' && <Check size={16} className="status-ok" />}
            {ocr?.status === 'unavailable' && <AlertCircle size={16} className="status-warn" />}
          </div>
        </section>

        <section className="grid-layout">
          <div className="left-column">
            <section className="panel upload-panel">
              <div className="section-head"><div><span className="section-kicker">01 / INGEST</span><h2>添加课程文档</h2></div><CircleHelp size={17} className="muted" /></div>
              <div className="field"><label htmlFor="course-code">课程代码</label><input id="course-code" value={courseCode} onChange={(e) => onCourseChange(e.target.value)} placeholder="例如 CS-COMP-ORG" /></div>
              <label className={`dropzone ${file ? 'has-file' : ''}`} htmlFor="file-upload">
                <input id="file-upload" type="file" accept=".pdf,.pptx,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setUploadState('idle'); setUploadResult(null) }} />
                <UploadCloud size={24} />
                <strong>{file ? file.name : '选择或拖入 PDF / PPTX'}</strong>
                <span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : '支持课程讲义和演示文稿'}</span>
              </label>
              <div className="file-note"><span>PDF 扫描页依赖 OCR 引擎</span><span>PPTX 仅解析文本内容</span></div>
              <button className="primary-button" onClick={() => void submitUpload()} disabled={!file || !courseCode.trim() || uploadState === 'loading'}><UploadCloud size={16} />{uploadState === 'loading' ? '正在处理…' : '上传并建立索引'}</button>
              {uploadState === 'success' && uploadResult && <div className="notice success"><Check size={16} /><div><strong>文档已加入课程</strong><span>{uploadMessage} · {uploadResult.pages} 页 · {uploadResult.chunks} 个 chunks · ID {uploadResult.id}</span></div></div>}
              {uploadState === 'error' && <div className="notice error"><AlertCircle size={16} /><span>{uploadMessage}</span></div>}
              {ocr?.status === 'unavailable' && <div className="notice warning"><AlertCircle size={16} /><span>OCR 不可用，扫描内容可能无法提取。{ocr.error ? ` ${ocr.error}` : ''}</span></div>}
              {ocr?.status === 'disabled' && <div className="notice warning"><AlertCircle size={16} /><span>OCR 已关闭，扫描 PDF 可能无法提取文字。</span></div>}
            </section>

            <section className="panel documents-panel">
              <div className="section-head"><div><span className="section-kicker">02 / LIBRARY</span><h2>课程文档 <small>{documents.length}</small></h2></div><button className="icon-button" title="刷新文档列表" onClick={() => void loadDocuments()}><RefreshCw size={16} className={listState === 'loading' ? 'spin' : ''} /></button></div>
              <div className="list-toolbar"><span>当前课程</span><strong>{courseCode || '未填写'}</strong><button onClick={() => void loadDocuments()}><Search size={14} /> 查询</button></div>
              {listState === 'error' && <div className="inline-error"><AlertCircle size={15} />{listError}</div>}
              {listState === 'loading' && documents.length === 0 ? <div className="empty-state"><LoaderCircle className="spin" size={21} />加载文档中…</div> : documents.length === 0 ? <div className="empty-state"><FileText size={22} /><span>该课程还没有文档</span><small>上传后，文档会出现在这里</small></div> : <div className="document-list">
                {documents.map((doc) => <div className={`document-row ${selectedDocument === doc.document_id ? 'selected' : ''}`} key={doc.document_id} onClick={() => setSelectedDocument(selectedDocument === doc.document_id ? '' : doc.document_id)}>
                  <div className={`file-icon ${doc.file_type.toLowerCase()}`}>{formatType(doc.file_type)}</div><div className="doc-info"><strong title={doc.filename}>{doc.filename}</strong><span>{doc.status} · {doc.page_count} 页 · {doc.chunk_count} chunks</span></div><button className="delete-button" title={`删除 ${doc.filename}`} onClick={(e) => { e.stopPropagation(); void removeDocument(doc) }}><Trash2 size={15} /></button><ChevronDown size={15} className={`row-chevron ${selectedDocument === doc.document_id ? 'open' : ''}`} /></div>)}
              </div>}
              {selectedDocument && <div className="selection-note"><Check size={14} />问答将限定在：<strong>{documents.find((doc) => doc.document_id === selectedDocument)?.filename}</strong><button onClick={() => setSelectedDocument('')}><X size={14} /></button></div>}
            </section>
          </div>

          <section className="panel qa-panel">
            <div className="section-head"><div><span className="section-kicker">03 / ASK</span><h2>课程问答</h2></div><div className="scope-chip"><MessageSquare size={14} />{selectedDocument ? '单份文档' : '全课程'}</div></div>
            <form onSubmit={submitQuery}>
              <label className="question-box"><span>你的问题</span><textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="例如：ADD 指令的微地址序列是什么？" rows={5} /></label>
              <div className="query-controls"><label>检索数量 <input type="number" min="1" max="20" value={topK} onChange={(e) => setTopK(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} /></label><span className="query-hint">按课程 <strong>{courseCode || '—'}</strong> 检索</span><button className="primary-button" type="submit" disabled={!question.trim() || !courseCode.trim() || queryState === 'loading'}><MessageSquare size={16} />{queryState === 'loading' ? '检索与生成中…' : '开始问答'}</button></div>
            </form>
            {queryState === 'error' && <div className="notice error"><AlertCircle size={16} /><div><span>{queryError.message}</span>{queryError.requestId && <small>request_id <code>{queryError.requestId}</code></small>}<small>请确认后端服务状态；429/503 错误可稍后重试。</small></div></div>}
            {queryState === 'loading' && <div className="answer-loading"><LoaderCircle className="spin" size={20} /><div><strong>正在查找相关内容</strong><span>答案生成完成前，请稍候…</span></div></div>}
            {answer && queryState === 'success' && <div className="answer-area"><div className="answer-meta"><span>回答</span><span>{answer.model} · {Math.round(answer.latency_ms)} ms</span></div><div className="answer-text">{answer.answer}</div><div className="citation-head"><h3>来源 <small>{answer.citations.length}</small></h3><span>分数为检索相关性，不是概率</span></div><div className="citations">{answer.citations.length === 0 ? <div className="empty-citations">没有返回引用来源。</div> : answer.citations.map((citation, index) => <CitationCard citation={citation} index={index} key={`${citation.document_id}-${citation.page}-${index}`} />)}</div><div className="request-id">request_id <code>{answer.request_id}</code></div></div>}
            {queryState === 'idle' && !answer && <div className="qa-empty"><MessageSquare size={28} /><strong>问一个课程问题</strong><span>回答会附带文档、页码和检索片段，方便回到原文核对。</span></div>}
          </section>
        </section>
      </main>
    </div>
  )
}

function CitationCard({ citation, index }: { citation: import('./api').Citation; index: number }) {
  const sourceText = citation.text_sources?.join(' · ') || (citation.page_used_ocr || citation.modality === 'ocr' ? 'OCR' : citation.modality || '文本')
  return <article className="citation-card"><div className="citation-index">{String(index + 1).padStart(2, '0')}</div><div className="citation-content"><div className="citation-title"><strong>{citation.filename || '未命名文档'}</strong><span>{citation.file_type?.toUpperCase() || 'DOC'} · {citation.page != null ? `第 ${citation.page} 页` : '页码未知'}</span></div><p>{citation.snippet || '暂无来源文本'}</p><div className="citation-tags"><span>{sourceText}</span>{citation.block_type && <span>{citation.block_type}</span>}{citation.score != null && <span>score {Number(citation.score).toFixed(3)}</span>}</div></div></article>
}
