import React, { useEffect, useMemo, useState } from 'react'
import { Loader2, Receipt } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import type { PeriodStatement, PeriodType } from '../../types'
import { PeriodCard } from './PeriodCard'
import { LedgerList } from './LedgerList'
import PageHeader from '../../components/PageHeader'

interface PeriodListProps {
  baseUrl: string
  onSelect: (statement: PeriodStatement) => void
}

type HomeTab = PeriodType | 'ledger'

export const PeriodList: React.FC<PeriodListProps> = ({ baseUrl, onSelect }) => {
  const [tab, setTab] = useState<HomeTab>('ledger')
  const [year, setYear] = useState(() => new Date().getFullYear())
  const [rows, setRows] = useState<PeriodStatement[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
  }, [baseUrl])

  useEffect(() => {
    if (tab === 'ledger') return
    let cancelled = false
    setLoading(true)
    apiClient
      .getPeriodStatements(tab)
      .then((list) => {
        if (!cancelled) setRows(list)
      })
      .catch((err) => {
        console.error('Failed to load statements:', err)
        if (!cancelled) setRows([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tab, baseUrl])

  const years = useMemo(() => {
    const nowYear = new Date().getFullYear()
    return [...new Set([nowYear + 1, nowYear, nowYear - 1, year, ...rows.map((row) => row.year)])]
      .filter((y) => Number.isFinite(y))
      .sort((a, b) => b - a)
  }, [rows, year])

  const statements = useMemo(
    () =>
      tab === 'ledger'
        ? []
        : rows
            .filter((row) => row.period_type === tab)
            .filter((row) => tab !== 'monthly' || row.year === year)
            .sort((a, b) => {
              if (a.year !== b.year) return b.year - a.year
              return (b.month ?? 0) - (a.month ?? 0)
            }),
    [tab, year, rows],
  )

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader>
        <h2 className="text-xl font-bold text-content">{t('bills_title')}</h2>
        <p className="text-xs text-content-tertiary mt-1">{t('bills_desc')}</p>

        <div className="relative mt-3 flex items-center justify-center min-h-[52px]">
          {tab === 'monthly' && (
            <div className="absolute left-0">
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className="h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content cursor-pointer"
              >
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex items-stretch gap-1 bg-inset rounded-btn p-0.5">
            <TabBtn
              label={t('bills_tab_ledger')}
              active={tab === 'ledger'}
              onClick={() => setTab('ledger')}
            />
            <TabBtn
              label={t('bills_tab_monthly')}
              active={tab === 'monthly'}
              onClick={() => setTab('monthly')}
            />
            <TabBtn
              label={t('bills_tab_yearly')}
              active={tab === 'yearly'}
              onClick={() => setTab('yearly')}
            />
          </div>
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-5">
          {tab === 'ledger' ? (
            <LedgerList baseUrl={baseUrl} />
          ) : loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('bills_loading')}
            </div>
          ) : statements.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Receipt size={32} className="mb-3 text-content-tertiary opacity-60" />
              <p className="text-content font-medium mb-1">{t('bills_empty')}</p>
              <p className="text-sm text-content-tertiary max-w-sm">{t('bills_empty_guide')}</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {statements.map((row) => (
                <PeriodCard key={row.id} statement={row} onClick={() => onSelect(row)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const TabBtn: React.FC<{
  label: string
  active: boolean
  onClick: () => void
}> = ({ label, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`inline-flex flex-col items-center gap-1 px-3 py-2 rounded-[6px] text-sm font-medium cursor-pointer transition-colors ${
      active ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    <span>{label}</span>
  </button>
)
