import React, { useEffect, useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import type { PeriodStatement, PeriodStatementItem } from '../../types'
import { formatDateTime, formatMinor, formatPeriodRange, periodLabel } from './helpers'
import { PeriodCharts } from './PeriodCharts'
import { PeriodRankings } from './PeriodRankings'

interface PeriodDetailProps {
  baseUrl: string
  statement: PeriodStatement
  onBack: () => void
}

export const PeriodDetail: React.FC<PeriodDetailProps> = ({ baseUrl, statement, onBack }) => {
  const [detail, setDetail] = useState<PeriodStatement>(statement)
  const [items, setItems] = useState<PeriodStatementItem[]>([])
  const [loading, setLoading] = useState(true)
  const open = detail.status === 'open'

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let cancelled = false
    setLoading(true)
    apiClient
      .getPeriodStatement(statement.id)
      .then((row) => {
        if (cancelled) return
        const { items: nextItems, ...rest } = row
        setDetail(rest)
        setItems(nextItems)
      })
      .catch((err) => {
        console.error('Failed to load statement:', err)
        if (!cancelled) setItems([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [baseUrl, statement.id])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center gap-3 px-6 py-3 flex-shrink-0 border-b border-subtle">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-sm text-content-secondary hover:bg-inset border border-strong transition-colors cursor-pointer"
        >
          <ArrowLeft size={14} />
          {t('bills_back')}
        </button>
        <h3 className="text-sm font-semibold text-content truncate">{periodLabel(detail)}</h3>
        <span
          className={`text-xs px-2 py-0.5 rounded-btn flex-shrink-0 ${
            open ? 'bg-accent-soft text-accent' : 'bg-inset text-content-tertiary'
          }`}
        >
          {open ? t('bills_status_open') : t('bills_status_closed')}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-content-tertiary">
            <Loader2 size={18} className="animate-spin mr-2" />
            {t('bills_loading')}
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-6 py-5 grid gap-4">
            <section className="rounded-card border border-default bg-surface p-4">
              <div className="grid grid-cols-3 gap-3">
                <Metric
                  label={t('bills_income')}
                  value={formatMinor(detail.income_minor, detail.currency)}
                  tone="success"
                />
                <Metric
                  label={t('bills_expense')}
                  value={formatMinor(detail.expense_minor, detail.currency)}
                  tone="danger"
                />
                <Metric
                  label={t('bills_net')}
                  value={formatMinor(detail.net_minor, detail.currency)}
                />
              </div>
              <div className="mt-4 pt-3 border-t border-subtle grid gap-1 text-xs text-content-tertiary">
                <div>
                  {t('bills_period')}
                  {' · '}
                  {formatPeriodRange(detail)}
                </div>
                <div>
                  {t('bills_generated')}
                  {' · '}
                  {formatDateTime(detail.generated_at)}
                </div>
                {detail.note ? <div>{detail.note}</div> : null}
              </div>
            </section>

            <PeriodCharts statement={detail} items={items} />
            <PeriodRankings items={items} currency={detail.currency} />
          </div>
        )}
      </div>
    </div>
  )
}

const Metric: React.FC<{ label: string; value: string; tone?: 'success' | 'danger' }> = ({
  label,
  value,
  tone,
}) => (
  <div>
    <div className="text-xs text-content-tertiary mb-1">{label}</div>
    <div
      className={`text-base font-semibold tabular-nums ${
        tone === 'success' ? 'text-success' : tone === 'danger' ? 'text-danger' : 'text-content'
      }`}
    >
      {value}
    </div>
  </div>
)
