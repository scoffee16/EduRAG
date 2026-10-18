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

/** 知识来源的中文标签与样式后缀（course_materials / web_search / model_knowledge）。 */
const SOURCE_LABELS: Record<string, string> = {
  course_materials: '课程资料',
  web_search: '联网搜索',
  model_knowledge: '模型通用知识',
}

const SOURCE_CLASSES: Record<string, string> = {
  course_materials: 'source-course',
  web_search: 'source-web',
  model_knowledge: 'source-model',
}

/** 列表里的外部网页摘要截断，避免长文本撑破卡片。 */
function truncateSnippet(text: string | null | undefined) {
  const value = (text ?? '').trim()
  return value.length > 160 ? `${value.slice(0, 160)}…` : value
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
  // 旧后端不返回 knowledge_sources 时，有引用即视为使用了课程资料
  const knowledgeSources =
    answer?.knowledge_sources ??
    (answer && answer.citations.length > 0 ? ['course_materials'] : [])
  const hasNonCourseSource = knowledgeSources.some(
    (source) => source !== 'course_materials',
  )
  const webResults = answer?.web_results ?? []
  return (
    <section className="panel qa-panel">
      <div className="panel-head qa-head">
        <div>
          <span className="section-kicker">问答 / ASK</span>
          <h2>课程问答</h2>
          <p className="panel-hint">
            优先基于课程文档检索；资料不足时会补充联网搜索或模型通用知识，并标注来源。
          </p>
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
          {knowledgeSources.length > 0 && (
            <div className="source-badges" data-testid="knowledge-sources">
              <span className="source-label">知识来源</span>
              {knowledgeSources.map((source) => (
                <span
                  className={`source-badge ${SOURCE_CLASSES[source] ?? 'source-unknown'}`}
                  key={source}
                >
                  {SOURCE_LABELS[source] ?? source}
                </span>
              ))}
            </div>
          )}
          {hasNonCourseSource && (
            <StatusNotice
              tone="warning"
              title="包含课程资料之外的内容"
              className="source-warning"
            >
              本回答包含课程资料之外的内容，请谨慎参考并核实来源。
            </StatusNotice>
          )}
          <AnswerMarkdown content={answer.answer} />
          {webResults.length > 0 && (
            <div className="web-sources" data-testid="web-results">
              <div className="web-sources-head">
                <h3>
                  联网搜索来源 <small>{webResults.length}</small>
                </h3>
                <span>外部网页内容，仅供参考</span>
              </div>
              <ul className="web-source-list">
                {webResults.map((item, index) => (
                  <li className="web-source-item" key={`${item.url}-${index}`}>
                    <a href={item.url} target="_blank" rel="noreferrer noopener">
                      {item.title || item.url}
                    </a>
                    {item.snippet && (
                      <p className="web-source-snippet">{truncateSnippet(item.snippet)}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="citation-head">
            <h3>
              来源 <small>{answer.citations.length}</small>
            </h3>
            <span>分数为检索相关性，不是概率</span>
          </div>
          <div className="citations">
            {answer.citations.length === 0 ? (
              <div className="empty-citations">
                {hasNonCourseSource ? '本回答未使用课程资料引用。' : '没有返回引用来源。'}
              </div>
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
          <span>回答会标注课程资料、联网搜索或模型通用知识来源，方便核对。</span>
          <span className="qa-empty-hint">
            <ArrowRight size={13} aria-hidden="true" />
            先在右上角选择课程，再输入问题
          </span>
        </div>
      )}
    </section>
  )
}
