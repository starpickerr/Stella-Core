import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Apple, ArrowDownToLine, ArrowUpFromLine, RefreshCw } from 'lucide-react'
import apiClient from '../../api/client'
import type { AppleCalendarConnection, AppleCalendarSyncResult, AppleReminderConnection, CalendarCategory } from '../../types'

type Kind = 'calendar' | 'todos'
type Connection = AppleCalendarConnection | AppleReminderConnection
type ContentDirection = 'import' | 'export' | 'bidirectional'
type TransferDirection = 'import' | 'export'
type DraftLink = { apple_id: string; stella_id: string; direction: ContentDirection; enabled: boolean }

const readableError = (reason: unknown) => reason instanceof Error ? reason.message : String(reason)
const CREATE = '__create__'

function AppleConnectionSection({ kind, focus }: { kind: Kind; focus: boolean }) {
  const calendar = kind === 'calendar'
  const title = calendar ? 'Apple 日历' : 'Apple 提醒事项'
  const sourceTitle = calendar ? '日历' : '列表'
  const sectionRef = useRef<HTMLElement>(null)
  const [connection, setConnection] = useState<Connection | null>(null)
  const [categories, setCategories] = useState<CalendarCategory[]>([])
  const [links, setLinks] = useState<DraftLink[]>([])
  const [linkPreview, setLinkPreview] = useState<{ token: string } | null>(null)
  const [transferDirection, setTransferDirection] = useState<TransferDirection | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [start, setStart] = useState(() => `${new Date().getFullYear()}-01-01`)
  const [end, setEnd] = useState(() => `${new Date().getFullYear() + 1}-01-01`)
  const [includeUndated, setIncludeUndated] = useState(false)
  const [includeCompleted, setIncludeCompleted] = useState(false)
  const [batchPreview, setBatchPreview] = useState<{ new: number; skipped: number; failed: number; token: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const apply = (state: Connection, rows = categories) => {
    setConnection(state)
    setLinks((state.links ?? []).map(link => ({
      apple_id: link.apple_id,
      stella_id: rows.some(row => row.id === link.stella_id) ? link.stella_id : link.stella_id,
      direction: link.direction,
      enabled: link.enabled,
    })))
  }
  const loadCategories = async () => calendar ? apiClient.getCalendarCategories() : apiClient.getTodoCategories()
  const refresh = async () => {
    const [state, rows] = await Promise.all([
      calendar ? apiClient.getAppleCalendar() : apiClient.getAppleReminders(),
      loadCategories(),
    ])
    setCategories(rows)
    apply(state, rows)
  }
  useEffect(() => {
    let active = true
    Promise.all([
      calendar ? apiClient.getAppleCalendar() : apiClient.getAppleReminders(),
      loadCategories(),
    ]).then(([state, rows]) => {
      if (!active) return
      setCategories(rows)
      apply(state, rows)
    }).catch(reason => { if (active) setError(readableError(reason)) })
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
      apply(response.connection as Connection)
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
  const payloadLinks = () => links.filter(link => link.apple_id).map(link => {
    const apple = sources.find(source => source.id === link.apple_id)
    if (link.stella_id === CREATE) return { apple_id: link.apple_id, create_name: apple?.title || '新分类', direction: link.direction, enabled: link.enabled }
    return { apple_id: link.apple_id, stella_id: link.stella_id, direction: link.direction, enabled: link.enabled }
  })
  const updateLink = (index: number, patch: Partial<DraftLink>) => {
    setLinks(current => current.map((link, position) => position === index ? { ...link, ...patch } : link))
    setLinkPreview(null)
  }
  const prepareLinks = async () => {
    setBusy(true); setError(''); setLinkPreview(null)
    try {
      const result = await apiClient.previewAppleCategoryLinks(kind, payloadLinks())
      setLinkPreview({ token: result.preview_token })
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const confirmLinks = () => {
    if (!linkPreview) return
    const token = linkPreview.token
    setLinkPreview(null)
    void request(async () => {
      const response = await apiClient.saveAppleCategoryLinks(kind, payloadLinks(), token)
      const rows = await loadCategories()
      setCategories(rows)
      return response as { connection: Connection; result: AppleCalendarSyncResult }
    })
  }
  const openTransfer = (next: TransferDirection) => {
    setTransferDirection(next); setSourceId(''); setTargetId(''); setBatchPreview(null)
  }
  const selection = () => {
    if (transferDirection === 'import') return [{ apple_id: sourceId, stella_id: targetId }]
    return [{ apple_id: targetId, stella_id: sourceId }]
  }
  const prepareBatch = async () => {
    if (!transferDirection || !sourceId || !targetId) return
    setBusy(true); setError(''); setBatchPreview(null)
    try {
      const result = await apiClient.previewAppleCategoryBatch(kind, {
        direction: transferDirection, selections: selection(), start, end,
        include_undated: includeUndated, include_completed: includeCompleted,
      })
      setBatchPreview({ ...result.preview, token: result.preview_token })
    } catch (reason) { setError(readableError(reason)) }
    finally { setBusy(false) }
  }
  const confirmBatch = () => {
    if (!batchPreview || !transferDirection) return
    const token = batchPreview.token
    setBatchPreview(null)
    void request(() => apiClient.transferAppleCategoryBatch(kind, {
      direction: transferDirection, selections: selection(), start, end, preview_token: token,
      include_undated: includeUndated, include_completed: includeCompleted,
    }) as Promise<{ connection: Connection; result: AppleCalendarSyncResult }>)
  }
  const resolve = (id: string, choice: 'keep_stella' | 'keep_apple') => void mutate(() => calendar
    ? apiClient.resolveAppleCalendarConflict(id, choice) : apiClient.resolveAppleRemindersConflict(id, choice))
  const sync = (remote = false, local = false) => void request(() => calendar
    ? apiClient.syncAppleCalendar(remote, local) : apiClient.syncAppleReminders(remote, local))
  const conflictRows = connection?.conflicts ?? []
  const nameConflicts = (connection?.links ?? []).filter(link => link.name_conflict)
  const sourceChoices = transferDirection === 'export'
    ? categories.map(row => ({ id: row.id, title: row.name }))
    : sources.map(row => ({ id: row.id, title: row.title }))
  const targetChoices = transferDirection === 'export'
    ? sources.filter(row => row.writable).map(row => ({ id: row.id, title: row.title }))
    : categories.map(row => ({ id: row.id, title: row.name }))

  return <section ref={sectionRef} role="region" aria-label={title} className="rounded-card border border-default bg-surface p-5 space-y-5 scroll-mt-6">
    <header className="flex items-start justify-between gap-4">
      <div><h3 className="text-base font-semibold text-content">{title}</h3>
        <p className="text-xs text-content-tertiary mt-1">按稳定分类一一对应。分类名称双向同步，内容方向在每一行单独设置。</p></div>
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
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-medium text-content">持续同步</h4>
          <label className="flex items-center gap-2 text-sm text-content">
            <input type="checkbox" aria-label="自动同步" checked={connection.auto_enabled} disabled={busy}
              onChange={event => void toggleAuto(event.target.checked)} />自动同步
          </label>
        </div>
        {links.length === 0 && <p className="text-xs text-content-tertiary">还没有分类映射。未映射的{sourceTitle}不参与持续同步。</p>}
        {links.map((link, index) => <div key={`${link.apple_id}-${index}`} className="grid gap-2 rounded-btn border border-default p-3 md:grid-cols-4">
          <label className="text-sm text-content">Apple {sourceTitle}
            <select aria-label={`Apple ${sourceTitle} ${index + 1}`} value={link.apple_id} disabled={busy} onChange={event => updateLink(index, { apple_id: event.target.value })}
              className="mt-1 block w-full rounded-btn border border-default bg-surface-2 px-3 py-2">
              <option value="">请选择</option>
              {sources.map(source => <option key={source.id} value={source.id}>{source.title}{source.writable ? '' : ' · 只读'}</option>)}
            </select>
          </label>
          <label className="text-sm text-content">Stella 分类
            <select aria-label={`Stella 分类 ${index + 1}`} value={link.stella_id} disabled={busy} onChange={event => updateLink(index, { stella_id: event.target.value })}
              className="mt-1 block w-full rounded-btn border border-default bg-surface-2 px-3 py-2">
              <option value="">请选择</option>
              <option value={CREATE}>新建同名分类</option>
              {categories.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <label className="text-sm text-content">内容方向
            <select aria-label={`内容方向 ${index + 1}`} value={link.direction} disabled={busy} onChange={event => updateLink(index, { direction: event.target.value as ContentDirection })}
              className="mt-1 block w-full rounded-btn border border-default bg-surface-2 px-3 py-2">
              <option value="import">Apple → Stella</option>
              <option value="export">Stella → Apple</option>
              <option value="bidirectional">双向</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-content md:mt-6">
            <input type="checkbox" aria-label={`已启用 ${index + 1}`} checked={link.enabled} disabled={busy} onChange={event => updateLink(index, { enabled: event.target.checked })} />
            {link.enabled ? '已启用' : '已暂停'}
          </label>
        </div>)}
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => { setLinks(current => [...current, { apple_id: '', stella_id: '', direction: 'bidirectional', enabled: true }]); setLinkPreview(null) }}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50">添加映射</button>
          <button type="button" disabled={busy || links.length === 0} onClick={() => void prepareLinks()}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50">预览同步</button>
          {connection.connected && <button type="button" disabled={busy} onClick={() => sync()}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50">立即同步</button>}
        </div>
        {linkPreview && <div className="rounded-btn border border-accent/40 bg-surface-2 p-3 space-y-2 text-sm text-content">
          <p>将保存 {payloadLinks().length} 条分类映射。分类名称会双向同步，没有单独的名称方向。</p>
          <button type="button" disabled={busy} onClick={confirmLinks} className="rounded-btn bg-accent px-3 py-2 text-accent-contrast disabled:opacity-50">确认连接并同步</button>
        </div>}
      </div>
      <div className="border-t border-default pt-4 space-y-3">
        <div><h4 className="font-medium text-sm text-content">一次性传输</h4><p className="text-xs text-content-tertiary mt-1">按类别和时间范围传输，不开启持续同步。</p></div>
        <div className="flex gap-2">
          <button type="button" disabled={busy} onClick={() => openTransfer('import')} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50"><ArrowDownToLine size={14} />一次性导入</button>
          <button type="button" disabled={busy} onClick={() => openTransfer('export')} className="inline-flex items-center gap-1 rounded-btn border border-default px-3 py-2 text-sm text-content hover:bg-surface-2 disabled:opacity-50"><ArrowUpFromLine size={14} />一次性写入</button>
        </div>
        {transferDirection && <div className="space-y-3 rounded-btn bg-surface-2 p-3">
          <label className="block text-sm text-content">来源分类
            <select aria-label="来源分类" value={sourceId} disabled={busy} onChange={event => { setSourceId(event.target.value); setBatchPreview(null) }}
              className="mt-1 block w-full rounded-btn border border-default bg-surface px-3 py-2">
              <option value="">请选择</option>{sourceChoices.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
            </select>
          </label>
          <label className="block text-sm text-content">目标分类
            <select aria-label="目标分类" value={targetId} disabled={busy} onChange={event => { setTargetId(event.target.value); setBatchPreview(null) }}
              className="mt-1 block w-full rounded-btn border border-default bg-surface px-3 py-2">
              <option value="">请选择</option>{targetChoices.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap gap-2 text-sm text-content">
            <label>开始日期 <input aria-label="开始日期" type="date" value={start} disabled={busy} onChange={event => { setStart(event.target.value); setBatchPreview(null) }} className="rounded-btn border border-default bg-surface p-1 disabled:opacity-50" /></label>
            <label>结束日期 <input aria-label="结束日期" type="date" value={end} disabled={busy} onChange={event => { setEnd(event.target.value); setBatchPreview(null) }} className="rounded-btn border border-default bg-surface p-1 disabled:opacity-50" /></label>
          </div>
          {!calendar && <div className="flex flex-wrap gap-4 text-sm text-content">
            <label className="flex items-center gap-2"><input type="checkbox" aria-label="包含无日期事务" checked={includeUndated} disabled={busy} onChange={event => { setIncludeUndated(event.target.checked); setBatchPreview(null) }} />包含无日期事务</label>
            <label className="flex items-center gap-2"><input type="checkbox" aria-label="包含已完成事务" checked={includeCompleted} disabled={busy} onChange={event => { setIncludeCompleted(event.target.checked); setBatchPreview(null) }} />包含已完成事务</label>
          </div>}
          <button type="button" disabled={busy || !sourceId || !targetId || !start || !end || start > end} onClick={() => void prepareBatch()}
            className="rounded-btn border border-default px-3 py-2 text-sm text-content disabled:opacity-50">{transferDirection === 'import' ? '预计导入' : '预计写入'}</button>
          {batchPreview && <div className="space-y-2 text-sm text-content">
            <p>{transferDirection === 'import' ? '预计导入' : '预计写入'} {batchPreview.new} 条，跳过 {batchPreview.skipped} 条，失败 {batchPreview.failed} 条。</p>
            <button type="button" disabled={busy} onClick={confirmBatch} className="rounded-btn bg-accent px-3 py-2 text-accent-contrast disabled:opacity-50">{transferDirection === 'import' ? '开始导入' : '开始写入'}</button>
          </div>}
        </div>}
      </div>
      {connection.last_success && <p className="text-xs text-content-secondary">上次成功同步：{new Date(connection.last_success).toLocaleString('zh-CN')}</p>}
      {(connection.pending_deletions > 0 || connection.pending_local_deletions > 0) && <div className="space-y-2 text-xs text-content-secondary">
        {connection.pending_deletions > 0 && <p>Apple 端待确认删除 {connection.pending_deletions} 条。<button type="button" className="ml-2 text-danger" onClick={() => { if (window.confirm('确认删除 Apple 中的关联条目？')) sync(true) }}>确认删除 Apple 条目</button></p>}
        {connection.pending_local_deletions > 0 && <p>Stella 端待确认删除 {connection.pending_local_deletions} 条。<button type="button" className="ml-2 text-danger" onClick={() => { if (window.confirm('确认删除 Stella 中的关联条目？')) sync(false, true) }}>确认删除 Stella 条目</button></p>}
      </div>}
      {nameConflicts.map(link => <p key={link.apple_id} role="alert" className="text-sm text-danger">{link.apple_name}：{link.name_conflict}</p>)}
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
    <p className="flex items-center gap-2 px-1 text-xs text-content-tertiary"><Apple size={14} />日历与提醒事项分别授权和配置。每次连接或传输前先查看数量。</p>
    <AppleConnectionSection kind="calendar" focus={section === 'apple-calendar'} />
    <AppleConnectionSection kind="todos" focus={section === 'apple-reminders'} />
  </div>
}
