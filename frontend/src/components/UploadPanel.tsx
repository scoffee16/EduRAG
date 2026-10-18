import { useRef, useState } from 'react'
import { CloudUpload, FileUp, RotateCcw, Square, UploadCloud } from 'lucide-react'
import type { DocumentDetail, DocumentProgress, OcrHealth } from '../api'
import { fileExtension, formatFileType, stageLabel, stagePercent } from '../format'
import StatusNotice from './StatusNotice'

export type UploadPhase =
  | 'idle'
  | 'uploading'
  | 'processing'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'error'

const ACCEPT =
  '.pdf,.pptx,.docx,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

const BUSY_PHASES: UploadPhase[] = ['uploading', 'processing']

interface UploadPanelProps {
  courseCode: string
  courseName?: string
  file: File | null
  phase: UploadPhase
  progress: DocumentProgress | null
  detail: DocumentDetail | null
  errorMessage: string
  errorCode?: string | null
  requestId?: string | null
  ocr: OcrHealth | null
  ocrState: 'loading' | 'ready' | 'error'
  onFileChange: (file: File | null) => void
  onUpload: () => void
  onRetry: () => void
  onCancelPolling: () => void
  onRefreshLists: () => void
}

/** 上传面板：支持 PDF / PPTX / DOCX，异步上传后展示阶段进度。 */
export default function UploadPanel({
  courseCode,
  courseName,
  file,
  phase,
  progress,
  detail,
  errorMessage,
  errorCode,
  requestId,
  ocr,
  ocrState,
  onFileChange,
  onUpload,
  onRetry,
  onCancelPolling,
  onRefreshLists,
}: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragActive, setDragActive] = useState(false)
  const busy = BUSY_PHASES.includes(phase)
  const oldDoc = file != null && fileExtension(file.name) === 'doc'
  const currentType = formatFileType(detail?.file_type ?? (file ? fileExtension(file.name) : ''))
  const percent = stagePercent(progress)
  const canUpload = Boolean(file) && Boolean(courseCode.trim()) && !busy && !oldDoc

  const pickFile = (next: File | null) => {
    onFileChange(next)
    setDragActive(false)
  }

  return (
    <section className="panel upload-panel">
      <div className="panel-head">
        <div>
          <span className="section-kicker">01 / INGEST</span>
          <h2>添加课程文档</h2>
        </div>
        <UploadCloud size={18} className="muted" aria-hidden="true" />
      </div>
      <p className="panel-hint">
        上传到：
        <strong>{courseName || courseCode || '未选择课程'}</strong>
        {courseName && courseCode && <code>{courseCode}</code>}
      </p>

      <label
        className={`dropzone ${file ? 'has-file' : ''} ${dragActive ? 'drag-active' : ''}`}
        htmlFor="file-upload"
        onDragOver={(event) => {
          event.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault()
          const dropped = event.dataTransfer?.files?.[0] ?? null
          if (dropped) pickFile(dropped)
          else setDragActive(false)
        }}
      >
        <input
          ref={inputRef}
          id="file-upload"
          type="file"
          accept={ACCEPT}
          onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
        />
        <span className="dropzone-icon" aria-hidden="true">
          {file ? <FileUp size={24} /> : <CloudUpload size={24} />}
        </span>
        <strong>{file ? file.name : '选择或拖入 PDF / PPTX / DOCX'}</strong>
        <span>
          {file
            ? `${currentType} · ${(file.size / 1024 / 1024).toFixed(2)} MB`
            : '课程讲义、演示文稿与 Word 文档'}
        </span>
      </label>
      <div className="file-note">
        <span>PDF 扫描页依赖 OCR 引擎</span>
        <span>PPTX / DOCX 仅解析文本内容</span>
      </div>

      {oldDoc && (
        <StatusNotice tone="warning" title="暂不支持旧版 .doc">
          请用 Word / WPS 另存为 .docx 后再上传。
        </StatusNotice>
      )}

      <button
        className="primary-button upload-button"
        onClick={onUpload}
        disabled={!canUpload}
      >
        <UploadCloud size={16} />
        {busy ? '正在解析并向量化，大文件可能需要数分钟' : '上传并建立索引'}
      </button>

      {busy && (
        <div className="upload-progress" role="status">
          <div className="progress-head">
            <strong>{stageLabel(progress)}</strong>
            <span>{percent != null ? `${percent}%` : '处理中'}</span>
          </div>
          <div className={`progress-track ${percent == null ? 'indeterminate' : ''}`}>
            <div
              className="progress-bar"
              style={percent != null ? { width: `${percent}%` } : undefined}
            />
          </div>
          <div className="progress-foot">
            <span title={detail?.filename ?? file?.name ?? ''}>
              {detail?.filename ?? file?.name}
            </span>
            <button className="text-button" onClick={onCancelPolling}>
              <Square size={12} aria-hidden="true" /> 中止轮询
            </button>
          </div>
        </div>
      )}

      {phase === 'success' && (
        <StatusNotice tone="success" title="文档已建立索引" requestId={requestId}>
          <span>
            {detail?.filename ?? file?.name ?? '文档'} · {detail?.page_count ?? 0} 页 ·{' '}
            {detail?.chunk_count ?? 0} chunks
          </span>
        </StatusNotice>
      )}

      {phase === 'failed' && (
        <StatusNotice
          tone="error"
          title={`文档处理失败${errorCode ? `（${errorCode}）` : ''}`}
          requestId={requestId}
        >
          <span>解析或向量化过程中断，可重试上传；若持续失败请带上 request_id 查看后端日志。</span>
          <div className="notice-actions">
            <button className="text-button" onClick={onRetry} disabled={!file}>
              <RotateCcw size={12} aria-hidden="true" /> 重试上传
            </button>
          </div>
        </StatusNotice>
      )}

      {phase === 'timeout' && (
        <StatusNotice tone="warning" title="处理超时（超过 10 分钟）" requestId={requestId}>
          <span>
            文档可能仍在后台处理，可稍后刷新文档列表；也可用 request_id 在 API 日志窗口排查。
          </span>
          <div className="notice-actions">
            <button className="text-button" onClick={onRefreshLists}>
              刷新列表
            </button>
            <button className="text-button" onClick={onRetry} disabled={!file}>
              <RotateCcw size={12} aria-hidden="true" /> 重新上传
            </button>
          </div>
        </StatusNotice>
      )}

      {phase === 'cancelled' && (
        <StatusNotice tone="info" title="已中止进度轮询">
          <span>文档可能仍在后台解析，可稍后点击「刷新列表」查看结果。</span>
          <div className="notice-actions">
            <button className="text-button" onClick={onRefreshLists}>
              刷新列表
            </button>
          </div>
        </StatusNotice>
      )}

      {phase === 'error' && (
        <StatusNotice tone="error" title="上传失败" requestId={requestId}>
          <span>{errorMessage}</span>
          {errorCode && <small>错误码 {errorCode}</small>}
          <div className="notice-actions">
            <button className="text-button" onClick={onRetry} disabled={!file}>
              <RotateCcw size={12} aria-hidden="true" /> 重试上传
            </button>
          </div>
        </StatusNotice>
      )}

      {ocrState === 'loading' && <p className="panel-hint muted">正在检测 OCR 引擎…</p>}
      {ocr?.status === 'unavailable' && (
        <StatusNotice tone="warning">
          OCR 不可用，扫描内容可能无法提取。{ocr.error ? ` ${ocr.error}` : ''}
        </StatusNotice>
      )}
      {ocr?.status === 'disabled' && (
        <StatusNotice tone="warning">OCR 已关闭，扫描 PDF 可能无法提取文字。</StatusNotice>
      )}
    </section>
  )
}
