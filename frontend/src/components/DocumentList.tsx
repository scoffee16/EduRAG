import { Check, FileText, Lock, RefreshCw, Trash2, X } from 'lucide-react'
import type { CourseSummary, DocumentSummary } from '../api'
import { fileTypeClass, formatDocumentMeta, formatFileType } from '../format'
import StatusNotice from './StatusNotice'

interface DocumentListProps {
  documents: DocumentSummary[]
  courses: CourseSummary[]
  courseCode: string
  /** 限定检索的文档 ID（可多选；为空表示检索全课程）。 */
  selectedDocuments: string[]
  listState: 'idle' | 'loading' | 'error'
  listError: string
  /** 手动刷新文档列表成功后的 transient 提示（由 App 定时清除）。 */
  refreshNotice?: string
  onToggle: (documentId: string) => void
  onClearSelection: () => void
  onDelete: (document: DocumentSummary) => void
  onRefresh: () => void
}

/** 右侧课程文档列表：按课程显示，支持多选限定检索范围、刷新与删除。 */
export default function DocumentList({
  documents,
  courses,
  courseCode,
  selectedDocuments,
  listState,
  listError,
  refreshNotice = '',
  onToggle,
  onClearSelection,
  onDelete,
  onRefresh,
}: DocumentListProps) {
  const course = courses.find((item) => item.code === courseCode)
  const courseName = course?.name
  const selectedCount = selectedDocuments.length
  const selectedNames = selectedDocuments
    .map((id) => documents.find((document) => document.document_id === id)?.filename)
    .filter((name): name is string => Boolean(name))
  const displayName = (document: DocumentSummary) =>
    document.course_name ?? courses.find((item) => item.code === document.course_code)?.name ?? '未命名课程'

  return (
    <section className="panel documents-panel">
      <div className="panel-head">
        <div>
          <span className="section-kicker">02 / LIBRARY</span>
          <h2>
            课程文档 <small>{documents.length}</small>
          </h2>
        </div>
        <div className="panel-head-actions">
          {selectedCount > 0 && (
            <span className="selected-count-chip">已选 {selectedCount}</span>
          )}
          <button
            className="icon-button"
            type="button"
            title="刷新文档列表"
            aria-label="刷新文档列表"
            onClick={onRefresh}
          >
            <RefreshCw size={16} className={listState === 'loading' ? 'spin' : ''} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="list-toolbar">
        <span>当前课程</span>
        <strong title={courseCode}>{courseName ? `${courseName}（${courseCode}）` : courseCode || '未选择'}</strong>
      </div>

      {refreshNotice && (
        <StatusNotice tone="success" className="refresh-notice">
          <span aria-live="polite">{refreshNotice}</span>
        </StatusNotice>
      )}

      {course?.origin === 'config' && (
        <p className="config-course-note" data-testid="config-course-note">
          <Lock size={13} aria-hidden="true" />
          示例课程由配置文件同步生成，不能删除
        </p>
      )}

      <p className="list-hint" data-testid="document-scope-hint">
        {selectedCount === 0
          ? '点击文档可限定检索范围（可多选）；不选择时检索该课程的全部文档。'
          : `已选 ${selectedCount} 篇文档；再次点击已选文档可取消选择。`}
      </p>

      {listState === 'error' && (
        <StatusNotice tone="error" title="文档列表加载失败">
          {listError}
        </StatusNotice>
      )}

      {listState === 'loading' && documents.length === 0 && (
        <div className="skeleton-list" data-testid="document-skeleton">
          {[0, 1, 2].map((index) => (
            <div className="skeleton-row" key={index}>
              <span className="skeleton skeleton-badge" />
              <span className="skeleton skeleton-line" />
            </div>
          ))}
        </div>
      )}

      {!(listState === 'loading' && documents.length === 0) && documents.length === 0 && listState !== 'error' && (
        <div className="empty-state">
          <FileText size={22} aria-hidden="true" />
          <span>该课程还没有文档</span>
          <small>上传后，文档会出现在这里</small>
        </div>
      )}

      {documents.length > 0 && (
        <div className="document-list">
          {documents.map((document) => {
            const active = selectedDocuments.includes(document.document_id)
            return (
              <div className={`document-row ${active ? 'selected' : ''}`} key={document.document_id}>
                <button
                  type="button"
                  className="document-main"
                  aria-pressed={active}
                  title={active ? '再次点击取消限定' : '点击限定检索此文档（可多选）'}
                  onClick={() => onToggle(document.document_id)}
                >
                  <span className={`file-icon ${fileTypeClass(document.file_type)}`}>
                    {formatFileType(document.file_type)}
                  </span>
                  <span className="doc-info">
                    <strong title={document.filename}>{document.filename}</strong>
                    <span className="doc-meta">
                      {displayName(document)} · {document.course_code}
                    </span>
                    <span className="doc-meta">
                      {formatDocumentMeta(document.file_type, document.page_count, document.chunk_count)} ·{' '}
                      {document.status}
                    </span>
                  </span>
                  {active && <Check size={16} className="doc-selected-check" aria-hidden="true" />}
                </button>
                <button
                  className="delete-button"
                  type="button"
                  title={`删除 ${document.filename}`}
                  aria-label={`删除 ${document.filename}`}
                  onClick={() => onDelete(document)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            )
          })}
        </div>
      )}

      {selectedCount > 0 && (
        <div className="selection-note" data-testid="selection-note">
          <span>
            问答将限定在 {selectedCount} 篇文档：
            <strong title={selectedNames.join('、')}>
              {selectedNames.length > 1
                ? `${selectedNames[0]} 等 ${selectedCount} 篇`
                : selectedNames[0] ?? `${selectedCount} 篇文档`}
            </strong>
          </span>
          <button type="button" className="text-button" onClick={onClearSelection}>
            <X size={13} aria-hidden="true" /> 恢复全课程
          </button>
        </div>
      )}
    </section>
  )
}
