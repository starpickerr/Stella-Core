import React, { useMemo, useState } from 'react'
import { t } from '../../i18n'
import type { PeriodStatement, PeriodStatementItem } from '../../types'
import { formatMinor, groupByCategory } from './helpers'

interface PeriodChartsProps {
  statement: PeriodStatement
  items: PeriodStatementItem[]
}

interface ChartSlice {
  category: string
  amount_minor: number
  entry_count: number
  color: string
  label: string
  startDeg: number
  endDeg: number
  share: number
}

const EXPENSE_COLORS = ['#ef4444', '#f59e0b', '#f97316', '#a855f7', '#3b82f6', '#64748b']
const INCOME_COLORS = ['#4abe6e', '#14b8a6', '#3b82f6', '#6366f1', '#84cc16', '#0ea5e9']

const VB = 120
const CX = 60
const CY = 60
const OUTER = 40
const INNER = 25

export const PeriodCharts: React.FC<PeriodChartsProps> = ({ statement, items }) => {
  const expense = useMemo(() => groupByCategory(items, 'expense'), [items])
  const income = useMemo(() => groupByCategory(items, 'income'), [items])

  return (
    <section className="rounded-card border border-default bg-surface p-4">
      <h4 className="text-sm font-semibold text-content mb-4">{t('bills_charts_title')}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 sm:gap-0">
        <CategoryDonut
          title={t('bills_charts_expense')}
          totalLabel={formatMinor(statement.expense_minor, statement.currency)}
          slices={expense}
          colors={EXPENSE_COLORS}
          currency={statement.currency}
        />
        <div className="sm:border-l sm:border-subtle sm:pl-6 sm:ml-6">
          <CategoryDonut
            title={t('bills_charts_income')}
            totalLabel={formatMinor(statement.income_minor, statement.currency)}
            slices={income}
            colors={INCOME_COLORS}
            currency={statement.currency}
          />
        </div>
      </div>
    </section>
  )
}

const CategoryDonut: React.FC<{
  title: string
  totalLabel: string
  slices: { category: string; amount_minor: number; entry_count: number }[]
  colors: string[]
  currency: string
}> = ({ title, totalLabel, slices, colors, currency }) => {
  const [hover, setHover] = useState<number | null>(null)
  const total = slices.reduce((sum, row) => sum + row.amount_minor, 0)

  const chartSlices: ChartSlice[] = useMemo(() => {
    let deg = 0
    return slices.map((row, i) => {
      const startDeg = deg
      const endDeg = i === slices.length - 1 ? 360 : deg + (row.amount_minor / total) * 360
      deg = endDeg
      return {
        ...row,
        color: colors[i % colors.length],
        label: row.category || t('bills_uncategorized'),
        startDeg,
        endDeg,
        share: total > 0 ? row.amount_minor / total : 0,
      }
    })
  }, [slices, colors, total])

  const active = hover != null ? chartSlices[hover] : undefined

  return (
    <div onMouseLeave={() => setHover(null)}>
      <div className="mb-3">
        <div className="text-xs font-medium text-content-tertiary">{title}</div>
        <div className="text-sm font-semibold tabular-nums text-content mt-0.5">{totalLabel}</div>
      </div>

      {chartSlices.length === 0 ? (
        <p className="text-sm text-content-tertiary py-8 text-center">{t('bills_charts_empty')}</p>
      ) : (
        <>
          <div className="flex justify-center mb-4">
            <div className="relative w-[200px] h-[200px]">
              <svg viewBox={`0 0 ${VB} ${VB}`} className="w-full h-full overflow-visible">
                {chartSlices.map((slice, i) => {
                  const dimmed = hover != null && hover !== i
                  return (
                    <path
                      key={slice.category || `_uncat_${i}`}
                      d={slicePath(slice.startDeg, slice.endDeg, OUTER, INNER)}
                      fill={slice.color}
                      fillRule="evenodd"
                      className="cursor-pointer"
                      style={{
                        transform: hover === i ? 'scale(1.1)' : 'scale(1)',
                        transformBox: 'view-box',
                        transformOrigin: '50% 50%',
                        opacity: dimmed ? 0.35 : 1,
                        transition: 'transform 160ms ease, opacity 160ms ease',
                      }}
                      onMouseEnter={() => setHover(i)}
                    />
                  )
                })}
              </svg>
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                {active ? (
                  <div className="text-center leading-tight max-w-[96px] px-1">
                    <div className="text-xs text-content truncate">{active.label}</div>
                    <div className="text-sm font-semibold tabular-nums text-content mt-0.5">
                      {formatMinor(active.amount_minor, currency)}
                    </div>
                    <div className="text-xs tabular-nums text-content-tertiary">
                      {t('bills_share').replace('{n}', (active.share * 100).toFixed(1))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
          <ul className="grid gap-0.5">
            {chartSlices.map((row, i) => (
              <li
                key={row.category || `_uncat_${i}`}
                className={`flex items-center gap-2 min-w-0 text-xs rounded-btn px-1.5 py-1 -mx-1.5 cursor-pointer transition-colors ${
                  hover === i ? 'bg-inset' : 'hover:bg-inset'
                }`}
                onMouseEnter={() => setHover(i)}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: row.color }} />
                <span className="text-content truncate">{row.label}</span>
                <span className="flex-1" />
                <span className="tabular-nums text-content-secondary flex-shrink-0">
                  {formatMinor(row.amount_minor, currency)}
                </span>
                <span className="tabular-nums text-content-tertiary w-11 text-right flex-shrink-0">
                  {t('bills_share').replace('{n}', (row.share * 100).toFixed(0))}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
}

function slicePath(startDeg: number, endDeg: number, outerR: number, innerR: number): string {
  const sweep = Math.max(0, Math.min(360, endDeg - startDeg))
  if (sweep >= 359.99) {
    const [ox, oy] = polar(CX, CY, outerR, 0)
    const [ox2, oy2] = polar(CX, CY, outerR, 180)
    const [ix, iy] = polar(CX, CY, innerR, 0)
    const [ix2, iy2] = polar(CX, CY, innerR, 180)
    return [
      `M ${ox} ${oy}`,
      `A ${outerR} ${outerR} 0 1 1 ${ox2} ${oy2}`,
      `A ${outerR} ${outerR} 0 1 1 ${ox} ${oy}`,
      `M ${ix} ${iy}`,
      `A ${innerR} ${innerR} 0 1 0 ${ix2} ${iy2}`,
      `A ${innerR} ${innerR} 0 1 0 ${ix} ${iy}`,
    ].join(' ')
  }

  const [x1, y1] = polar(CX, CY, outerR, startDeg)
  const [x2, y2] = polar(CX, CY, outerR, endDeg)
  const [x3, y3] = polar(CX, CY, innerR, endDeg)
  const [x4, y4] = polar(CX, CY, innerR, startDeg)
  const large = sweep > 180 ? 1 : 0
  return [
    `M ${x1} ${y1}`,
    `A ${outerR} ${outerR} 0 ${large} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${innerR} ${innerR} 0 ${large} 0 ${x4} ${y4}`,
    'Z',
  ].join(' ')
}
