import assert from 'node:assert/strict'
import test from 'node:test'
import { sortBriefingItems } from '../desktop/src/renderer/src/pages/briefing/sortItems.ts'

test('briefing items sort by score, then priority, then deadline', () => {
  const items = [
    { id: 'late', score: 80, payload: { priority: 'P1', due_at: '2026-10-20T00:00:00Z' } },
    { id: 'soon', score: 80, payload: { priority: 'P1', due_at: '2026-10-10T00:00:00Z' } },
    { id: 'urgent', score: 40, payload: { priority: 'P0', due_at: '2026-10-01T00:00:00Z' } },
    { id: 'top', score: 90, payload: { priority: 'P2' } },
    { id: 'plain', score: 80, payload: {} },
  ]
  const actions = { plain: { category: 'other', facts: { due_at: '2026-10-02T00:00:00Z' } } }
  assert.deepEqual(sortBriefingItems(items, actions).map((item) => item.id), [
    'top', 'soon', 'late', 'plain', 'urgent',
  ])
})

test('equal importance keeps the current briefing order', () => {
  const items = [
    { id: 'a', score: 10, payload: {} },
    { id: 'b', score: 10, payload: {} },
  ]
  assert.deepEqual(sortBriefingItems(items).map((item) => item.id), ['a', 'b'])
})
