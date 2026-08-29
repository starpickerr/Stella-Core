import { getLang } from '../../i18n'
import type { LedgerEntryType, PeriodStatement, PeriodStatementItem } from '../../types'

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
