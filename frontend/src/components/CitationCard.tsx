import type { Citation } from '../api'
import { formatCitationLocation, formatFileType } from '../format'

interface CitationCardProps {
  citation: Citation
  index: number
}

const MODALITY_LABELS: Record<string, string> = {
  text: '文本',
  ocr: 'OCR',
  image: '图片',
  mixed: '文本+OCR',
}

const BLOCK_TYPE_LABELS: Record<string, string> = {
  figure: '图形结构',
  table: '表格',
  code: '代码块',
  caption: '图注',
  title: '标题',
  paragraph: '正文',
}

const TEXT_SOURCE_LABELS: Record<string, string> = {
  vlm: 'VLM 识别',
  text: '正文',
  ocr: 'OCR',
}

function modalityLabel(key: string | null | undefined): string {
  if (!key) {
    return ''
  }
  return MODALITY_LABELS[key] ?? key
}

function blockTypeLabel(key: string | null | undefined): string {
  if (!key) {
    return ''
  }
  return BLOCK_TYPE_LABELS[key] ?? key
}

/** 引用来源卡片：文档、位置（DOCX 为节）、匹配分与检索片段（纯文本）。 */
export default function CitationCard({ citation, index }: CitationCardProps) {
  const labelledSources = citation.text_sources?.map((source) => TEXT_SOURCE_LABELS[source] ?? source)
  const sourceText =
    (labelledSources && labelledSources.length > 0 ? labelledSources.join(' · ') : '') ||
    (citation.page_used_ocr || citation.modality === 'ocr'
      ? 'OCR'
      : modalityLabel(citation.modality) || '文本')
  const blockType = blockTypeLabel(citation.block_type)

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
          {blockType && <span>{blockType}</span>}
          {citation.score != null && <span>score {Number(citation.score).toFixed(3)}</span>}
        </div>
      </div>
    </article>
  )
}
