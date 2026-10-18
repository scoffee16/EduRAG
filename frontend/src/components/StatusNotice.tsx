import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Info, TriangleAlert, type LucideIcon } from 'lucide-react'

export type NoticeTone = 'success' | 'warning' | 'error' | 'info'

const TONE_ICON: Record<NoticeTone, LucideIcon> = {
  success: CheckCircle2,
  warning: TriangleAlert,
  error: AlertCircle,
  info: Info,
}

interface StatusNoticeProps {
  tone?: NoticeTone
  title?: string
  requestId?: string | null
  className?: string
  children?: ReactNode
}

/** 统一的状态提示条：成功 / 警告 / 错误 / 信息，错误可附带 request_id。 */
export default function StatusNotice({
  tone = 'info',
  title,
  requestId,
  className = '',
  children,
}: StatusNoticeProps) {
  const Icon = TONE_ICON[tone]
  return (
    <div
      className={`notice notice-${tone} ${className}`.trim()}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <Icon size={16} className="notice-icon" aria-hidden="true" />
      <div className="notice-body">
        {title && <strong className="notice-title">{title}</strong>}
        {children && <div className="notice-content">{children}</div>}
        {requestId && (
          <small className="notice-request">
            request_id <code>{requestId}</code>
          </small>
        )}
      </div>
    </div>
  )
}
