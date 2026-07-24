/**
 * Paper category display labels, filter definitions, and the two-level
 * hierarchical grouping used by the cascading filter menu.
 *
 * The primary mapping lives in paperCategoryMap.ts (raw → unified + Chinese).
 * This file re-exports the unified category list, adds the hierarchical group
 * structure, and keeps the same `categoryLabelZh()` interface.
 */

import {
  UNIFIED_LABELS_ZH,
} from './paperCategoryMap'

export type { UnifiedCategoryId, UnifiedCategoryId as VisibleCategoryId } from './paperCategoryMap'

// ── Two-level hierarchy ────────────────────────────────────────────────────

export interface CategoryChild {
  id: string
  label: string
}

export interface CategoryGroup {
  id: string
  label: string
  children: CategoryChild[]
}

/** The four 大类 groups with their 小类 children. */
export const PAPER_CATEGORY_GROUPS: CategoryGroup[] = [
  {
    id: 'foundation-models',
    label: '基础与模型',
    children: [
      { id: 'machine-learning', label: '机器学习' },
      { id: 'deep-learning', label: '深度学习' },
      { id: 'reinforcement-learning', label: '强化学习' },
    ],
  },
  {
    id: 'language-vision',
    label: '语言与视觉',
    children: [
      { id: 'nlp-llm', label: '自然语言处理' },
      { id: 'computer-vision', label: '计算机视觉' },
      { id: 'multimodal', label: '多模态' },
      { id: 'speech-audio', label: '语音与音频' },
    ],
  },
  {
    id: 'generation-agents',
    label: '生成与智能体',
    children: [
      { id: 'llm', label: '大语言模型' },
      { id: 'image-video-generation', label: '图像与视频生成' },
      { id: 'agent-multi-agent', label: 'Agent 与多智能体' },
    ],
  },
  {
    id: 'systems-robotics',
    label: '系统与机器人',
    children: [
      { id: 'ai-systems', label: 'AI 系统与模型优化' },
      { id: 'embodied-robotics', label: '机器人与具身智能' },
    ],
  },
  {
    id: 'other',
    label: '其他',
    children: [
      { id: 'other', label: '其他' },
    ],
  },
]

/** Flat list of visible subcategory IDs in hierarchy order (for the filter menu). */
export const VISIBLE_SUBCATEGORY_IDS: readonly string[] =
  PAPER_CATEGORY_GROUPS.flatMap(g => g.children.map(c => c.id))

/** Return the parent group for a given subcategory ID, if any. */
export function parentGroupForChild(childId: string): CategoryGroup | undefined {
  return PAPER_CATEGORY_GROUPS.find(g => g.children.some(c => c.id === childId))
}

/** Collect all subcategory IDs under a parent group. */
export function childIdsForGroup(groupId: string): string[] {
  const group = PAPER_CATEGORY_GROUPS.find(g => g.id === groupId)
  return group ? group.children.map(c => c.id) : []
}

// ── Flat list (backward-compatible) ───────────────────────────────────────

/** Unified category IDs used for filter buttons (now hierarchy-derived). */
export const PAPER_CATEGORIES: readonly string[] = VISIBLE_SUBCATEGORY_IDS

/** Chinese label lookup — backwards-compatible re-export. */
export const CATEGORY_LABELS_ZH: Record<string, string> = UNIFIED_LABELS_ZH as Record<string, string>

/** Get Chinese label for a category (works with both unified IDs and raw names). */
export function categoryLabelZh(category: string): string {
  return UNIFIED_LABELS_ZH[category as keyof typeof UNIFIED_LABELS_ZH]
    ?? category
}
