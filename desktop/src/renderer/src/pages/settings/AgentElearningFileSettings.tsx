import React, { useEffect, useState } from 'react'
import { FolderDown, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { ElearningSettings } from '../../types'
import { Group, Row, Toggle } from './primitives'

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

  const footer = settings && <div className="flex items-center justify-end gap-3">
    {saved && <span role="status" className="text-xs text-success">{t('agent_elearning_file_saved')}</span>}
    <button type="button" disabled={busy || (enabled && (!ready || !root))} onClick={() => void save()}
      className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:bg-accent-hover disabled:opacity-50">
      {t('config_save')}
    </button>
  </div>

  return <Group title={t('settings_group_course_files')} description={t('agent_elearning_file_help')} footer={footer}>
    {loading && <p className="flex items-center gap-2 px-4 py-3.5 text-sm text-content-tertiary"><Loader2 size={16} className="animate-spin" />{t('briefing_loading')}</p>}
    {error && <p role="alert" className="px-4 py-3.5 text-sm text-danger">{error}</p>}
    {settings && <>
      <Row
        label={t('agent_elearning_file_title')}
        hint={!ready ? t('agent_elearning_file_account_required')
          : settings.courses.length ? t('agent_elearning_file_courses').replace('{count}', String(settings.courses.length))
          : t('agent_elearning_file_allow')}
        control={<Toggle label={t('agent_elearning_file_allow')} checked={enabled} disabled={busy || (!ready && !enabled)}
          onChange={(value) => { setEnabled(value); setSaved(false) }} />}
      />
      <Row
        label={t('agent_elearning_file_root')}
        hint={enabled && !root
          ? <span className="text-danger">{t('agent_elearning_file_root_required')}</span>
          : <span className="break-all">{root || '—'}</span>}
        control={<button type="button" disabled={busy || !ready} onClick={() => void (async () => {
          try {
            const path = await window.electronAPI?.selectDirectory?.()
            if (path) { setRoot(path); setSaved(false) }
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : String(cause))
          }
        })()} className="inline-flex items-center gap-1.5 rounded-btn border border-default px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50">
          <FolderDown size={14} />{t('agent_elearning_file_choose')}
        </button>}
      />
    </>}
  </Group>
}

export default AgentElearningFileSettings
