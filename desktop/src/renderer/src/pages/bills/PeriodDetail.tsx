import React, { useMemo } from 'react'
import { ArrowLeft } from 'lucide-react'
import { t } from '../../i18n'
import type { LedgerEntryType, PeriodStatement, PeriodStatementItem } from '../../types'
import { formatDateTime, formatMinor, formatPeriodRange, periodLabel } from './helpers'
import { PeriodCharts } from './PeriodCharts'
import { PeriodRankings } from './PeriodRankings'

interface PeriodDetailProps {
  baseUrl: string
  statement: PeriodStatement
  onBack: () => void
}

export const PeriodDetail: React.FC<PeriodDetailProps> = ({ statement, onBack }) => {
  const items = useMemo(() => MOCK_ITEMS[statement.id] ?? [], [statement.id])
  const open = statement.status === 'open'

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
        <h3 className="text-sm font-semibold text-content truncate">{periodLabel(statement)}</h3>
        <span
          className={`text-xs px-2 py-0.5 rounded-btn flex-shrink-0 ${
            open ? 'bg-accent-soft text-accent' : 'bg-inset text-content-tertiary'
          }`}
        >
          {open ? t('bills_status_open') : t('bills_status_closed')}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-5 grid gap-4">
          <section className="rounded-card border border-default bg-surface p-4">
            <div className="grid grid-cols-3 gap-3">
              <Metric
                label={t('bills_income')}
                value={formatMinor(statement.income_minor, statement.currency)}
                tone="success"
              />
              <Metric
                label={t('bills_expense')}
                value={formatMinor(statement.expense_minor, statement.currency)}
                tone="danger"
              />
              <Metric
                label={t('bills_net')}
                value={formatMinor(statement.net_minor, statement.currency)}
              />
            </div>
            <div className="mt-4 pt-3 border-t border-subtle grid gap-1 text-xs text-content-tertiary">
              <div>
                {t('bills_period')}
                {' · '}
                {formatPeriodRange(statement)}
              </div>
              <div>
                {t('bills_generated')}
                {' · '}
                {formatDateTime(statement.generated_at)}
              </div>
              {statement.note ? <div>{statement.note}</div> : null}
            </div>
          </section>

          <PeriodCharts statement={statement} items={items} />
          <PeriodRankings items={items} currency={statement.currency} />
        </div>
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

function item(
  statementId: string,
  n: number,
  category: string,
  name: string,
  entryType: LedgerEntryType,
  amountMinor: number,
  entryCount: number,
): PeriodStatementItem {
  return {
    id: `${statementId}-${entryType}-${n}`,
    statement_id: statementId,
    category,
    name,
    entry_type: entryType,
    amount_minor: amountMinor,
    entry_count: entryCount,
  }
}

// Placeholder rows matching period_statement_items. Replace with apiClient
// once the bills HTTP API exists. Amounts sum to the parent statement totals.
const MOCK_ITEMS: Record<string, PeriodStatementItem[]> = {
  'stmt-2026-08': [
    item('stmt-2026-08', 1, '工资', '月薪', 'income', 1200000, 1),
    item('stmt-2026-08', 2, '退款', '外卖', 'income', 80000, 2),
    item('stmt-2026-08', 1, '消费', '午餐', 'expense', 126000, 18),
    item('stmt-2026-08', 2, '消费', '晚餐', 'expense', 89000, 10),
    item('stmt-2026-08', 3, '消费', '咖啡', 'expense', 45600, 16),
    item('stmt-2026-08', 4, '消费', '超市', 'expense', 67300, 6),
    item('stmt-2026-08', 5, '交通', '地铁', 'expense', 32000, 20),
    item('stmt-2026-08', 6, '交通', '打车', 'expense', 18400, 4),
    item('stmt-2026-08', 7, '住房', '水电', 'expense', 42000, 2),
    item('stmt-2026-08', 8, '娱乐', '会员', 'expense', 32000, 2),
  ],
  'stmt-2026-07': [
    item('stmt-2026-07', 1, '工资', '月薪', 'income', 1200000, 1),
    item('stmt-2026-07', 2, '退款', '购物', 'income', 80000, 1),
    item('stmt-2026-07', 1, '住房', '房租', 'expense', 250000, 1),
    item('stmt-2026-07', 2, '消费', '午餐', 'expense', 142000, 20),
    item('stmt-2026-07', 3, '消费', '晚餐', 'expense', 110000, 14),
    item('stmt-2026-07', 4, '消费', '超市', 'expense', 45200, 5),
    item('stmt-2026-07', 5, '交通', '地铁', 'expense', 32000, 20),
    item('stmt-2026-07', 6, '娱乐', '电影', 'expense', 18600, 3),
    item('stmt-2026-07', 7, '医疗', '体检', 'expense', 12650, 1),
  ],
  'stmt-2026-06': [
    item('stmt-2026-06', 1, '工资', '月薪', 'income', 1200000, 1),
    item('stmt-2026-06', 2, '退款', '购物', 'income', 80000, 2),
    item('stmt-2026-06', 1, '消费', '午餐', 'expense', 118000, 16),
    item('stmt-2026-06', 2, '消费', '晚餐', 'expense', 76000, 9),
    item('stmt-2026-06', 3, '消费', '超市', 'expense', 52120, 4),
    item('stmt-2026-06', 4, '交通', '地铁', 'expense', 32000, 20),
    item('stmt-2026-06', 5, '消费', '咖啡', 'expense', 40000, 14),
    item('stmt-2026-06', 6, '娱乐', '游戏', 'expense', 30000, 1),
    item('stmt-2026-06', 7, '日用', '水电', 'expense', 40000, 2),
  ],
  'stmt-2026': [
    item('stmt-2026', 1, '工资', '工资', 'income', 9600000, 8),
    item('stmt-2026', 2, '退款', '退款', 'income', 320000, 12),
    item('stmt-2026', 3, '理财', '理财', 'income', 320000, 4),
    item('stmt-2026', 1, '住房', '住房', 'expense', 1750000, 8),
    item('stmt-2026', 2, '消费', '消费', 'expense', 890000, 214),
    item('stmt-2026', 3, '交通', '交通', 'expense', 256000, 160),
    item('stmt-2026', 4, '娱乐', '娱乐', 'expense', 184870, 28),
    item('stmt-2026', 5, '医疗', '医疗', 'expense', 130000, 6),
  ],
  'stmt-2025': [
    item('stmt-2025', 1, '工资', '工资', 'income', 13200000, 12),
    item('stmt-2025', 2, '理财', '理财', 'income', 980000, 8),
    item('stmt-2025', 3, '退款', '退款', 'income', 320000, 18),
    item('stmt-2025', 1, '住房', '住房', 'expense', 2400000, 12),
    item('stmt-2025', 2, '消费', '消费', 'expense', 1520000, 340),
    item('stmt-2025', 3, '交通', '交通', 'expense', 420000, 240),
    item('stmt-2025', 4, '娱乐', '娱乐', 'expense', 342300, 46),
    item('stmt-2025', 5, '医疗', '医疗', 'expense', 300000, 10),
  ],
}
