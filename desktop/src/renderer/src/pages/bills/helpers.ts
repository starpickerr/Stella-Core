import { getLang } from '../../i18n'
import type { LedgerEntry, LedgerEntryType, PeriodStatement, PeriodStatementItem } from '../../types'

export function formatMinor(amountMinor: number, currency = 'CNY'): string {
  return new Intl.NumberFormat(getLang() === 'zh' ? 'zh-CN' : 'en-US', {
    style: 'currency',
    currency,
  }).format(amountMinor / 100)
}

export function periodLabel(bill: PeriodStatement): string {
  if (bill.period_type === 'yearly' || bill.month == null) {
    return getLang() === 'zh' ? `${bill.year} 年` : String(bill.year)
  }
  if (getLang() === 'zh') return `${bill.year} 年 ${bill.month} 月`
  return `${bill.year}-${String(bill.month).padStart(2, '0')}`
}

export function formatPeriodRange(bill: PeriodStatement): string {
  const loc = getLang() === 'zh' ? 'zh-CN' : 'en-US'
  const start = formatIsoDate(bill.start_at, loc)
  const endExclusive = new Date(bill.end_at)
  if (!Number.isNaN(endExclusive.getTime())) {
    endExclusive.setDate(endExclusive.getDate() - 1)
  }
  const end = Number.isNaN(endExclusive.getTime())
    ? bill.end_at.slice(0, 10)
    : endExclusive.toLocaleDateString(loc, { year: 'numeric', month: 'short', day: 'numeric' })
  return `${start} – ${end}`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function groupByCategory(
  items: PeriodStatementItem[],
  entryType: LedgerEntryType,
): { category: string; amount_minor: number; entry_count: number }[] {
  const map = new Map<string, { amount_minor: number; entry_count: number }>()
  for (const item of items) {
    if (item.entry_type !== entryType) continue
    const prev = map.get(item.category) ?? { amount_minor: 0, entry_count: 0 }
    prev.amount_minor += item.amount_minor
    prev.entry_count += item.entry_count
    map.set(item.category, prev)
  }
  return [...map.entries()]
    .map(([category, v]) => ({ category, ...v }))
    .sort((a, b) => b.amount_minor - a.amount_minor)
}

function formatIsoDate(iso: string, loc: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toLocaleDateString(loc, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function monthDateRange(year: number, month: number): { start: string; end: string } {
  const pad = (n: number) => String(n).padStart(2, '0')
  const last = new Date(year, month, 0).getDate()
  return {
    start: `${year}-${pad(month)}-01`,
    end: `${year}-${pad(month)}-${pad(last)}`,
  }
}

export function monthLabel(month: number): string {
  if (getLang() === 'zh') return `${month} 月`
  return String(month).padStart(2, '0')
}

export function occurredDateKey(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function inYearMonth(iso: string, year: number, month: number): boolean {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return false
  return d.getFullYear() === year && d.getMonth() + 1 === month
}

export function formatDayHeading(dateKey: string): string {
  const d = new Date(`${dateKey}T12:00:00`)
  if (Number.isNaN(d.getTime())) return dateKey
  if (getLang() === 'zh') {
    const weekday = d.toLocaleDateString('zh-CN', { weekday: 'short' })
    return `${d.getMonth() + 1}月${d.getDate()}日 ${weekday}`
  }
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export function formatClock(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(getLang() === 'zh' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function toDatetimeLocal(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromDatetimeLocal(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toISOString()
}

export function yuanFromMinor(amountMinor: number): string {
  return (amountMinor / 100).toFixed(2)
}

export function parseYuanToMinor(raw: string): number | null {
  const n = Number(raw.trim())
  if (!Number.isFinite(n) || n < 0) return null
  return Math.round(n * 100)
}

export function defaultLedgerLocalTime(year: number, month: number): string {
  const now = new Date()
  if (now.getFullYear() === year && now.getMonth() + 1 === month) {
    return toDatetimeLocal(now.toISOString())
  }
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${year}-${pad(month)}-01T12:00`
}

export function groupLedgerByDay(entries: LedgerEntry[]): {
  date: string
  rows: LedgerEntry[]
  income_minor: number
  expense_minor: number
}[] {
  const map = new Map<string, LedgerEntry[]>()
  const sorted = [...entries].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at))
  for (const row of sorted) {
    const key = occurredDateKey(row.occurred_at)
    const list = map.get(key) ?? []
    list.push(row)
    map.set(key, list)
  }
  return [...map.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([date, rows]) => ({
      date,
      rows,
      income_minor: rows
        .filter((r) => r.entry_type === 'income')
        .reduce((s, r) => s + r.amount_minor, 0),
      expense_minor: rows
        .filter((r) => r.entry_type === 'expense')
        .reduce((s, r) => s + r.amount_minor, 0),
    }))
}
