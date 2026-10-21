import React, { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { FolderDown, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { getLang, t } from '../../i18n'
import { Group, Row } from './primitives'

const ElearningFileSettings: React.FC = () => {
  const [root, setRoot] = useState('')
  const [savedRoot, setSavedRoot] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [syncMessage, setSyncMessage] = useState('')
  const syncRequest = useRef<AbortController | null>(null)
  const location = useLocation()
  const zh = getLang() === 'zh'

  useEffect(() => {
    let active = true
    apiClient.getElearningFileSyncSettings()
      .then(value => { if (active) { setRoot(value.file_sync_root); setSavedRoot(value.file_sync_root) } })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : String(cause)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false; syncRequest.current?.abort() }
  }, [])

  const save = async () => {
    if (busy || loading) return
    setBusy(true); setSaved(false); setError('')
    try {
      const settings = await apiClient.saveElearningFileSyncSettings(root)
      setRoot(settings.file_sync_root); setSavedRoot(settings.file_sync_root); setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally { setBusy(false) }
  }
  const edit = (value: string) => { setRoot(value); setSaved(false); setSyncMessage('') }
  const sync = async () => {
    if (busy || loading || !savedRoot || savedRoot !== root) return
    const controller = new AbortController()
    syncRequest.current = controller
    setBusy(true); setError(''); setSaved(false); setSyncMessage('')
    const params = new URLSearchParams(location.search)
    const scope = { agent: params.get('agent') || '', session: params.get('session') || '' }
    try {
      let offset = 0
      let processed = 0
      while (!controller.signal.aborted) {
        const result = await apiClient.syncElearningFiles(offset, controller.signal, scope)
        if (controller.signal.aborted) return
        processed += result.processed
        setSyncMessage(zh ? `已处理 ${processed} 个文件` : `Processed ${processed} files`)
        if (result.errors.length) { setError(result.errors.join('\n')); return }
        if (result.next_offset === null) return
        if (result.next_offset <= offset) throw new Error(zh ? '同步进度无效，请刷新后重试' : 'Invalid sync progress. Refresh and retry.')
        offset = result.next_offset
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause))
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }
  const footer = <div className="flex items-center justify-end gap-3">
    {saved && <span role="status" className="text-xs text-success">{t('elearning_file_saved')}</span>}
    {syncMessage && <span role="status" className="text-xs text-content-secondary">{syncMessage}</span>}
    <button type="button" disabled={busy || loading || !savedRoot || root !== savedRoot} onClick={() => void sync()}
      className="rounded-btn border border-default px-3 py-2 text-sm hover:bg-surface-2 disabled:opacity-50">{zh ? '同步课程文件' : 'Sync course files'}</button>
    <button type="button" disabled={busy || loading} onClick={() => void save()}
      className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:bg-accent-hover disabled:opacity-50">
      {t('config_save')}
    </button>
  </div>

  return <Group title={t('settings_group_course_files')} description={t('elearning_file_help')} footer={footer}>
    {loading && <p role="status" className="flex items-center gap-2 px-4 py-3.5 text-sm text-content-tertiary"><Loader2 size={16} className="animate-spin" />{t('briefing_loading')}</p>}
    {error && <p role="alert" className="px-4 py-3.5 text-sm text-danger whitespace-pre-wrap">{error}</p>}
    <p className="px-4 py-3 text-xs text-content-secondary">{zh ? '按需同步所选课程的文件。先保存目录，再开始同步；已修改的本地文件会保留。' : 'Sync files from selected courses on demand. Save the directory first. Locally modified files are preserved.'}</p>
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
