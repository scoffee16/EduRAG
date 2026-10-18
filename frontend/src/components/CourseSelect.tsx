import { ChevronDown, LoaderCircle, Trash2 } from 'lucide-react'
import type { CourseSummary } from '../api'

const MANUAL_VALUE = '__manual__'

interface CourseSelectProps {
  courses: CourseSummary[]
  /** 当前选中的课程代码；手动新建模式下为空。 */
  value: string
  manual: boolean
  coursesState: 'loading' | 'ready' | 'error'
  manualCode: string
  manualName: string
  creating: boolean
  createError: string
  deleting?: boolean
  onSelectCourse: (code: string) => void
  onStartManual: () => void
  onManualCodeChange: (code: string) => void
  onManualNameChange: (name: string) => void
  onCreate: () => void
  onCancelManual: () => void
  onDeleteCourse: () => void
}

/** 课程下拉 + 手动新建（课程代码 / 课程名称双输入框）+ 删除可删除课程。 */
export default function CourseSelect({
  courses,
  value,
  manual,
  coursesState,
  manualCode,
  manualName,
  creating,
  createError,
  deleting = false,
  onSelectCourse,
  onStartManual,
  onManualCodeChange,
  onManualNameChange,
  onCreate,
  onCancelManual,
  onDeleteCourse,
}: CourseSelectProps) {
  const selectedCourse = courses.find((course) => course.code === value) ?? null
  const known = selectedCourse != null
  const canCreate = Boolean(manualCode.trim() && manualName.trim()) && !creating

  return (
    <div className={`course-select ${manual ? 'manual-mode' : ''}`.trim()}>
      {!manual && (
        <>
          <label className="course-label" htmlFor="course-select">
            课程
          </label>
          <div className="select-wrap">
            <select
              id="course-select"
              value={value}
              onChange={(event) => {
                const next = event.target.value
                if (next === MANUAL_VALUE) onStartManual()
                else onSelectCourse(next)
              }}
            >
              {(!value || !known) && (
                <option value={value || ''} disabled>
                  {coursesState === 'loading'
                    ? '课程加载中…'
                    : coursesState === 'error'
                      ? '课程列表加载失败'
                      : '请选择课程'}
                </option>
              )}
              {value && !known && <option value={value}>{value}</option>}
              {courses.map((course) => (
                <option key={course.code} value={course.code}>
                  {course.name}（{course.code}）· {course.document_count} 篇文档
                </option>
              ))}
              <option value={MANUAL_VALUE}>+ 手动新建课程…</option>
            </select>
            <ChevronDown size={14} className="select-chevron" aria-hidden="true" />
          </div>
          {selectedCourse && (
            <span
              className="course-delete-wrap"
              title={
                selectedCourse.deletable
                  ? '删除课程'
                  : '示例课程由配置文件同步生成，不能删除'
              }
            >
              <button
                type="button"
                className={`icon-button course-delete-button ${selectedCourse.deletable ? '' : 'locked'}`.trim()}
                title={
                  selectedCourse.deletable
                    ? '删除课程'
                    : '示例课程由配置文件同步生成，不能删除'
                }
                aria-label="删除课程"
                onClick={onDeleteCourse}
                disabled={deleting || !selectedCourse.deletable}
              >
                {deleting ? (
                  <LoaderCircle size={15} className="spin" aria-hidden="true" />
                ) : (
                  <Trash2 size={15} aria-hidden="true" />
                )}
              </button>
            </span>
          )}
        </>
      )}

      {manual && (
        <div className="manual-course-form">
          <label className="manual-field" htmlFor="manual-course-code">
            <span>课程代码</span>
            <input
              id="manual-course-code"
              value={manualCode}
              onChange={(event) => onManualCodeChange(event.target.value.toUpperCase())}
              placeholder="例如 CS-COMP-ORG"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="manual-field" htmlFor="manual-course-name">
            <span>课程名称</span>
            <input
              id="manual-course-name"
              value={manualName}
              onChange={(event) => onManualNameChange(event.target.value)}
              placeholder="例如 计算机组成原理"
              autoComplete="off"
            />
          </label>
          <div className="manual-actions">
            <button
              type="button"
              className="primary-button manual-create-button"
              onClick={onCreate}
              disabled={!canCreate}
            >
              {creating ? '创建中…' : '创建课程'}
            </button>
            <button type="button" className="text-button" onClick={onCancelManual}>
              取消
            </button>
          </div>
          {createError && (
            <p className="manual-error" role="alert">
              {createError}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
