import React, { useMemo, useState } from 'react'
import { Loader2, Receipt } from 'lucide-react'
import { t } from '../../i18n'
import type { PeriodStatement, PeriodType } from '../../types'
import { PeriodCard } from './PeriodCard'

interface PeriodListProps {
  baseUrl: string
  onSelect: (statement: PeriodStatement) => void
}

// Placeholder rows matching period_statements. Replace with apiClient once the
// bills HTTP API exists.
const MOCK_STATEMENTS: PeriodStatement[] = [
  {
    id: 'stmt-2026-08',
    period_type: 'monthly',
    year: 2026,
    month: 8,
    start_at: '2026-08-01T00:00:00Z',
    end_at: '2026-09-01T00:00:00Z',
    currency: 'CNY',
    income_minor: 1280000,
    expense_minor: 452300,
    net_minor: 827700,
    status: 'open',
    note: '',
    generated_at: '2026-08-27T00:00:00Z',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
  },
  {
    id: 'stmt-2026-07',
    period_type: 'monthly',
    year: 2026,
    month: 7,
    start_at: '2026-07-01T00:00:00Z',
    end_at: '2026-08-01T00:00:00Z',
    currency: 'CNY',
    income_minor: 1280000,
    expense_minor: 610450,
    net_minor: 669550,
    status: 'closed',
    note: '',
    generated_at: '2026-08-01T00:00:00Z',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 'stmt-2026-06',
    period_type: 'monthly',
    year: 2026,
    month: 6,
    start_at: '2026-06-01T00:00:00Z',
    end_at: '2026-07-01T00:00:00Z',
    currency: 'CNY',
    income_minor: 1280000,
    expense_minor: 388120,
    net_minor: 891880,
    status: 'closed',
    note: '',
    generated_at: '2026-07-01T00:00:00Z',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
  },
  {
    id: 'stmt-2026',
    period_type: 'yearly',
    year: 2026,
    month: null,
    start_at: '2026-01-01T00:00:00Z',
    end_at: '2027-01-01T00:00:00Z',
    currency: 'CNY',
    income_minor: 10240000,
    expense_minor: 3210870,
    net_minor: 7029130,
    status: 'open',
    note: '',
    generated_at: '2026-08-27T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
  },
  {
    id: 'stmt-2025',
    period_type: 'yearly',
    year: 2025,
    month: null,
    start_at: '2025-01-01T00:00:00Z',
    end_at: '2026-01-01T00:00:00Z',
    currency: 'CNY',
    income_minor: 14500000,
    expense_minor: 4982300,
    net_minor: 9517700,
    status: 'closed',
    note: '',
    generated_at: '2026-01-01T00:00:00Z',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

export const PeriodList: React.FC<PeriodListProps> = ({ onSelect }) => {
  const [periodType, setPeriodType] = useState<PeriodType>('monthly')
  const [year, setYear] = useState(2026)
  const [loading] = useState(false)

  const years = useMemo(
    () => [...new Set(MOCK_STATEMENTS.map((row) => row.year))].sort((a, b) => b - a),
    [],
  )

  const statements = useMemo(
    () =>
      MOCK_STATEMENTS.filter((row) => row.period_type === periodType)
        .filter((row) => periodType !== 'monthly' || row.year === year)
        .sort((a, b) => {
          if (a.year !== b.year) return b.year - a.year
          return (b.month ?? 0) - (a.month ?? 0)
        }),
    [periodType, year],
  )

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-6 pt-5 pb-3 flex-shrink-0">
        <h2 className="text-xl font-bold text-content">{t('bills_title')}</h2>
        <p className="text-xs text-content-tertiary mt-1">{t('bills_desc')}</p>

        <div className="relative mt-3 flex items-center justify-center min-h-[52px]">
          {periodType === 'monthly' && (
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
              label={t('bills_tab_monthly')}
              active={periodType === 'monthly'}
              onClick={() => setPeriodType('monthly')}
            />
            <TabBtn
              label={t('bills_tab_yearly')}
              active={periodType === 'yearly'}
              onClick={() => setPeriodType('yearly')}
            />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-3xl mx-auto px-6 py-5">
          {loading ? (
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
    className={`inline-flex flex-col items-center gap-1 px-4 py-2 rounded-[6px] text-sm font-medium cursor-pointer transition-colors ${
      active ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    <span>{label}</span>
  </button>
)
