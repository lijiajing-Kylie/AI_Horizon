import { useState, useEffect, useRef, useCallback } from 'react'
import {
  PAPER_CATEGORY_GROUPS,
  type CategoryGroup,
} from '../utils/paperCategories'
import { categoryLabelZh } from '../utils/paperCategories'

interface CategoryFilterMenuProps {
  selectedIds: string[]
  onSelectionChange: (ids: string[]) => void
  onClear: () => void
  /** Custom groups to display (defaults to PAPER_CATEGORY_GROUPS). */
  groups?: CategoryGroup[]
  /** When false, selecting a child replaces the current selection (single-select). Default true. */
  multiSelect?: boolean
}

export default function CategoryFilterMenu({
  selectedIds,
  onSelectionChange,
  onClear,
  groups,
  multiSelect = true,
}: CategoryFilterMenuProps) {
  const resolvedGroups = groups ?? PAPER_CATEGORY_GROUPS
  const [isOpen, setIsOpen] = useState(false)
  const [hoveredGroup, setHoveredGroup] = useState<CategoryGroup | null>(
    resolvedGroups[0] ?? null,
  )
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen])

  // Default hover to first group when opening
  useEffect(() => {
    if (isOpen) {
      setHoveredGroup(resolvedGroups[0])
    }
  }, [isOpen])

  const toggleGroup = useCallback(
    (group: CategoryGroup) => {
      // In single-select mode, groups are navigation only — clicking them
      // should not toggle all children at once.
      if (!multiSelect) return
      const allSelected = group.children.every(c => selectedIds.includes(c.id))
      const someSelected = group.children.some(c => selectedIds.includes(c.id))

      let next: string[]
      if (allSelected) {
        // Deselect all in group
        next = selectedIds.filter(id => !group.children.some(c => c.id === id))
      } else if (someSelected) {
        // Select all in group (add missing ones)
        const groupIds = group.children.map(c => c.id)
        next = [...new Set([...selectedIds, ...groupIds])]
      } else {
        // Select all in group
        next = [...selectedIds, ...group.children.map(c => c.id)]
      }
      onSelectionChange(next)
    },
    [selectedIds, onSelectionChange, multiSelect],
  )

  const toggleChild = useCallback(
    (id: string) => {
      if (selectedIds.includes(id)) {
        // Deselect
        onSelectionChange(selectedIds.filter(i => i !== id))
      } else if (multiSelect) {
        // Add to existing selection
        onSelectionChange([...selectedIds, id])
      } else {
        // Replace selection (single-select)
        onSelectionChange([id])
      }
    },
    [selectedIds, onSelectionChange, multiSelect],
  )

  // ── Helper: find a child label across resolved groups ─────────────────
  const childLabel = (id: string) => {
    for (const g of resolvedGroups) {
      const child = g.children.find(c => c.id === id)
      if (child) return child.label
    }
    return categoryLabelZh(id)
  }

  const parentGroupForId = (id: string): CategoryGroup | undefined => {
    return resolvedGroups.find(g => g.children.some(c => c.id === id))
  }

  // ── Trigger label ──────────────────────────────────────────────────────
  const triggerLabel = (() => {
    if (selectedIds.length === 0) return '主题⌄'

    // Single subcategory selected — show "GroupLabel / SubLabel"
    if (selectedIds.length === 1) {
      const parent = parentGroupForId(selectedIds[0])
      if (parent) {
        return `主题：${parent.label} / ${childLabel(selectedIds[0])}`
      }
      return `主题：${childLabel(selectedIds[0])}`
    }

    // Check if all selected belong to the same group
    const parentSet = new Set(selectedIds.map(id => parentGroupForId(id)?.label).filter(Boolean))
    if (parentSet.size === 1) {
      const groupLabel = parentSet.values().next().value
      return `主题：${groupLabel} (${selectedIds.length})`
    }

    return `主题 (${selectedIds.length})`
  })()

  const hasSelection = selectedIds.length > 0

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger */}
      <div className="flex items-center gap-0">
        <button
          onClick={() => setIsOpen(v => !v)}
          className={`shrink-0 text-xs font-medium transition-colors cursor-pointer px-1 py-1 ${
            hasSelection
              ? 'text-[var(--accent)]'
              : 'text-[var(--muted)] hover:text-[var(--ink)]'
          }`}
        >
          {triggerLabel}
        </button>
        {hasSelection && (
          <button
            onClick={onClear}
            className="text-xs text-[var(--muted)] hover:text-[var(--ink)] transition-colors cursor-pointer px-1 py-1"
            title="清除主题筛选"
          >
            ✕
          </button>
        )}
      </div>

      {/* Dropdown panel */}
      {isOpen && (
        <div
          className="absolute top-full left-0 mt-1 z-50"
          onClick={e => e.stopPropagation()}
        >
          {/* Desktop: two-column layout */}
          <div className="hidden lg:flex bg-white/90 backdrop-blur-sm border border-[var(--line)] rounded-xl overflow-hidden min-w-[320px] shadow-sm">
            {/* Left: groups */}
            <div className="w-[140px] border-r border-[var(--line)] py-1">
              {resolvedGroups.map(group => {
                const allSelected = group.children.every(c => selectedIds.includes(c.id))
                const someSelected = group.children.some(c => selectedIds.includes(c.id))
                return (
                  <button
                    key={group.id}
                    onClick={() => toggleGroup(group)}
                    onMouseEnter={() => setHoveredGroup(group)}
                    className={`w-full text-left px-3 py-2 text-sm font-medium transition-colors cursor-pointer ${
                      allSelected
                        ? 'text-[var(--accent)] bg-[var(--accent)]/8'
                        : someSelected
                          ? 'text-[var(--accent)] bg-[var(--accent)]/5'
                          : 'text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    {group.label}
                    {allSelected && (
                      <span className="ml-1 text-[10px] text-[var(--accent)]">✓</span>
                    )}
                    {someSelected && !allSelected && (
                      <span className="ml-1 text-[10px] text-[var(--accent)]">–</span>
                    )}
                  </button>
                )
              })}
            </div>

            {/* Right: children of hovered group */}
            <div className="w-[180px] py-1">
              {hoveredGroup?.children.map(child => {
                const selected = selectedIds.includes(child.id)
                return (
                  <button
                    key={child.id}
                    onClick={() => toggleChild(child.id)}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-colors cursor-pointer ${
                      selected
                        ? 'text-[var(--accent)] bg-[var(--accent)]/8 font-medium'
                        : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    {child.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Mobile: accordion layout */}
          <div className="lg:hidden bg-white/95 backdrop-blur-sm border border-[var(--line)] rounded-xl min-w-[240px] shadow-sm overflow-hidden">
            {resolvedGroups.map(group => {
              const allSelected = group.children.every(c => selectedIds.includes(c.id))
              const someSelected = group.children.some(c => selectedIds.includes(c.id))
              const isExpanded = hoveredGroup?.id === group.id
              return (
                <div key={group.id}>
                  <button
                    onClick={() => {
                      if (isExpanded) {
                        setHoveredGroup(null)
                      } else {
                        setHoveredGroup(group)
                      }
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2.5 text-sm font-medium transition-colors cursor-pointer ${
                      allSelected
                        ? 'text-[var(--accent)] bg-[var(--accent)]/8'
                        : someSelected
                          ? 'text-[var(--accent)] bg-[var(--accent)]/5'
                          : 'text-[var(--ink)] hover:bg-black/[.03]'
                    }`}
                  >
                    <span>
                      {group.label}
                      {allSelected && <span className="ml-1.5 text-[10px]">✓</span>}
                      {someSelected && !allSelected && (
                        <span className="ml-1.5 text-[10px]">–</span>
                      )}
                    </span>
                    <span className={`text-xs text-[var(--muted)] transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
                      ▾
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="border-t border-[var(--line)]/40">
                      {group.children.map(child => {
                        const selected = selectedIds.includes(child.id)
                        return (
                          <button
                            key={child.id}
                            onClick={() => toggleChild(child.id)}
                            className={`w-full text-left px-5 py-2 text-sm transition-colors cursor-pointer ${
                              selected
                                ? 'text-[var(--accent)] bg-[var(--accent)]/8 font-medium'
                                : 'text-[var(--muted)] hover:text-[var(--ink)] hover:bg-black/[.03]'
                            }`}
                          >
                            {child.label}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
