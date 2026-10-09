import React, { useEffect, useState } from 'react'
import { AlertCircle, CalendarDays, Check, RefreshCw, X } from 'lucide-react'
import apiClient from '../../api/client'
import type { AppleCalendarConnection, AppleCalendarSyncResult } from '../../types'

type Props = { en: boolean; onClose: () => void; onSynced: () => void }

const AppleCalendarPanel: React.FC<Props> = ({ en, onClose, onSynced }) => {
  const [connection, setConnection] = useState<AppleCalendarConnection | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [direction, setDirection] = useState<AppleCalendarConnection['direction']>('bidirectional')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AppleCalendarSyncResult | null>(null)

  const apply = (state: AppleCalendarConnection) => {
    setConnection(state)
    setSelected(state.calendar_ids)
    setDirection(state.direction)
  }
  useEffect(() => {
    let active = true
    apiClient.getAppleCalendar().then(state => { if (active) apply(state) })
      .catch(reason => { if (active) setError(String(reason)) })
    return () => { active = false }
  }, [])
  const run = async (action: () => Promise<{ connection: AppleCalendarConnection; result?: AppleCalendarSyncResult }>, refresh = false) => {
    setBusy(true); setError('')
    try {
      const response = await action()
      apply(response.connection)
      if (response.result) setResult(response.result)
      if (refresh) onSynced()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const connect = async () => {
    setBusy(true); setError('')
    try {
      const prepared = await apiClient.previewAppleCalendarScope(selected, direction)
      const { preview } = prepared
      const summary = en
        ? `Preview: ${preview.new} new, ${preview.updated} updated, ${preview.skipped} skipped, ${preview.conflicts} conflicts. Continue?`
        : `同步预览：新增 ${preview.new} 条，更新 ${preview.updated} 条，跳过 ${preview.skipped} 条，冲突 ${preview.conflicts} 条。确认执行？`
      if (!window.confirm(summary)) return
      const response = await apiClient.configureAppleCalendar(selected, direction, prepared.preview_token)
      apply(response.connection); setResult(response.result); onSynced()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const toggle = (id: string) => setSelected(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
  const supported = connection?.supported && connection.authorization !== 'unsupported' && connection.authorization !== 'helper_missing'
  const authorized = connection?.authorization === 'full_access'
  const label = en ? {
    title: 'Apple Calendar', intro: 'Keep selected system calendars and Stella schedules in sync.',
    unsupported: 'Apple Calendar is not supported on this platform', missing: 'Apple Calendar helper is not installed',
    denied: 'System calendar access was denied', permissionHint: 'Enable Stella in System Settings → Privacy & Security → Calendars, then check again.',
    request: 'Request calendar access', recheck: 'Check again', connected: 'Connected', disconnected: 'Not connected',
    calendars: 'Calendars to sync', direction: 'Sync direction', import: 'Apple → Stella', export: 'Stella → Apple', both: 'Two-way sync',
    targetHint: 'New Stella events go to the first selected calendar that allows edits.',
    connect: 'Connect and sync', save: 'Save settings', sync: 'Sync now', last: 'Last successful sync', never: 'Never',
    disconnect: 'Disconnect', disconnectConfirm: 'Disconnect Apple Calendar? Synced schedules remain in Stella and Apple events are not deleted.',
    pending: 'Stella schedules were deleted. Apple events will remain until you confirm.', confirmDelete: 'Confirm Apple event deletion',
    deleteConfirm: 'Delete the pending linked events from Apple Calendar?', conflicts: 'Changes need your decision',
    pendingLocal: 'Apple events are missing. Stella schedules remain until you confirm.', confirmLocal: 'Confirm Stella schedule deletion',
    localDeleteConfirm: 'Delete the pending Stella schedules? Review your Apple calendar first.',
    keepStella: 'Keep Stella version', keepApple: 'Keep Apple version', close: 'Close',
    summary: (value: AppleCalendarSyncResult) => `Imported ${value.imported}, updated ${value.updated}, sent ${value.exported}.`,
  } : {
    title: 'Apple 日历', intro: '选择系统日历，与 Stella 日程保持同步。',
    unsupported: '此平台不支持 Apple 日历', missing: 'Apple 日历原生组件未安装',
    denied: '系统日历权限已拒绝', permissionHint: '请在「系统设置 → 隐私与安全性 → 日历」中允许 Stella，然后重新检查。',
    request: '请求日历权限', recheck: '重新检查', connected: '已连接', disconnected: '未连接',
    calendars: '要同步的日历', direction: '同步方向', import: '仅 Apple → Stella', export: '仅 Stella → Apple', both: '双向同步',
    targetHint: '新建的 Stella 日程将写入所选日历中第一个可编辑的日历。',
    connect: '连接并同步', save: '保存设置', sync: '立即同步', last: '上次成功同步', never: '尚未同步',
    disconnect: '断开连接', disconnectConfirm: '断开 Apple 日历连接？已同步的日程会保留在 Stella，Apple 日历事件不会被删除。',
    pending: 'Stella 中有已删除的日程。关联的 Apple 事件将在你确认后删除。', confirmDelete: '确认删除 Apple 事件',
    deleteConfirm: '确认从 Apple 日历删除待处理的关联事件？', conflicts: '以下变更需要你选择保留哪一版',
    pendingLocal: 'Apple 事件暂未找到。Stella 日程会保留，直到你核查并确认。', confirmLocal: '确认删除 Stella 日程',
    localDeleteConfirm: '确认删除待处理的 Stella 日程？请先核查 Apple 日历。',
    keepStella: '保留 Stella 版本', keepApple: '保留 Apple 版本', close: '关闭',
    summary: (value: AppleCalendarSyncResult) => `导入 ${value.imported} 条，更新 ${value.updated} 条，发送 ${value.exported} 条。`,
  }

  return <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section role="dialog" aria-modal="true" aria-label={label.title} className="w-full max-w-xl max-h-[88vh] overflow-y-auto rounded-card border border-default bg-surface shadow-xl text-content">
      <header className="px-5 py-4 border-b border-default flex items-start justify-between gap-4">
        <div className="flex gap-3 items-start"><span className="w-9 h-9 rounded-btn bg-surface-2 text-accent flex items-center justify-center"><CalendarDays size={19} /></span>
          <div><h2 className="font-semibold text-base">{label.title}</h2><p className="text-xs text-content-tertiary mt-1">{label.intro}</p></div></div>
        <button type="button" aria-label={label.close} onClick={onClose} className="p-1 text-content-tertiary hover:text-content"><X size={18} /></button>
      </header>
      <div className="px-5 py-5 space-y-5">
        {connection && <div className="flex items-center justify-between gap-3 text-sm">
          <span className={`inline-flex items-center gap-1.5 ${connection.connected ? 'text-accent' : 'text-content-secondary'}`}>
            {connection.connected && <Check size={15} />}{connection.connected ? label.connected : label.disconnected}</span>
          <button type="button" disabled={busy} onClick={() => void run(async () => ({ connection: await apiClient.getAppleCalendar() }))}
            className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-content disabled:opacity-50"><RefreshCw size={13} />{label.recheck}</button>
        </div>}
        {connection && !supported && <p role="status" className="rounded-btn bg-surface-2 px-3 py-3 text-sm text-content-secondary">
          {connection.authorization === 'helper_missing' ? label.missing : label.unsupported}</p>}
        {connection && supported && !authorized && <div className="space-y-3">
          <p role="status" className="text-sm text-content-secondary">{connection.authorization === 'denied' ? label.denied : label.permissionHint}</p>
          {connection.authorization === 'denied' && <p className="text-xs text-content-tertiary">{label.permissionHint}</p>}
          <button type="button" disabled={busy} onClick={() => void run(async () => ({ connection: await apiClient.requestAppleCalendarAccess() }))}
            className="px-3 py-2 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{label.request}</button>
        </div>}
        {connection && authorized && <>
          <fieldset className="space-y-2"><legend className="font-medium text-sm mb-2">{label.calendars}</legend>
            {connection.calendars.map(calendar => <label key={calendar.id} className="flex items-center gap-3 rounded-btn border border-default px-3 py-2.5 text-sm cursor-pointer hover:bg-surface-2">
              <input type="checkbox" checked={selected.includes(calendar.id)} onChange={() => toggle(calendar.id)} disabled={busy} />
              <span className="flex-1">{calendar.title}</span><span className="text-xs text-content-tertiary">{calendar.source}</span>
            </label>)}
          </fieldset>
          <label className="block text-sm font-medium">{label.direction}
            <select aria-label={label.direction} value={direction} disabled={busy} onChange={event => setDirection(event.target.value as AppleCalendarConnection['direction'])}
              className="mt-2 w-full rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm">
              <option value="import">{label.import}</option><option value="export">{label.export}</option><option value="bidirectional">{label.both}</option>
            </select>
          </label>
          {direction !== 'import' && <p className="text-xs text-content-tertiary">{label.targetHint}</p>}
          {connection.last_success && <p className="text-xs text-content-tertiary">{label.last}：{new Date(connection.last_success).toLocaleString(en ? 'en-US' : 'zh-CN')}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || selected.length === 0} onClick={() => void connect()}
              className="px-3 py-2 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{connection.connected ? label.save : label.connect}</button>
            {connection.connected && <button type="button" disabled={busy} onClick={() => void run(() => apiClient.syncAppleCalendar(), true)}
              className="px-3 py-2 rounded-btn border border-default text-sm hover:bg-surface-2 disabled:opacity-50">{label.sync}</button>}
          </div>
          {connection.connected && connection.pending_deletions > 0 && <div className="rounded-btn border border-default p-3 space-y-2 text-sm">
            <p>{label.pending} <strong>{connection.pending_deletions}</strong></p>
            <button type="button" disabled={busy} onClick={() => { if (window.confirm(label.deleteConfirm)) void run(() => apiClient.syncAppleCalendar(true), true) }}
              className="text-danger font-medium disabled:opacity-50">{label.confirmDelete}</button>
          </div>}
          {connection.connected && connection.pending_local_deletions > 0 && <div className="rounded-btn border border-default p-3 space-y-2 text-sm">
            <p>{label.pendingLocal} <strong>{connection.pending_local_deletions}</strong></p>
            <button type="button" disabled={busy} onClick={() => { if (window.confirm(label.localDeleteConfirm)) void run(() => apiClient.syncAppleCalendar(false, true), true) }}
              className="text-danger font-medium disabled:opacity-50">{label.confirmLocal}</button>
          </div>}
          {connection.conflicts.length > 0 && <section aria-label={label.conflicts} className="space-y-2">
            <h3 className="text-sm font-medium inline-flex items-center gap-1.5"><AlertCircle size={15} className="text-danger" />{label.conflicts}</h3>
            {connection.conflicts.map(conflict => <div key={conflict.stella_id} className="rounded-btn border border-default p-3 text-xs space-y-2">
              <p className="text-content-secondary">{conflict.reason}</p>
              <div className="flex gap-3"><button type="button" disabled={busy} onClick={() => void run(async () => ({ connection: await apiClient.resolveAppleCalendarConflict(conflict.stella_id, 'keep_stella') }), true)} className="text-accent">{label.keepStella}</button>
                <button type="button" disabled={busy} onClick={() => void run(async () => ({ connection: await apiClient.resolveAppleCalendarConflict(conflict.stella_id, 'keep_apple') }), true)} className="text-accent">{label.keepApple}</button></div>
            </div>)}
          </section>}
          {connection.connected && <button type="button" disabled={busy} onClick={() => { if (window.confirm(label.disconnectConfirm)) void run(async () => ({ connection: await apiClient.disconnectAppleCalendar() })) }}
            className="text-xs text-danger hover:underline disabled:opacity-50">{label.disconnect}</button>}
        </>}
        {result && <p role="status" className="text-xs text-accent">{label.summary(result)}</p>}
        {connection?.error && <p role="alert" className="text-xs text-danger">{connection.error}</p>}
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      </div>
    </section>
  </div>
}

export default AppleCalendarPanel
