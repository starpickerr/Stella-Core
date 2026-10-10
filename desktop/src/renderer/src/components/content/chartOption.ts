const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
const MAX_DEPTH = 12
const MAX_NODES = 8000
const MAX_STRING = 8000
const MAX_JSON = 100_000

function unsafeString(value: string): boolean {
  return /^\s*(function\b|javascript:)/i.test(value) || value.includes('=>')
}

function sanitizeNode(value: unknown, depth: number, budget: { left: number }): unknown {
  if (budget.left <= 0) throw new Error('chart option is too large')
  budget.left -= 1
  if (value === null || typeof value === 'boolean' || typeof value === 'number') {
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('chart option has a non-finite number')
    return value
  }
  if (typeof value === 'string') {
    if (value.length > MAX_STRING || unsafeString(value)) throw new Error('chart option has an unsafe string')
    return value
  }
  if (depth > MAX_DEPTH) throw new Error('chart option is too deep')
  if (Array.isArray(value)) return value.map((item) => sanitizeNode(item, depth + 1, budget))
  if (typeof value !== 'object') throw new Error('chart option has an unsupported value')
  const output: Record<string, unknown> = {}
  for (const key of Object.keys(value as Record<string, unknown>)) {
    if (FORBIDDEN_KEYS.has(key) || key.startsWith('on')) throw new Error('chart option has a forbidden key')
    output[key] = sanitizeNode((value as Record<string, unknown>)[key], depth + 1, budget)
  }
  return output
}

/** Parse an ECharts option from JSON only. Functions and event handlers are rejected. */
export function parseChartOption(source: string): Record<string, unknown> {
  if (source.length > MAX_JSON) throw new Error('chart option is too large')
  const parsed: unknown = JSON.parse(source)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('chart option must be an object')
  }
  return sanitizeNode(parsed, 0, { left: MAX_NODES }) as Record<string, unknown>
}
