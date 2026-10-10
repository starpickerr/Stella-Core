/** Importance order for one briefing's current items. */

export interface RankedBriefingItem {
  id: string
  score: number
  payload?: Record<string, unknown>
}

export interface RankedBriefingAction {
  category?: string
  facts?: Record<string, unknown>
}

const PRIORITY_RANK: Record<string, number> = {
  P0: 0,
  p0: 0,
  P1: 1,
  p1: 1,
  P2: 2,
  p2: 2,
  needs_action: 0,
  attention: 1,
  status_update: 2,
  other: 3,
}

function priorityRank(item: RankedBriefingItem, action?: RankedBriefingAction): number {
  const facts = action?.facts ?? {}
  const payload = item.payload ?? {}
  const raw = facts.priority ?? payload.priority ?? action?.category
  if (typeof raw === 'string' && raw in PRIORITY_RANK) return PRIORITY_RANK[raw]
  if (typeof raw === 'number' && raw >= 0 && raw <= 2) return raw
  if (action?.category && action.category in PRIORITY_RANK) return PRIORITY_RANK[action.category]
  return 3
}

function deadline(item: RankedBriefingItem, action?: RankedBriefingAction): number {
  const facts = action?.facts ?? {}
  const payload = item.payload ?? {}
  const raw = facts.due_at ?? payload.due_at
  if (typeof raw !== 'string' || !raw) return Number.POSITIVE_INFINITY
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY
}

export function sortBriefingItems<T extends RankedBriefingItem>(
  items: readonly T[],
  actions?: Record<string, RankedBriefingAction>,
): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftAction = actions?.[left.item.id]
      const rightAction = actions?.[right.item.id]
      const score = (right.item.score || 0) - (left.item.score || 0)
      if (score) return score
      const rank = priorityRank(left.item, leftAction) - priorityRank(right.item, rightAction)
      if (rank) return rank
      const due = deadline(left.item, leftAction) - deadline(right.item, rightAction)
      if (due) return due
      return left.index - right.index
    })
    .map((row) => row.item)
}
