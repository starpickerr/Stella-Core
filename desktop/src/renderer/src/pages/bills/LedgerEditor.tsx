import React, { useState } from 'react'
import { t } from '../../i18n'
import type { LedgerEntry, LedgerEntryType } from '../../types'
import { Btn, Dropdown, Field, Modal, TextInput } from '../settings/primitives'
import {
  defaultLedgerLocalTime,
  fromDatetimeLocal,
  parseYuanToMinor,
  toDatetimeLocal,
  yuanFromMinor,
} from './helpers'

interface LedgerEditorProps {
  entry: LedgerEntry | null
  year: number
  month: number
  onClose: () => void
  onSave: (entry: LedgerEntry) => Promise<void>
  onDelete?: (id: string) => Promise<void>
}

export const LedgerEditor: React.FC<LedgerEditorProps> = ({
  entry,
  year,
  month,
  onClose,
  onSave,
  onDelete,
}) => {
  const creating = entry == null
  const [entryType, setEntryType] = useState<LedgerEntryType>(entry?.entry_type ?? 'expense')
  const [name, setName] = useState(entry?.name ?? '')
  const [category, setCategory] = useState(entry?.category ?? '')
  const [amount, setAmount] = useState(entry ? yuanFromMinor(entry.amount_minor) : '')
  const [occurredLocal, setOccurredLocal] = useState(
    entry ? toDatetimeLocal(entry.occurred_at) : defaultLedgerLocalTime(year, month),
  )
  const [note, setNote] = useState(entry?.note ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError(t('bills_ledger_name_required'))
      return
    }
    const amountMinor = parseYuanToMinor(amount)
    if (amountMinor == null || amountMinor <= 0) {
      setError(t('bills_ledger_amount_invalid'))
      return
    }
    if (!occurredLocal) {
      setError(t('bills_ledger_time_required'))
      return
    }
    const now = new Date().toISOString()
    const occurredAt = fromDatetimeLocal(occurredLocal)
    setBusy(true)
    setError('')
    try {
      await onSave({
        id: entry?.id ?? '',
        amount_minor: amountMinor,
        currency: entry?.currency ?? 'CNY',
        category: category.trim(),
        name: trimmed,
        note: note.trim(),
        entry_type: entryType,
        txn_type: entry?.txn_type || category.trim(),
        counterparty: entry?.counterparty ?? '',
        occurred_at: occurredAt,
        status: entry?.status ?? 'posted',
        created_at: entry?.created_at ?? now,
        updated_at: now,
      })
    } catch (err) {
      console.error('Failed to save ledger:', err)
      setError(t('bills_save_failed'))
    } finally {
      setBusy(false)
    }
  }

  const del = async () => {
    if (!entry || !onDelete) return
    if (!window.confirm(t('bills_ledger_delete_confirm'))) return
    setBusy(true)
    setError('')
    try {
      await onDelete(entry.id)
    } catch (err) {
      console.error('Failed to delete ledger:', err)
      setError(t('bills_delete_failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={creating ? t('bills_ledger_add') : t('bills_ledger_edit')}
      onClose={onClose}
      footer={
        <>
          {!creating && onDelete && (
            <Btn variant="danger" onClick={del} disabled={busy} className="mr-auto">
              {t('task_delete')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose} disabled={busy}>
            {t('task_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={busy}>
            {t('task_save')}
          </Btn>
        </>
      }
    >
      <Field label={t('bills_ledger_type')}>
        <Dropdown
          value={entryType}
          onChange={(v) => setEntryType(v as LedgerEntryType)}
          options={[
            { value: 'expense', label: t('bills_expense') },
            { value: 'income', label: t('bills_income') },
          ]}
        />
      </Field>
      <Field label={t('bills_ledger_name')}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label={t('bills_ledger_category')}>
        <TextInput value={category} onChange={(e) => setCategory(e.target.value)} />
      </Field>
      <Field label={t('bills_ledger_amount')} hint={t('bills_ledger_amount_hint')}>
        <TextInput
          type="number"
          min="0"
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </Field>
      <Field label={t('bills_ledger_time')}>
        <TextInput
          type="datetime-local"
          value={occurredLocal}
          onChange={(e) => setOccurredLocal(e.target.value)}
        />
      </Field>
      <Field label={t('bills_ledger_note')}>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors resize-none"
        />
      </Field>
      {error && <p className="text-xs text-danger">{error}</p>}
    </Modal>
  )
}
