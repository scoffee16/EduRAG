import type { Citation, KnowledgeSource } from './api'

/** 知识来源的中文标签（course_materials / web_search / model_knowledge）。 */
export const SOURCE_LABELS: Record<string, string> = {
  course_materials: '课程资料',
  web_search: '联网搜索',
  model_knowledge: '模型通用知识',
}

/** 知识来源徽标配色用的 class 后缀。 */
export const SOURCE_CLASSES: Record<string, string> = {
  course_materials: 'source-course',
  web_search: 'source-web',
  model_knowledge: 'source-model',
}

/**
 * 回答/历史记录实际使用的知识来源。
 * 旧后端不返回 knowledge_sources 时：有引用即视为使用了课程资料。
 */
export function resolveKnowledgeSources(
  sources: KnowledgeSource[] | null | undefined,
  citations: Citation[] | null | undefined,
): KnowledgeSource[] {
  if (sources != null) return sources
  return citations && citations.length > 0 ? ['course_materials'] : []
}
