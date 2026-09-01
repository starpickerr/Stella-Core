import React from 'react'
import { t } from '../../i18n'
import type { PeriodStatement } from '../../types'
import { formatMinor, periodLabel } from './helpers'

interface PeriodCardProps {
  statement: PeriodStatement
  onClick: () => void
}

export const PeriodCard: React.FC<PeriodCardProps> = ({ statement, onClick }) => {
  const open = statement.status === 'open'
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-card border border-default bg-surface p-4 cursor-pointer hover:border-strong transition-colors"
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="font-medium text-sm text-content">{periodLabel(statement)}</span>
        <div className="flex-1" />
        <span
          className={`text-xs px-2 py-0.5 rounded-btn ${
            open ? 'bg-accent-soft text-accent' : 'bg-inset text-content-tertiary'
          }`}
        >
          {open ? t('bills_status_open') : t('bills_status_closed')}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-xs">
        <Metric label={t('bills_income')} value={formatMinor(statement.income_minor, statement.currency)} tone="success" />
        <Metric label={t('bills_expense')} value={formatMinor(statement.expense_minor, statement.currency)} tone="danger" />
        <Metric label={t('bills_net')} value={formatMinor(statement.net_minor, statement.currency)} />
      </div>
    </button>
  )
}

const Metric: React.FC<{ label: string; value: string; tone?: 'success' | 'danger' }> = ({
  label,
  value,
  tone,
}) => (
  <div>
    <div className="text-content-tertiary mb-0.5">{label}</div>
    <div
      className={`font-medium tabular-nums ${
        tone === 'success' ? 'text-success' : tone === 'danger' ? 'text-danger' : 'text-content'
      }`}
    >
      {value}
    </div>
  </div>
)
