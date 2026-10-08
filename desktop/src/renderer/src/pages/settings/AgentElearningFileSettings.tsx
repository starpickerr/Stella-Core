import React, { useEffect, useState } from 'react'
import { FolderDown, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { ElearningSettings } from '../../types'
import { Card } from './primitives'

const AgentElearningFileSettings: React.FC = () => {
  const [settings, setSettings] = useState<ElearningSettings | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [root, setRoot] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const show = (value: ElearningSettings) => {
    setSettings(value)
    setEnabled(value.file_sync_enabled)
    setRoot(value.file_sync_root)
  }

  useEffect(() => {
    let active = true
    apiClient.getElearningFileSyncSettings()
      .then((value) => { if (active) show(value) })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const save = async () => {
    setBusy(true)
    setSaved(false)
    setError('')
    try {
      show(await apiClient.saveElearningFileSyncSettings(enabled, root))
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const ready = !!settings?.configured

  return <Card icon={<FolderDown size={16} />} title={t('agent_elearning_file_title')} subtitle={t('agent_elearning_file_help')}>
    <div className="space-y-4">
      {loading && <p className="flex items-center gap-2 text-sm text-content-tertiary"><Loader2 size={16} className="animate-spin" />{t('briefing_loading')}</p>}
      {error && <p role="alert" className="rounded-card bg-danger-soft p-3 text-sm text-danger">{error}</p>}
      {settings && <>
        {!ready && <p className="text-sm text-content-tertiary">{t('agent_elearning_file_account_required')}</p>}
        {!!settings.courses.length && <p className="text-xs text-content-tertiary">
          {t('agent_elearning_file_courses').replace('{count}', String(settings.courses.length))}
        </p>}
        <label className="flex items-center gap-2 text-sm text-content-secondary">
          <input type="checkbox" checked={enabled} disabled={busy || (!ready && !enabled)}
            onChange={(event) => { setEnabled(event.target.checked); setSaved(false) }} />
          {t('agent_elearning_file_allow')}
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-content-secondary">{t('agent_elearning_file_root')}</span>
          <span className="min-w-0 flex-1 break-all text-sm text-content">{root || '—'}</span>
          <button type="button" disabled={busy || !ready} onClick={() => void (async () => {
            try {
              const path = await window.electronAPI?.selectDirectory?.()
              if (path) { setRoot(path); setSaved(false) }
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : String(cause))
            }
          })()} className="rounded-btn border border-default px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50">
            {t('agent_elearning_file_choose')}
          </button>
        </div>
        {enabled && !root && <p className="text-xs text-danger">{t('agent_elearning_file_root_required')}</p>}
        <div className="flex items-center justify-end gap-3">
          {saved && <span role="status" className="text-xs text-success">{t('agent_elearning_file_saved')}</span>}
          <button type="button" disabled={busy || (enabled && (!ready || !root))} onClick={() => void save()}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:bg-accent-hover disabled:opacity-50">
            {t('config_save')}
          </button>
        </div>
      </>}
    </div>
  </Card>
}

export default AgentElearningFileSettings
