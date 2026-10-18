import { FileText, RefreshCw, Search, Trash2, X } from 'lucide-react'
import type { CourseSummary, DocumentSummary } from '../api'
import { fileTypeClass, formatDocumentMeta, formatFileType } from '../format'
import StatusNotice from './StatusNotice'

interface DocumentListProps {
  documents: DocumentSummary[]
  courses: CourseSummary[]
  courseCode: string
  selectedDocument: string
  listState: 'idle' | 'loading' | 'error'
  listError: string
  onSelect: (documentId: string) => void
  onDelete: (document: DocumentSummary) => void
  onRefresh: () => void
}

/** 右侧课程文档列表：按课程显示，支持选择单文档限定问答与删除。 */
export default function DocumentList({
  documents,
  courses,
  courseCode,
  selectedDocument,
  listState,
  listError,
  onSelect,
  onDelete,
  onRefresh,
}: DocumentListProps) {
  const courseName = courses.find((course) => course.code === courseCode)?.name
  const selected = documents.find((document) => document.document_id === selectedDocument)
  const displayName = (document: DocumentSummary) =>
    document.course_name ?? courses.find((course) => course.code === document.course_code)?.name ?? '未命名课程'

  return (
    <section className="panel documents-panel">
      <div className="panel-head">
        <div>
          <span className="section-kicker">02 / LIBRARY</span>
          <h2>
            课程文档 <small>{documents.length}</small>
          </h2>
        </div>
        <button
          className="icon-button"
          title="刷新文档列表"
          aria-label="刷新文档列表"
          onClick={onRefresh}
        >
          <RefreshCw size={16} className={listState === 'loading' ? 'spin' : ''} />
        </button>
      </div>
      <div className="list-toolbar">
        <span>当前课程</span>
        <strong title={courseCode}>{courseName ? `${courseName}（${courseCode}）` : courseCode || '未选择'}</strong>
        <button className="text-button" onClick={onRefresh}>
          <Search size={14} aria-hidden="true" /> 查询
        </button>
      </div>

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
            const active = selectedDocument === document.document_id
            return (
              <div className={`document-row ${active ? 'selected' : ''}`} key={document.document_id}>
                <button
                  type="button"
                  className="document-main"
                  aria-pressed={active}
                  onClick={() => onSelect(document.document_id)}
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
                </button>
                <button
                  className="delete-button"
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

      {selected && (
        <div className="selection-note">
          <span>
            问答将限定在：<strong>{selected.filename}</strong>
          </span>
          <button className="text-button" onClick={() => onSelect(selected.document_id)}>
            <X size={13} aria-hidden="true" /> 取消限定
          </button>
        </div>
      )}
    </section>
  )
}
