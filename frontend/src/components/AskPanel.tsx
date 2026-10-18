import type { FormEvent } from 'react'
import { ArrowRight, LoaderCircle, MessageSquare } from 'lucide-react'
import type { QueryResponse } from '../api'
import AnswerMarkdown from './AnswerMarkdown'
import CitationCard from './CitationCard'
import StatusNotice from './StatusNotice'

interface AskPanelProps {
  question: string
  onQuestionChange: (value: string) => void
  topK: number
  onTopKChange: (value: number) => void
  courseCode: string
  courseName?: string
  selectedFilename?: string
  queryState: 'idle' | 'loading' | 'success' | 'error'
  queryError: { message: string; requestId?: string }
  answer: QueryResponse | null
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}

/** 主问答面板：提问、检索范围、Markdown/LaTeX 答案与引用来源。 */
export default function AskPanel({
  question,
  onQuestionChange,
  topK,
  onTopKChange,
  courseCode,
  courseName,
  selectedFilename,
  queryState,
  queryError,
  answer,
  onSubmit,
}: AskPanelProps) {
  const loading = queryState === 'loading'
  return (
    <section className="panel qa-panel">
      <div className="panel-head qa-head">
        <div>
          <span className="section-kicker">问答 / ASK</span>
          <h2>课程问答</h2>
          <p className="panel-hint">基于课程文档检索，回答附带来源页码，方便回到原文核对。</p>
        </div>
        <span className="scope-chip">
          <MessageSquare size={14} aria-hidden="true" />
          {selectedFilename ? '单份文档' : '全课程'}
        </span>
      </div>

      <form onSubmit={onSubmit} className="ask-form">
        <label className="question-box">
          <span>你的问题</span>
          <textarea
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder="例如：ADD 指令的微地址序列是什么？"
            rows={5}
          />
        </label>
        <div className="query-controls">
          <label className="topk-field">
            <span>检索数量</span>
            <input
              type="number"
              min="1"
              max="20"
              value={topK}
              onChange={(event) =>
                onTopKChange(Math.max(1, Math.min(20, Number(event.target.value) || 1)))
              }
            />
          </label>
          <span className="query-hint">
            按课程 <strong>{courseName || courseCode || '—'}</strong> 检索
            {selectedFilename && (
              <>
                {' '}
                · 限定 <strong>{selectedFilename}</strong>
              </>
            )}
          </span>
          <button
            className="primary-button"
            type="submit"
            disabled={!question.trim() || !courseCode.trim() || loading}
          >
            <MessageSquare size={16} aria-hidden="true" />
            {loading ? '检索与生成中…' : '开始问答'}
          </button>
        </div>
      </form>

      {queryState === 'error' && (
        <StatusNotice
          tone="error"
          title="问答失败"
          requestId={queryError.requestId}
        >
          <span>{queryError.message}</span>
          <small>请确认后端服务状态；429/503 错误可稍后重试。</small>
        </StatusNotice>
      )}

      {loading && (
        <div className="answer-skeleton" role="status" data-testid="answer-skeleton">
          <div className="skeleton-loading">
            <LoaderCircle className="spin" size={18} aria-hidden="true" />
            <div>
              <strong>正在查找相关内容</strong>
              <span>答案生成完成前，请稍候…</span>
            </div>
          </div>
          <span className="skeleton skeleton-line" />
          <span className="skeleton skeleton-line short" />
          <span className="skeleton skeleton-line" />
        </div>
      )}

      {answer && queryState === 'success' && (
        <div className="answer-area">
          <div className="answer-meta">
            <span>回答</span>
            <span>
              {answer.model} · {Math.round(answer.latency_ms)} ms
            </span>
          </div>
          <AnswerMarkdown content={answer.answer} />
          <div className="citation-head">
            <h3>
              来源 <small>{answer.citations.length}</small>
            </h3>
            <span>分数为检索相关性，不是概率</span>
          </div>
          <div className="citations">
            {answer.citations.length === 0 ? (
              <div className="empty-citations">没有返回引用来源。</div>
            ) : (
              answer.citations.map((citation, index) => (
                <CitationCard
                  citation={citation}
                  index={index}
                  key={`${citation.document_id ?? 'doc'}-${citation.page ?? 'p'}-${index}`}
                />
              ))
            )}
          </div>
          <div className="request-id">
            request_id <code>{answer.request_id}</code>
          </div>
        </div>
      )}

      {queryState !== 'loading' && !answer && queryState !== 'error' && (
        <div className="qa-empty">
          <MessageSquare size={26} aria-hidden="true" />
          <strong>问一个课程问题</strong>
          <span>回答会附带文档、页码和检索片段，方便回到原文核对。</span>
          <span className="qa-empty-hint">
            <ArrowRight size={13} aria-hidden="true" />
            先在右上角选择课程，再输入问题
          </span>
        </div>
      )}
    </section>
  )
}
