import { Component, type ErrorInfo, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

/**
 * 清洗模型输出里可能出现的孤立控制字符（保留换行/制表），
 * 避免渲染管线崩溃或页面出现不可见乱码。
 */
export function sanitizeAnswerText(text: string): string {
  return (text ?? '').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ' ')
}

interface BoundaryProps {
  children: ReactNode
  fallback: string
}

interface BoundaryState {
  failed: boolean
}

/** 渲染异常的兜底：回退为 <pre> 原文，保证不白屏。 */
class MarkdownErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false }

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn('[AnswerMarkdown] 渲染失败，已回退为纯文本', error, info.componentStack)
  }

  render() {
    if (this.state.failed) {
      return (
        <pre className="answer-fallback" data-testid="answer-fallback">
          {this.props.fallback}
        </pre>
      )
    }
    return this.props.children
  }
}

interface AnswerMarkdownProps {
  content: string
}

/**
 * 答案渲染：Markdown（GFM）+ LaTeX。
 * - skipHtml：禁止答案里的原始 HTML 执行，防 XSS；
 * - 控制字符清洗 + ErrorBoundary 兜底 <pre>。
 */
export default function AnswerMarkdown({ content }: AnswerMarkdownProps) {
  const text = sanitizeAnswerText(content)
  return (
    <MarkdownErrorBoundary key={text} fallback={text}>
      <div className="answer-markdown" data-testid="answer-markdown">
        <ReactMarkdown
          skipHtml
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
        >
          {text}
        </ReactMarkdown>
      </div>
    </MarkdownErrorBoundary>
  )
}
