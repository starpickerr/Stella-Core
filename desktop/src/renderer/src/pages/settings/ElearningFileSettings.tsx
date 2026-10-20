import React, { useEffect, useState } from 'react'
import { FolderDown, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import { Group, Row } from './primitives'

const ElearningFileSettings: React.FC = () => {
  const [root, setRoot] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    apiClient.getElearningFileSyncSettings()
      .then(value => { if (active) setRoot(value.file_sync_root) })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : String(cause)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const save = async () => {
    if (busy || loading) return
    setBusy(true); setSaved(false); setError('')
    try {
      const settings = await apiClient.saveElearningFileSyncSettings(root)
      setRoot(settings.file_sync_root); setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally { setBusy(false) }
  }
  const edit = (value: string) => { setRoot(value); setSaved(false) }
  const footer = <div className="flex items-center justify-end gap-3">
    {saved && <span role="status" className="text-xs text-success">{t('elearning_file_saved')}</span>}
    <button type="button" disabled={busy || loading} onClick={() => void save()}
      className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:bg-accent-hover disabled:opacity-50">
      {t('config_save')}
    </button>
  </div>

  return <Group title={t('settings_group_course_files')} description={t('elearning_file_help')} footer={footer}>
    {loading && <p role="status" className="flex items-center gap-2 px-4 py-3.5 text-sm text-content-tertiary"><Loader2 size={16} className="animate-spin" />{t('briefing_loading')}</p>}
    {error && <p role="alert" className="px-4 py-3.5 text-sm text-danger">{error}</p>}
    <Row label={t('elearning_file_root')} control={<div className="flex w-full min-w-0 flex-wrap items-center gap-2">
      <input aria-label={t('elearning_file_root')} value={root} disabled={busy || loading}
        onChange={event => edit(event.target.value)}
        className="min-w-0 flex-1 rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content disabled:opacity-50" />
      <button type="button" disabled={busy || loading} onClick={() => void (async () => {
        try {
          const path = await window.electronAPI?.selectDirectory?.()
          if (path) edit(path)
        } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
      })()} className="inline-flex items-center gap-1.5 rounded-btn border border-default px-3 py-2 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50">
        <FolderDown size={14} />{t('elearning_file_choose')}
      </button>
    </div>} />
  </Group>
}

export default ElearningFileSettings
