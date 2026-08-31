import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Loader2, Plus, Receipt } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import type { LedgerEntry } from '../../types'
import { LedgerEditor } from './LedgerEditor'
import { LedgerExport } from './LedgerExport'
import {
  formatClock,
  formatDayHeading,
  formatMinor,
  groupLedgerByDay,
  monthLabel,
} from './helpers'

interface LedgerListProps {
  baseUrl: string
}

export const LedgerList: React.FC<LedgerListProps> = ({ baseUrl }) => {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [entries, setEntries] = useState<LedgerEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<LedgerEntry | 'new' | null>(null)
  const [exporting, setExporting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await apiClient.getLedgerEntries(year, month)
      setEntries(rows)
    } catch (err) {
      console.error('Failed to load ledger:', err)
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [year, month])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void load()
  }, [baseUrl, load])

  const years = useMemo(() => {
    const nowYear = new Date().getFullYear()
    const fromData = entries.map((row) => new Date(row.occurred_at).getFullYear())
    return [...new Set([nowYear + 1, nowYear, nowYear - 1, year, ...fromData])]
      .filter((y) => Number.isFinite(y))
      .sort((a, b) => b - a)
  }, [entries, year])

  const groups = useMemo(() => groupLedgerByDay(entries), [entries])
  const income = entries
    .filter((row) => row.entry_type === 'income')
    .reduce((s, row) => s + row.amount_minor, 0)
  const expense = entries
    .filter((row) => row.entry_type === 'expense')
    .reduce((s, row) => s + row.amount_minor, 0)

  const save = async (entry: LedgerEntry) => {
    const payload = {
      amount_minor: entry.amount_minor,
      currency: entry.currency,
      category: entry.category,
      name: entry.name,
      note: entry.note,
      entry_type: entry.entry_type,
      txn_type: entry.txn_type,
      counterparty: entry.counterparty,
      occurred_at: entry.occurred_at,
      status: entry.status,
    }
    if (editing === 'new' || !entry.id) {
      await apiClient.createLedgerEntry(payload)
    } else {
      await apiClient.updateLedgerEntry(entry.id, payload)
    }
    await load()
    setEditing(null)
  }

  const remove = async (id: string) => {
    await apiClient.deleteLedgerEntry(id)
    await load()
    setEditing(null)
  }

  return (
    <>
      <div className="flex items-center gap-2 mb-4">
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
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content cursor-pointer"
        >
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
            </option>
          ))}
        </select>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
        >
          <Plus size={14} />
          {t('bills_ledger_add')}
        </button>
        <button
          type="button"
          onClick={() => setExporting(true)}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn border border-strong text-content-secondary hover:bg-surface-2 text-sm font-medium cursor-pointer transition-colors"
        >
          <Download size={14} />
          {t('bills_ledger_export')}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 size={18} className="animate-spin mr-2" />
          {t('bills_loading')}
        </div>
      ) : (
        <>
          {entries.length > 0 && (
            <div className="grid grid-cols-3 gap-3 mb-5 text-xs">
              <Metric label={t('bills_income')} value={formatMinor(income)} tone="success" />
              <Metric label={t('bills_expense')} value={formatMinor(expense)} tone="danger" />
              <Metric label={t('bills_net')} value={formatMinor(income - expense)} />
            </div>
          )}

          {groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Receipt size={32} className="mb-3 text-content-tertiary opacity-60" />
              <p className="text-content font-medium mb-1">{t('bills_ledger_empty')}</p>
              <p className="text-sm text-content-tertiary max-w-sm">{t('bills_ledger_empty_guide')}</p>
            </div>
          ) : (
            <div className="grid gap-5">
              {groups.map((group) => (
                <section key={group.date}>
                  <div className="sticky top-0 z-10 bg-base flex items-baseline gap-2 py-1.5 mb-2">
                    <h5 className="text-sm font-semibold text-content">{formatDayHeading(group.date)}</h5>
                    <span className="flex-1" />
                    <span className="text-xs tabular-nums text-danger">
                      {t('bills_expense')} {formatMinor(group.expense_minor)}
                    </span>
                    <span className="text-xs tabular-nums text-success">
                      {t('bills_income')} {formatMinor(group.income_minor)}
                    </span>
                  </div>
                  <div className="rounded-card border border-default bg-surface overflow-hidden">
                    {group.rows.map((row) => (
                      <button
                        key={row.id}
                        type="button"
                        onClick={() => setEditing(row)}
                        className="w-full text-left px-4 py-3 flex items-center gap-3 border-b border-subtle last:border-0 hover:bg-inset cursor-pointer transition-colors"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-content truncate">{row.name}</div>
                          <div className="text-xs text-content-tertiary mt-0.5 truncate">
                            {row.category || t('bills_uncategorized')}
                            {' · '}
                            {formatClock(row.occurred_at)}
                          </div>
                        </div>
                        <span
                          className={`text-sm font-medium tabular-nums flex-shrink-0 ${
                            row.entry_type === 'expense' ? 'text-danger' : 'text-success'
                          }`}
                        >
                          {row.entry_type === 'expense' ? '-' : '+'}
                          {formatMinor(row.amount_minor, row.currency)}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {editing != null && (
        <LedgerEditor
          entry={editing === 'new' ? null : editing}
          year={year}
          month={month}
          onClose={() => setEditing(null)}
          onSave={save}
          onDelete={editing === 'new' ? undefined : remove}
        />
      )}
      {exporting && (
        <LedgerExport year={year} month={month} onClose={() => setExporting(false)} />
      )}
    </>
  )
}

const Metric: React.FC<{ label: string; value: string; tone?: 'success' | 'danger' }> = ({
  label,
  value,
  tone,
}) => (
  <div className="rounded-card border border-default bg-surface p-3">
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
