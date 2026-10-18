import { useState } from 'react'
import { ChevronDown, Clock3 } from 'lucide-react'
import type { HistoryItem } from '../api'
import { formatCitationLocation, formatShortDateTime } from '../format'
import { resolveKnowledgeSources, SOURCE_CLASSES, SOURCE_LABELS } from '../sources'
import AnswerMarkdown from './AnswerMarkdown'

/** 最多展示的最近问答条数（与 getHistory 的默认 limit 一致）。 */
const MAX_HISTORY_ITEMS = 20

interface HistoryPanelProps {
  items: HistoryItem[]
  loading: boolean
  error?: string
}

/** 列表里的外部网页摘要截断，避免长文本撑破卡片。 */
function truncateSnippet(text: string | null | undefined) {
  const value = (text ?? '').trim()
  return value.length > 160 ? `${value.slice(0, 160)}…` : value
}

/**
 * 历史问答面板：默认折叠，点击展开查看课程、限定文档、完整问题、
 * 答案（Markdown/LaTeX）与命中片段、联网来源。
 */
export default function HistoryPanel({ items, loading, error = '' }: HistoryPanelProps) {
  // 展开的记录 id 列表；受控折叠，支持同时展开多条
  const [expanded, setExpanded] = useState<string[]>([])

  const toggle = (historyId: string) => {
    setExpanded((current) =>
      current.includes(historyId)
        ? current.filter((id) => id !== historyId)
        : [...current, historyId],
    )
  }

  const visible = items.slice(0, MAX_HISTORY_ITEMS)

  return (
    <section className="panel history-panel" data-testid="history-panel">
      <div className="panel-head history-head">
        <div>
          <span className="section-kicker">记录 / HISTORY</span>
          <h2>
            历史问答{' '}
            <small className="history-count" data-testid="history-count">
              {items.length}
            </small>
          </h2>
          <p className="panel-hint">
            最近 20 次问答记录，默认折叠；点击可展开查看课程、限定文档与命中片段。
          </p>
        </div>
      </div>

      {loading && visible.length === 0 && (
        <p className="history-status" role="status">
          历史问答加载中…
        </p>
      )}

      {error && (
        <p className="history-status history-status-error" role="status">
          历史问答加载失败：{error}
        </p>
      )}

      {!loading && !error && visible.length === 0 && (
        <p className="history-empty">暂无历史问答，提问后会显示在这里</p>
      )}

      {visible.length > 0 && (
        <div className="history-list">
          {visible.map((item, index) => {
            const open = expanded.includes(item.history_id)
            const detailId = `history-detail-${index}`
            const scope = item.document_scope ?? []
            const citations = item.citations ?? []
            const webResults = item.web_results ?? []
            const sources = resolveKnowledgeSources(item.knowledge_sources, citations)
            const timeLabel = formatShortDateTime(item.created_at)
            const courseLabel = item.course_name?.trim() || item.course_code
            const scopeLabel = scope.length === 0 ? '全课程' : `限定 ${scope.length} 篇文档`
            const scopeFiles = scope.map((document) => document.filename).join('、')
            return (
              <article
                className={`history-item${open ? ' open' : ''}`}
                key={item.history_id}
                data-testid="history-item"
              >
                <button
                  type="button"
                  className="history-summary"
                  aria-expanded={open}
                  aria-controls={detailId}
                  title={open ? '收起这条问答记录' : '展开这条问答记录'}
                  onClick={() => toggle(item.history_id)}
                >
                  <span className="history-summary-main">
                    <span className="history-summary-meta">
                      {timeLabel && (
                        <span className="history-time">
                          <Clock3 size={12} aria-hidden="true" />
                          {timeLabel}
                        </span>
                      )}
                      <span className="history-course" title={item.course_code}>
                        {courseLabel}
                      </span>
                      <span
                        className={`history-scope-badge ${scope.length === 0 ? 'scope-all' : 'scope-limited'}`}
                      >
                        {scopeLabel}
                      </span>
                    </span>
                    <span className="history-question">{item.question}</span>
                    {sources.length > 0 && (
                      <span className="history-source-badges" data-testid="history-sources">
                        {sources.map((source) => (
                          <span
                            className={`source-badge ${SOURCE_CLASSES[source] ?? 'source-unknown'}`}
                            key={source}
                          >
                            {SOURCE_LABELS[source] ?? source}
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                  <ChevronDown className="history-chevron" size={16} aria-hidden="true" />
                </button>

                {open && (
                  <div className="history-detail" id={detailId} data-testid="history-detail">
                    <dl className="history-meta-list">
                      <div>
                        <dt>课程</dt>
                        <dd>
                          {item.course_name
                            ? `${item.course_name}（${item.course_code}）`
                            : item.course_code}
                        </dd>
                      </div>
                      <div>
                        <dt>检索范围</dt>
                        <dd>
                          {scope.length === 0 ? (
                            '全课程：该课程全部文档'
                          ) : (
                            <span className="history-scope-files" data-testid="history-scope-files">
                              {scopeFiles}
                            </span>
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>模型</dt>
                        <dd>
                          {item.model || '未知'} · {Math.round(item.latency_ms)} ms
                        </dd>
                      </div>
                    </dl>

                    <p className="history-full-question">{item.question}</p>
                    <AnswerMarkdown content={item.answer} />

                    {citations.length > 0 && (
                      <div className="history-citations" data-testid="history-citations">
                        <h3>
                          命中片段 <small>{citations.length}</small>
                        </h3>
                        <ul>
                          {citations.map((citation, citationIndex) => (
                            <li
                              key={`${citation.document_id ?? 'doc'}-${citation.page ?? 'p'}-${citationIndex}`}
                            >
                              <div className="history-citation-head">
                                <strong>{citation.filename || '未命名文档'}</strong>
                                <span>
                                  {formatCitationLocation(citation.file_type, citation.page)}
                                  {citation.score != null &&
                                    ` · score ${Number(citation.score).toFixed(3)}`}
                                </span>
                              </div>
                              {citation.snippet && (
                                <p className="history-citation-snippet">{citation.snippet}</p>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {webResults.length > 0 && (
                      <div className="history-web-results" data-testid="history-web-results">
                        <h3>
                          联网搜索来源 <small>{webResults.length}</small>
                        </h3>
                        <ul className="web-source-list">
                          {webResults.map((result, resultIndex) => (
                            <li className="web-source-item" key={`${result.url}-${resultIndex}`}>
                              <a href={result.url} target="_blank" rel="noreferrer noopener">
                                {result.title || result.url}
                              </a>
                              {result.snippet && (
                                <p className="web-source-snippet">
                                  {truncateSnippet(result.snippet)}
                                </p>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="history-foot">
                      request_id <code>{item.request_id}</code>
                    </div>
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
