import type { DocumentProgress } from './api'

/** 取文件扩展名（小写，不含点）。 */
export function fileExtension(filename: string): string {
  const name = (filename ?? '').toLowerCase()
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index + 1) : ''
}

/** 把 file_type / 扩展名统一成 UI 徽标文案。 */
export function formatFileType(fileType?: string | null): string {
  const normalized = (fileType ?? '').toLowerCase().replace(/^\./, '')
  if (!normalized) return '文档'
  if (normalized === 'pptx' || normalized === 'ppt') return 'PPTX'
  if (normalized === 'docx' || normalized === 'doc') return 'DOCX'
  if (normalized === 'pdf') return 'PDF'
  return normalized.toUpperCase()
}

/** 文件徽标配色用的 class 后缀。 */
export function fileTypeClass(fileType?: string | null): string {
  const normalized = (fileType ?? '').toLowerCase()
  return normalized === 'pdf' || normalized === 'pptx' || normalized === 'docx' ? normalized : 'other'
}

/** DOCX 没有真实页码，页数按「节」展示。 */
export function formatDocumentMeta(
  fileType: string | null | undefined,
  pageCount?: number | null,
  chunkCount?: number | null,
): string {
  const unit = (fileType ?? '').toLowerCase() === 'docx' ? '节' : '页'
  return `${pageCount ?? 0} ${unit} · ${chunkCount ?? 0} chunks`
}

/** 引用位置：DOCX 显示「第 N 节」，PDF/PPTX 显示「第 N 页」。 */
export function formatCitationLocation(
  fileType: string | null | undefined,
  page?: number | string | null,
): string {
  if (page == null || page === '') return '位置未知'
  const unit = (fileType ?? '').toLowerCase() === 'docx' ? '节' : '页'
  return `第 ${page} ${unit}`
}

const STAGE_PERCENT: Record<string, number> = { parse: 8, chunk: 26, store: 95 }

/** 阶段文案：解析中 / 分块中 / 向量化 n/m / 写入索引。 */
export function stageLabel(progress: DocumentProgress | null | undefined): string {
  if (!progress) return '等待处理…'
  switch (progress.stage) {
    case 'parse':
      return '解析文档中…'
    case 'chunk':
      return '切分文本块中…'
    case 'embed':
      return progress.total > 0 ? `向量化 ${progress.done}/${progress.total}` : '向量化中…'
    case 'store':
      return '写入索引中…'
    default:
      return progress.stage ? `处理中（${progress.stage}）…` : '处理中…'
  }
}

/** 本地时钟文案（HH:MM:SS），用于「文档列表已刷新（HH:MM:SS）」提示。 */
export function formatClock(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** 进度百分比；无法计算（total 未知）时返回 null，UI 用不确定进度条。 */
export function stagePercent(progress: DocumentProgress | null | undefined): number | null {
  if (!progress) return null
  if (progress.stage === 'embed') {
    if (!progress.total) return null
    const ratio = Math.max(0, Math.min(1, progress.done / progress.total))
    return Math.min(94, 40 + Math.round(ratio * 54))
  }
  return STAGE_PERCENT[progress.stage] ?? null
}
