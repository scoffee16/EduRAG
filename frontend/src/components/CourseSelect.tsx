import { ChevronDown } from 'lucide-react'
import type { CourseSummary } from '../api'

const MANUAL_VALUE = '__manual__'

interface CourseSelectProps {
  courses: CourseSummary[]
  value: string
  manual: boolean
  coursesState: 'loading' | 'ready' | 'error'
  onSelectCourse: (code: string) => void
  onStartManual: () => void
  onManualCodeChange: (code: string) => void
}

/** 课程下拉：选项来自 GET /api/v1/courses，保留「手动新建课程」入口。 */
export default function CourseSelect({
  courses,
  value,
  manual,
  coursesState,
  onSelectCourse,
  onStartManual,
  onManualCodeChange,
}: CourseSelectProps) {
  const known = courses.some((course) => course.code === value)
  return (
    <div className="course-select">
      <label className="course-label" htmlFor="course-select">
        课程
      </label>
      <div className="select-wrap">
        <select
          id="course-select"
          value={manual ? MANUAL_VALUE : value}
          onChange={(event) => {
            const next = event.target.value
            if (next === MANUAL_VALUE) onStartManual()
            else onSelectCourse(next)
          }}
        >
          {!manual && (!value || !known) && (
            <option value={value || ''} disabled>
              {coursesState === 'loading'
                ? '课程加载中…'
                : coursesState === 'error'
                  ? '课程列表加载失败'
                  : '请选择课程'}
            </option>
          )}
          {!manual &&
            value &&
            !known && <option value={value}>{value}</option>}
          {courses.map((course) => (
            <option key={course.code} value={course.code}>
              {course.name}（{course.code}）· {course.document_count} 篇文档
            </option>
          ))}
          <option value={MANUAL_VALUE}>+ 手动新建课程…</option>
        </select>
        <ChevronDown size={14} className="select-chevron" aria-hidden="true" />
      </div>
      {manual && (
        <label className="manual-course">
          <span>新课程代码</span>
          <input
            id="manual-course-code"
            value={value}
            onChange={(event) => onManualCodeChange(event.target.value.toUpperCase())}
            placeholder="例如 CS-COMP-ORG"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
      )}
    </div>
  )
}
