import type { Citation } from '../api'
import { formatCitationLocation, formatFileType } from '../format'

interface CitationCardProps {
  citation: Citation
  index: number
}

/** 引用来源卡片：文档、位置（DOCX 为节）、匹配分与检索片段（纯文本）。 */
export default function CitationCard({ citation, index }: CitationCardProps) {
  const sourceText =
    citation.text_sources?.join(' · ') ||
    (citation.page_used_ocr || citation.modality === 'ocr' ? 'OCR' : citation.modality || '文本')

  return (
    <article className="citation-card">
      <div className="citation-index">{String(index + 1).padStart(2, '0')}</div>
      <div className="citation-content">
        <div className="citation-title">
          <strong>{citation.filename || '未命名文档'}</strong>
          <span>
            {formatFileType(citation.file_type)} ·{' '}
            {formatCitationLocation(citation.file_type, citation.page)}
          </span>
        </div>
        <p className="citation-snippet">{citation.snippet || '暂无来源文本'}</p>
        <div className="citation-tags">
          <span>{sourceText}</span>
          {citation.block_type && <span>{citation.block_type}</span>}
          {citation.score != null && <span>score {Number(citation.score).toFixed(3)}</span>}
        </div>
      </div>
    </article>
  )
}
