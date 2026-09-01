import React, { useState } from 'react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import { Btn, Field, Modal, TextInput } from '../settings/primitives'
import { monthDateRange } from './helpers'

interface LedgerExportProps {
  year: number
  month: number
  onClose: () => void
}

export const LedgerExport: React.FC<LedgerExportProps> = ({ year, month, onClose }) => {
  const initial = monthDateRange(year, month)
  const [start, setStart] = useState(initial.start)
  const [end, setEnd] = useState(initial.end)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const exportFile = async () => {
    if (!start || !end) {
      setError(t('bills_ledger_export_invalid'))
      return
    }
    if (start > end) {
      setError(t('bills_ledger_export_invalid'))
      return
    }
    setBusy(true)
    setError('')
    try {
      const blob = await apiClient.exportLedgerXlsx(start, end)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `bills-${start}-${end}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      onClose()
    } catch (err) {
      console.error('Failed to export ledger:', err)
      setError(t('bills_ledger_export_failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={t('bills_ledger_export_title')}
      onClose={onClose}
      footer={
        <>
          <Btn variant="ghost" onClick={onClose} disabled={busy}>
            {t('task_cancel')}
          </Btn>
          <Btn variant="primary" onClick={exportFile} disabled={busy}>
            {t('bills_ledger_export')}
          </Btn>
        </>
      }
    >
      <Field label={t('bills_ledger_export_start')}>
        <TextInput type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </Field>
      <Field label={t('bills_ledger_export_end')} hint={t('bills_ledger_export_hint')}>
        <TextInput type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
      {error && <p className="text-xs text-danger">{error}</p>}
    </Modal>
  )
}
