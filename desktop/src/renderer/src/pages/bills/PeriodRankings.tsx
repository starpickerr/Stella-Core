import React, { useMemo, useState } from 'react'
import { t } from '../../i18n'
import type { LedgerEntryType, PeriodStatementItem } from '../../types'
import { formatMinor } from './helpers'

interface PeriodRankingsProps {
  items: PeriodStatementItem[]
  currency: string
}

export const PeriodRankings: React.FC<PeriodRankingsProps> = ({ items, currency }) => {
  const [entryType, setEntryType] = useState<LedgerEntryType>('expense')

  const rows = useMemo(
    () =>
      items
        .filter((row) => row.entry_type === entryType)
        .sort((a, b) => b.amount_minor - a.amount_minor),
    [items, entryType],
  )

  const total = rows.reduce((sum, row) => sum + row.amount_minor, 0)
  const max = rows[0]?.amount_minor ?? 0
  const barTone = entryType === 'expense' ? 'bg-danger' : 'bg-success'

  return (
    <section className="rounded-card border border-default bg-surface p-4">
      <div className="flex items-center gap-3 mb-4">
        <h4 className="text-sm font-semibold text-content">{t('bills_rankings_title')}</h4>
        <div className="flex-1" />
        <div className="flex items-stretch gap-1 bg-inset rounded-btn p-0.5">
          <TabBtn
            label={t('bills_expense')}
            active={entryType === 'expense'}
            onClick={() => setEntryType('expense')}
          />
          <TabBtn
            label={t('bills_income')}
            active={entryType === 'income'}
            onClick={() => setEntryType('income')}
          />
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-content-tertiary py-6 text-center">{t('bills_rankings_empty')}</p>
      ) : (
        <ol className="grid gap-3">
          {rows.map((row, i) => {
            const share = total > 0 ? row.amount_minor / total : 0
            const width = max > 0 ? (row.amount_minor / max) * 100 : 0
            const title = row.name || row.category || t('bills_uncategorized')
            const subtitle = row.category && row.category !== title ? row.category : ''
            return (
              <li key={row.id}>
                <div className="flex items-baseline gap-2 text-sm mb-0.5">
                  <span className="w-4 text-xs tabular-nums text-content-tertiary flex-shrink-0">{i + 1}</span>
                  <span className="font-medium text-content truncate">{title}</span>
                  <span className="flex-1" />
                  <span
                    className={`tabular-nums font-medium ${
                      entryType === 'expense' ? 'text-danger' : 'text-success'
                    }`}
                  >
                    {formatMinor(row.amount_minor, currency)}
                  </span>
                </div>
                <div className="pl-6 mb-1 text-xs text-content-tertiary">
                  {subtitle ? `${subtitle} · ` : ''}
                  {t('bills_entry_count').replace('{n}', String(row.entry_count))}
                  {' · '}
                  {t('bills_share').replace('{n}', (share * 100).toFixed(1))}
                </div>
                <div className="pl-6 h-1.5 rounded-full bg-inset overflow-hidden">
                  <div className={`h-full rounded-full ${barTone}`} style={{ width: `${width}%` }} />
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

const TabBtn: React.FC<{ label: string; active: boolean; onClick: () => void }> = ({
  label,
  active,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className={`px-3 py-1 rounded-[6px] text-xs font-medium cursor-pointer transition-colors ${
      active ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    {label}
  </button>
)
