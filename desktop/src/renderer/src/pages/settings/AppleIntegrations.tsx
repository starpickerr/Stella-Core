import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Apple, ArrowDownToLine, ArrowUpFromLine, RefreshCw } from 'lucide-react'
import apiClient from '../../api/client'
import type { AppleCalendarConnection, AppleCalendarSyncResult, AppleReminderConnection } from '../../types'

type Kind = 'calendar' | 'todos'
type Connection = AppleCalendarConnection | AppleReminderConnection
type Direction = Connection['direction']
type Preview = { new: number; updated: number; skipped: number; conflicts: number }
type TransferDirection = 'import' | 'export'
type Item = { id: string; title: string }

const readableError = (reason: unknown) => reason instanceof Error ? reason.message : String(reason)
const summarize = (preview: Preview) => `新增 ${preview.new} · 更新 ${preview.updated} · 跳过 ${preview.skipped} · 冲突 ${preview.conflicts}`

function AppleConnectionSection({ kind, focus }: { kind: Kind; focus: boolean }) {
  const calendar = kind === 'calendar'
  const title = calendar ? 'Apple 日历' : 'Apple 提醒事项'
  const sourceTitle = calendar ? '日历' : '列表'
  const sectionRef = useRef<HTMLElement>(null)
  const [connection, setConnection] = useState<Connection | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [direction, setDirection] = useState<Direction>('bidirectional')
  const [scopePreview, setScopePreview] = useState<{ preview: Preview; token: string } | null>(null)
  const [transferDirection, setTransferDirection] = useState<TransferDirection | null>(null)
  const [transferSource, setTransferSource] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [itemIds, setItemIds] = useState<string[]>([])
  const [itemPreview, setItemPreview] = useState<{ preview: Preview; token: string } | null>(null)
  const [start, setStart] = useState(() => `${new Date().getFullYear()}-01-01`)
  const [end, setEnd] = useState(() => `${new Date().getFullYear() + 1}-01-01`)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const apply = (state: Connection) => {
    setConnection(state)
    setSelected(calendar ? (state as AppleCalendarConnection).calendar_ids : (state as AppleReminderConnection).list_ids)
    setDirection(state.direction)
  }
  const refresh = async () => apply(calendar ? await apiClient.getAppleCalendar() : await apiClient.getAppleReminders())
  useEffect(() => {
    let active = true
    ;(calendar ? apiClient.getAppleCalendar() : apiClient.getAppleReminders())
      .then(state => { if (active) apply(state) })
      .catch(reason => { if (active) setError(readableError(reason)) })
    return () => { active = false }
  }, [calendar])
  useEffect(() => { if (focus) sectionRef.current?.scrollIntoView({ block: 'start' }) }, [focus])

  const sources = useMemo(() => connection
    ? calendar ? (connection as AppleCalendarConnection).calendars : (connection as AppleReminderConnection).lists
    : [], [connection, calendar])
  const authorized = connection?.authorization === 'full_access'
  const supported = connection?.supported && connection.authorization !== 'helper_missing' && connection.authorization !== 'unsupported'
  const request = async (action: () => Promise<{ connection: Connection; result?: AppleCalendarSyncResult }>) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await action()
      setConnection(response.connection)
      if (response.result) setNotice(`已完成：导入 ${response.result.imported}，更新 ${response.result.updated}，写入 ${response.result.exported}`)
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const mutate = async (action: () => Promise<Connection>) => request(async () => ({ connection: await action() }))
  const toggleAuto = async (enabled: boolean) => {
    const previous = connection?.auto_enabled ?? true
    setConnection(current => current ? { ...current, auto_enabled: enabled } : current)
    setBusy(true); setError('')
    try { setConnection(calendar ? await apiClient.setAppleCalendarAuto(enabled) : await apiClient.setAppleRemindersAuto(enabled)) }
    catch (reason) {
      setConnection(current => current ? { ...current, auto_enabled: previous } : current)
      setError(readableError(reason))
    } finally { setBusy(false) }
  }
  const chooseSource = (id: string) => {
    setSelected(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])
    setScopePreview(null)
  }
  const prepareScope = async () => {
    setBusy(true); setError(''); setScopePreview(null)
    try {
      const result = calendar ? await apiClient.previewAppleCalendarScope(selected, direction)
        : await apiClient.previewAppleRemindersScope(selected, direction)
      setScopePreview({ preview: result.preview, token: result.preview_token })
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const confirmScope = () => {
    if (!scopePreview) return
    const token = scopePreview.token
    setScopePreview(null)
    void request(() => calendar ? apiClient.configureAppleCalendar(selected, direction, token)
      : apiClient.configureAppleReminders(selected, direction, token))
  }
  const openTransfer = (next: TransferDirection) => {
    setTransferDirection(next); setTransferSource(''); setItems([]); setItemIds([]); setItemPreview(null)
  }
  const loadItems = async () => {
    if (!transferSource || !transferDirection) return
    setBusy(true); setError(''); setItems([]); setItemIds([]); setItemPreview(null)
    try {
      if (transferDirection === 'import') {
        if (calendar) {
          const rows = await apiClient.getAppleCalendarItems(transferSource,
            new Date(`${start}T00:00:00`).toISOString(), new Date(`${end}T00:00:00`).toISOString())
          setItems(rows.map(row => ({ id: row.event_id, title: row.title })))
        } else {
          const rows = await apiClient.getAppleRemindersItems(transferSource)
          setItems(rows.map(row => ({ id: row.reminder_id, title: row.title })))
        }
      } else if (calendar) {
        const rows = await apiClient.getCalendarEvents(new Date(`${start}T00:00:00`).toISOString(),
          new Date(`${end}T00:00:00`).toISOString())
        setItems(rows.filter(row => !row.source_type).map(row => ({ id: row.id, title: row.title })))
      } else {
        const rows = await apiClient.getTodos()
        setItems(rows.filter(row => !row.source_type).map(row => ({ id: row.id, title: row.title })))
      }
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const prepareItems = async () => {
    if (!transferDirection || !transferSource || itemIds.length === 0) return
    setBusy(true); setError(''); setItemPreview(null)
    try {
      const result = calendar
        ? await apiClient.previewAppleCalendarItems(transferDirection, transferSource, itemIds)
        : await apiClient.previewAppleRemindersItems(transferDirection, transferSource, itemIds)
      setItemPreview({ preview: result.preview, token: result.preview_token })
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const confirmItems = () => {
    if (!itemPreview || !transferDirection) return
    const token = itemPreview.token
    setItemPreview(null)
    void request(() => calendar
      ? apiClient.transferAppleCalendarItems(transferDirection, transferSource, itemIds, token)
      : apiClient.transferAppleRemindersItems(transferDirection, transferSource, itemIds, token))
  }
  const resolve = (id: string, choice: 'keep_stella' | 'keep_apple') => void mutate(() => calendar
    ? apiClient.resolveAppleCalendarConflict(id, choice) : apiClient.resolveAppleRemindersConflict(id, choice))
  const sync = (remote = false, local = false) => void request(() => calendar
    ? apiClient.syncAppleCalendar(remote, local) : apiClient.syncAppleReminders(remote, local))
  const conflictRows = connection?.conflicts ?? []

  return <section ref={sectionRef} role="region" aria-label={title} className="rounded-card border border-default bg-surface p-5 space-y-5 scroll-mt-6">
    <header className="flex items-start justify-between gap-4">
      <div><h3 className="text-base font-semibold text-content">{title}</h3>
        <p className="text-xs text-content-tertiary mt-1">{calendar ? '选择系统日历，与 Stella 日程连接。' : '选择系统列表，与 Stella 事务连接。'}</p></div>
      <button type="button" disabled={busy} onClick={() => void refresh().catch(reason => setError(readableError(reason)))}
        className="text-xs text-content-secondary inline-flex items-center gap-1 hover:text-content disabled:opacity-50"><RefreshCw size={13} />重新检查</button>
    </header>
    {!connection && !error && <p role="status" className="text-sm text-content-secondary">正在读取连接状态…</p>}
    {connection && <p className="text-xs text-content-secondary">{connection.connected ? '已连接' : '未连接'} · 权限：{connection.authorization === 'full_access' ? '已授权' : connection.authorization}</p>}
    {connection && !supported && <p role="status" className="text-sm text-content-secondary">此设备暂不支持 {title}，或原生组件尚未安装。</p>}
    {connection && supported && !authorized && <div className="space-y-2">
      <p role="status" className="text-sm text-content-secondary">请在系统设置中允许 Stella 访问{sourceTitle}，然后重新检查。</p>
      <button type="button" disabled={busy} onClick={() => void mutate(() => calendar ? apiClient.requestAppleCalendarAccess() : apiClient.requestAppleRemindersAccess())}
        className="rounded-btn bg-accent px-3 py-2 text-sm text-accent-contrast disabled:opacity-50">请求访问权限</button>
    </div>}
    {connection && supported && authorized && <>
      <fieldset className="space-y-2"><legend className="text-sm font-medium text-content mb-2">持续同步的{sourceTitle}</legend>
        {sources.length === 0 && <p className="text-xs text-content-tertiary">未找到可用{sourceTitle}。</p>}
        {sources.map(source => <label key={source.id} className="flex items-center gap-3 rounded-btn border border-default px-3 py-2 text-sm text-content cursor-pointer hover:bg-surface-2">
          <input type="checkbox" checked={selected.includes(source.id)} onChange={() => chooseSource(source.id)} disabled={busy} />
          <span className="flex-1">{source.title}</span><span className="text-xs text-content-tertiary">{source.source}{source.writable ? '' : ' · 只读'}</span>
        </label>)}
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm text-content">同步方向
          <select aria-label={`${title}同步方向`} value={direction} disabled={busy} onChange={event => { setDirection(event.target.value as Direction); setScopePreview(null) }}
            className="mt-1 block w-full rounded-btn border border-default bg-surface-2 px-3 py-2">
            <option value="import">仅 Apple → Stella</option><option value="export">仅 Stella → Apple</option><option value="bidirectional">双向同步</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-content self-end pb-2">
          <input type="checkbox" aria-label="自动同步" checked={connection.auto_enabled} disabled={busy}
            onChange={event => void toggleAuto(event.target.checked)} />自动同步
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy || selected.length === 0} onClick={() => void prepareScope()}
          className="rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50">预览同步</button>
        {connection.connected && <button type="button" disabled={busy} onClick={() => sync()}
          className="rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50">立即同步</button>}
      </div>
      {scopePreview && <div className="rounded-btn border border-accent/40 bg-surface-2 p-3 space-y-2 text-sm text-content">
        <p>同步预览：{summarize(scopePreview.preview)}</p>
        <button type="button" disabled={busy} onClick={confirmScope} className="rounded-btn bg-accent px-3 py-2 text-accent-contrast disabled:opacity-50">确认连接并同步</button>
      </div>}
      <div className="border-t border-default pt-4 space-y-3">
        <div><h4 className="font-medium text-sm text-content">一次性传输</h4><p className="text-xs text-content-tertiary mt-1">只处理你选择的条目，不开启持续同步。</p></div>
        <div className="flex gap-2">
          <button type="button" disabled={busy} onClick={() => openTransfer('import')} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50"><ArrowDownToLine size={14} />一次性导入</button>
          <button type="button" disabled={busy} onClick={() => openTransfer('export')} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50"><ArrowUpFromLine size={14} />一次性写入</button>
        </div>
        {transferDirection && <div className="space-y-3 rounded-btn bg-surface-2 p-3">
          <label className="block text-sm text-content">目标{sourceTitle}
            <select aria-label={`一次性${sourceTitle}`} value={transferSource} disabled={busy} onChange={event => { setTransferSource(event.target.value); setItems([]); setItemIds([]); setItemPreview(null) }}
              className="mt-1 block w-full rounded-btn border border-default bg-surface px-3 py-2">
              <option value="">请选择</option>{sources.filter(source => transferDirection === 'import' || source.writable).map(source => <option key={source.id} value={source.id}>{source.title}</option>)}
            </select>
          </label>
          {calendar && <div className="flex flex-wrap gap-2 text-sm text-content">
            <label>开始日期 <input aria-label="开始日期" type="date" value={start} disabled={busy} onChange={event => { setStart(event.target.value); setItems([]); setItemIds([]); setItemPreview(null) }} className="rounded-btn border border-default bg-surface p-1 disabled:opacity-50" /></label>
            <label>结束日期 <input aria-label="结束日期" type="date" value={end} disabled={busy} onChange={event => { setEnd(event.target.value); setItems([]); setItemIds([]); setItemPreview(null) }} className="rounded-btn border border-default bg-surface p-1 disabled:opacity-50" /></label>
          </div>}
          <button type="button" disabled={busy || !transferSource || (calendar && (!start || !end || start >= end))} onClick={() => void loadItems()}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content disabled:opacity-50">载入条目</button>
          {items.length === 0 && <p className="text-xs text-content-tertiary">暂无已载入条目。</p>}
          {items.length > 0 && <fieldset className="space-y-1"><legend className="text-xs text-content-secondary">选择具体条目</legend>{items.map(item => <label key={item.id} className="flex items-center gap-2 text-sm text-content py-1">
            <input type="checkbox" checked={itemIds.includes(item.id)} disabled={busy} onChange={() => { setItemIds(current => current.includes(item.id) ? current.filter(id => id !== item.id) : [...current, item.id]); setItemPreview(null) }} />{item.title}
          </label>)}</fieldset>}
          {items.length > 0 && <button type="button" disabled={busy || itemIds.length === 0} onClick={() => void prepareItems()}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content disabled:opacity-50">{transferDirection === 'import' ? '预览导入' : '预览写入'}</button>}
          {itemPreview && <div className="space-y-2 text-sm text-content"><p>条目预览：{summarize(itemPreview.preview)}</p>
            <button type="button" disabled={busy} onClick={confirmItems} className="rounded-btn bg-accent px-3 py-2 text-accent-contrast disabled:opacity-50">{transferDirection === 'import' ? '确认一次性导入' : '确认一次性写入'}</button>
          </div>}
        </div>}
      </div>
      {connection.last_success && <p className="text-xs text-content-secondary">上次成功同步：{new Date(connection.last_success).toLocaleString('zh-CN')}</p>}
      {(connection.pending_deletions > 0 || connection.pending_local_deletions > 0) && <div className="space-y-2 text-xs text-content-secondary">
        {connection.pending_deletions > 0 && <p>Apple 端待确认删除 {connection.pending_deletions} 条。<button type="button" className="ml-2 text-danger" onClick={() => { if (window.confirm('确认删除 Apple 中的关联条目？')) sync(true) }}>确认删除 Apple 条目</button></p>}
        {connection.pending_local_deletions > 0 && <p>Stella 端待确认删除 {connection.pending_local_deletions} 条。<button type="button" className="ml-2 text-danger" onClick={() => { if (window.confirm('确认删除 Stella 中的关联条目？')) sync(false, true) }}>确认删除 Stella 条目</button></p>}
      </div>}
      {conflictRows.length > 0 && <div className="space-y-2 text-sm text-content"><h4 className="font-medium">待处理冲突</h4>
        {conflictRows.map(row => {
          const id = 'stella_id' in row ? row.stella_id : row.todo_id
          return <div key={id} className="rounded-btn border border-default p-3"><p>{row.reason}</p>
            <div className="flex gap-3 mt-2"><button type="button" disabled={busy} onClick={() => resolve(id, 'keep_stella')} className="text-accent">保留 Stella</button>
              <button type="button" disabled={busy} onClick={() => resolve(id, 'keep_apple')} className="text-accent">保留 Apple</button></div>
          </div>
        })}
      </div>}
      {connection.connected && <button type="button" disabled={busy} onClick={() => { if (window.confirm(`断开${title}连接？已同步的条目会保留。`)) void mutate(() => calendar ? apiClient.disconnectAppleCalendar() : apiClient.disconnectAppleReminders()) }}
        className="text-xs text-danger disabled:opacity-50">断开连接</button>}
    </>}
    {notice && <p role="status" className="text-sm text-accent">{notice}</p>}
    {(error || connection?.error) && <p role="alert" className="text-sm text-danger">{error || connection?.error}</p>}
  </section>
}

export default function AppleIntegrations({ section }: { section: string | null }) {
  return <div className="space-y-5">
    <div className="flex items-center gap-2 text-content"><Apple size={19} className="text-accent" /><h2 className="font-semibold">Apple 互联</h2></div>
    <p className="text-sm text-content-secondary">日历与提醒事项分别授权和配置。每次连接或传输前先查看预览。</p>
    <AppleConnectionSection kind="calendar" focus={section === 'apple-calendar'} />
    <AppleConnectionSection kind="todos" focus={section === 'apple-reminders'} />
  </div>
}
