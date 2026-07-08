// Shared "where did the user come from" navigation state.
//
// Every Link into a detail page (/items/:id, /topics/:slug, /daily/:date)
// carries state.backTo describing the page being left — never chained from
// that page's own backTo. So Topic tag clicks from ItemDetailPage always
// point back at that same item, regardless of how the item detail page
// itself was reached.
export interface BackTarget {
  path: string
  label: string
}

export function backToState(backTo?: BackTarget): { backTo: BackTarget } | undefined {
  return backTo ? { backTo } : undefined
}
