import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import apiClient from '../api/client'
import type { DataCommandResult, DataRecord, DataResource, DataSnapshot, DataSourceInfo } from '../api/dataTypes'
import { getLang, t } from '../i18n'
import PageHeader from '../components/PageHeader'
import { Toggle } from './settings/primitives'

const c = (zh: string, en: string) => getLang() === 'zh' ? zh : en
const button = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-default px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed'
const input = 'rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content min-w-0'
const tabs = ['overview', 'sources', 'records', 'sync', 'storage'] as const
type Tab = typeof tabs[number]
const labels = () => [c('总览', 'Overview'), c('信息源', 'Sources'), c('数据记录', 'Records'), c('同步与分发', 'Sync and delivery'), c('存储管理', 'Storage')]
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error)
const safeSettings = (source: DataSourceInfo) => ['/email', '/elearning'].includes(source.settings_url || '') ? source.settings_url : undefined
const supports = (source: DataSourceInfo | undefined, operation: string) => !!source && (!source.operations || source.operations.includes(operation))
const bytes = (value: number) => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`

export default function DataManagementPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const requested = new URLSearchParams(location.search).get('section') as Tab | null
  const tab: Tab = requested && tabs.includes(requested) ? requested : 'overview'
  const [state, setState] = useState<DataSnapshot | null>(null)
  const [busy, setBusy] = useState(true)
  const pending = useRef(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [records, setRecords] = useState<DataRecord[]>([])
  const [resources, setResources] = useState<DataResource[]>([])
  const [resourceContent, setResourceContent] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState('')
  const [recordLoading, setRecordLoading] = useState(false)
  const [consumer, setConsumer] = useState('briefing')
  const [filter, setFilter] = useState('')
  const mounted = useRef(true)
  const recordRequest = useRef<AbortController | null>(null)
  const source = state?.sources.find(item => item.id === sourceId) || state?.sources[0]
  const selectedId = source?.id || ''
  const referenceSource = source?.representation === 'reference'

  const snapshot = useCallback(async (refresh = false, signal?: AbortSignal) => {
    const result = await apiClient.getDataSnapshot(refresh, signal)
    if (!signal?.aborted && mounted.current) setState(result)
    return result
  }, [])

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    snapshot(false, controller.signal).catch(reason => { if (!controller.signal.aborted) setError(messageOf(reason)) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => { mounted.current = false; controller.abort(); recordRequest.current?.abort() }
  }, [snapshot])

  const loadRecords = useCallback(async () => {
    recordRequest.current?.abort()
    const controller = new AbortController()
    recordRequest.current = controller
    setRecords([]); setResources([]); setResourceContent(null); setExpanded(''); setRecordLoading(true)
    try {
      if (referenceSource) {
        const result = await apiClient.getDataResources(selectedId, query, offset, controller.signal)
        if (!controller.signal.aborted && mounted.current) { setResources(result.resources); setTotal(result.total) }
      } else {
        const result = await apiClient.getDataRecords(selectedId, query, offset, controller.signal)
        if (!controller.signal.aborted && mounted.current) { setRecords(result.records); setTotal(result.total) }
      }
    } catch (reason) {
      if (!controller.signal.aborted && mounted.current) { setError(messageOf(reason)); setTotal(0) }
    } finally { if (!controller.signal.aborted && mounted.current) setRecordLoading(false) }
  }, [selectedId, referenceSource, query, offset])

  useEffect(() => {
    if (tab === 'records' && source?.enabled && source.available) void loadRecords()
    else { recordRequest.current?.abort(); setRecords([]); setResources([]); setExpanded(''); setResourceContent(null); setRecordLoading(false); setTotal(0) }
    return () => recordRequest.current?.abort()
  }, [tab, source?.enabled, source?.available, loadRecords])

  const refresh = async () => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(''); setMessage('')
    try { await snapshot(true); if (tab === 'records' && source?.enabled && source.available) await loadRecords() }
    catch (reason) { if (mounted.current) { setError(messageOf(reason)); setRecords([]); setResources([]); setResourceContent(null) } }
    finally { pending.current = false; if (mounted.current) setBusy(false) }
  }

  const run = async (body: Record<string, unknown>, success: string, after?: (result: DataCommandResult) => void) => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(''); setMessage('')
    try {
      const result = await apiClient.dataCommand(body)
      if (!mounted.current) return
      after?.(result)
      await snapshot()
      if (tab === 'records' && source?.enabled && source.available) await loadRecords()
      if (result.sync?.errors.length) setError(result.sync.errors.join('\n'))
      setMessage(success)
    } catch (reason) { if (mounted.current) setError(messageOf(reason)) }
    finally { pending.current = false; if (mounted.current) setBusy(false) }
  }

  const readResource = async (row: DataResource) => {
    recordRequest.current?.abort()
    const controller = new AbortController()
    recordRequest.current = controller
    setExpanded(row.id); setResourceContent(null); setError('')
    try {
      const result = await apiClient.readDataResource(selectedId, row.id, controller.signal)
      if (!controller.signal.aborted && mounted.current) setResourceContent(typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2))
    } catch (reason) {
      if (!controller.signal.aborted && mounted.current) { setError(messageOf(reason)); setExpanded('') }
    }
  }

  const choose = (next: Tab) => navigate(`/data?section=${next}`, { replace: true, state: location.state })
  const sourceSelect = <label className="flex items-center gap-2 text-sm">{c('信息源', 'Source')}
    <select aria-label={c('选择信息源', 'Select source')} className={`${input} flex-1`} value={selectedId} disabled={busy || !state?.sources.length}
      onChange={event => { setSourceId(event.target.value); setOffset(0); setError('') }}>
      {state?.sources.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>

  const exportData = () => {
    if (!source) return
    void run({ action: 'export', source_id: source.id }, c('已导出', 'Exported'), result => {
      if (!result.export) throw new Error(c('导出结果为空', 'Missing export result'))
      const href = URL.createObjectURL(new Blob([JSON.stringify(result.export, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a'); link.href = href; link.download = `stella-${source.kind.replace(/[^A-Za-z0-9_-]/g, '_')}-${Date.now()}.json`; link.click()
      setTimeout(() => URL.revokeObjectURL(href), 1000)
    })
  }

  return <div className="flex-1 flex flex-col min-h-0">
    <PageHeader><h2 className="text-xl font-bold text-content">{t('menu_data')}</h2></PageHeader>
    <main data-stella-scroll className="flex-1 min-w-0 overflow-y-auto">
    <div className="max-w-4xl mx-auto px-6 py-6 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <nav aria-label={c('数据分类', 'Data sections')} className="flex flex-wrap gap-1">
        {tabs.map((key, index) => <button key={key} type="button" disabled={busy} aria-current={tab === key ? 'page' : undefined}
          className={`${button} ${tab === key ? 'bg-accent-soft text-accent border-accent' : 'text-content-secondary'}`} onClick={() => choose(key)}>{labels()[index]}</button>)}
      </nav>
      <button type="button" className={button} disabled={busy} onClick={() => void refresh()}><RefreshCw size={15} className={busy ? 'animate-spin' : ''} />{c('刷新', 'Refresh')}</button>
    </div>
    {(error || !!state?.errors.length) && <div role="alert" className="rounded-btn border border-danger/30 p-3 text-sm text-danger whitespace-pre-wrap break-words">{error || state?.errors.map(item => `${item.provider}: ${item.message}`).join('\n')}</div>}
    <p role="status" className="text-sm text-content-secondary" aria-live="polite">{message || (busy ? c('处理中…', 'Working…') : '')}</p>
    {!state ? <p className="text-sm text-content-secondary">{c('正在加载数据服务', 'Loading Data Service')}</p> : <>
      {tab === 'overview' && <div className="space-y-4">
        <dl className="grid grid-cols-3 gap-3 rounded-card border border-default bg-surface p-4">
          {[[c('信息源', 'Sources'), state.sources.length], [c('数据记录', 'Records'), state.record_count], [c('待投递', 'Pending'), state.deliveries.filter(item => item.state !== 'delivered').length]].map(([name, value]) => <div key={String(name)}><dt className="text-sm text-content-secondary">{name}</dt><dd className="mt-1 text-xl font-semibold">{value}</dd></div>)}
        </dl>
        <div className="flex flex-wrap gap-4 text-sm text-accent"><Link to="/email">{c('添加邮箱', 'Add mailbox')}</Link><Link to="/skills?tab=mcp">{c('管理 MCP', 'Manage MCP')}</Link><Link to="/security?tab=privacy">{c('数据访问', 'Data access')}</Link></div>
        {state.sources.map(item => <div key={item.id} className="flex flex-wrap justify-between gap-2 border-b border-default py-2 text-sm"><span>{item.name}</span><span className="text-content-secondary">{item.representation === 'reference' ? c('按需读取引用', 'Read references on demand') : item.running ? c('同步中', 'Syncing') : item.error ? c('同步异常', 'Sync failed') : item.last_run ? new Date(item.last_run * 1000).toLocaleString() : c('尚未同步', 'Not synced')}</span></div>)}
      </div>}
      {tab === 'sources' && <div className="space-y-3">
        <Link className="inline-block text-sm text-accent" to="/email">{c('添加邮箱', 'Add mailbox')}</Link>
        {!state.sources.length && <p className="text-sm text-content-secondary">{c('尚无已配置的信息源', 'No configured sources')}</p>}
        {state.sources.map(item => <section key={item.id} data-testid={`data-source-${item.id}`} className="rounded-card border border-default bg-surface p-4 space-y-3">
          <div className="flex items-center justify-between gap-3"><h4 className="font-medium break-words">{item.name}</h4><Toggle label={item.name} checked={item.enabled} disabled={busy} onChange={enabled => void run({ action: 'source', source_id: item.id, enabled }, c('已保存', 'Saved'))} /></div>
          <p className="text-xs text-content-secondary break-all">{item.provider} · {item.available ? c('连接已启用', 'Connection enabled') : c('来源或连接不可用', 'Source or connection unavailable')}</p>
          {item.error && <p className="text-sm text-danger break-words">{item.error}</p>}
          <div className="flex flex-wrap items-center gap-4 text-sm">
            {safeSettings(item) && <Link className="text-accent" to={safeSettings(item)!}>{c('配置账号', 'Configure account')}</Link>}
            <Link className="text-accent" to="/skills?tab=mcp">MCP</Link><Link className="text-accent" to="/security?tab=privacy">{c('授权', 'Access')}</Link>
            {supports(item, 'sync') && <button type="button" className={button} disabled={busy || !item.enabled || !item.available || item.running} onClick={() => void run({ action: 'sync', source_id: item.id }, c('同步完成', 'Sync completed'))}>{c('同步', 'Sync')}</button>}
          </div>
        </section>)}
      </div>}
      {tab === 'records' && <div className="space-y-3">
        {sourceSelect}
        <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); setOffset(0); if (query === draft && offset === 0) void loadRecords(); else setQuery(draft) }}>
          <input aria-label={c('搜索记录', 'Search records')} placeholder={c('搜索记录', 'Search records')} className={`${input} flex-1`} value={draft} onChange={event => setDraft(event.target.value)} />
          <button type="submit" className={button} disabled={busy || !source?.enabled || !source.available}>{c('搜索', 'Search')}</button>
          {supports(source, 'export') && <button type="button" className={button} disabled={busy || !source?.enabled || !source.available} onClick={exportData}>{c('导出', 'Export')}</button>}
        </form>
        {recordLoading && <p className="text-sm text-content-secondary">{c('正在读取', 'Loading records')}</p>}
        {!recordLoading && !records.length && !resources.length && <p className="text-sm text-content-secondary">{source && (!source.enabled || !source.available) ? c('来源或连接不可用', 'The source or connection is unavailable') : c('没有可显示的记录', 'No records to show')}</p>}
        {resources.map(row => <article key={row.id} className="rounded-card border border-default bg-surface p-4 space-y-2">
          <h4 className="font-medium break-words">{row.name}</h4>
          <p className="text-xs text-content-secondary break-words">{row.kind} · {c('引用；内容由来源管理', 'Reference; content managed by source')}</p>
          {row.operations.includes('read') && <button type="button" className="text-sm text-accent" onClick={() => void readResource(row)}>{c('查看内容', 'View content')}</button>}
          {expanded === row.id && <p className="whitespace-pre-wrap break-words text-sm">{resourceContent ?? c('正在读取', 'Loading content')}</p>}
        </article>)}
        {records.map(row => <article key={row.id} className="rounded-card border border-default bg-surface p-4 space-y-2">
          <h4 className="font-medium break-words">{row.item.title || row.item.source_id}</h4><p className="text-sm text-content-secondary break-words">{row.item.snippet}</p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary"><span>{row.item.occurred_at}</span>
            <button type="button" className="text-accent" onClick={() => setExpanded(expanded === row.id ? '' : row.id)}>{c('查看内容', 'View content')}</button>
            {/^(https?:)\/\//i.test(row.item.url || '') && <a href={row.item.url} target="_blank" rel="noopener noreferrer" className="text-accent">{c('打开来源', 'Open source')}</a>}
            <button type="button" className="text-danger" disabled={busy} onClick={() => { if (window.confirm(c('仅删除本地数据记录，保留来源和业务历史？', 'Delete the local record while keeping upstream and business history?'))) void run({ action: 'delete_record', record_id: row.id }, c('已删除', 'Deleted')) }}>{c('删除记录', 'Delete record')}</button>
          </div>
          {expanded === row.id && <p className="whitespace-pre-wrap break-words text-sm">{typeof row.item.payload.body === 'string' ? row.item.payload.body : c('此记录仅保留引用', 'This record retains a reference only')}</p>}
        </article>)}
        <div className="flex items-center gap-3 text-sm"><button type="button" className={button} disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{c('上一页', 'Previous')}</button><span>{total}</span><button type="button" className={button} disabled={busy || offset + records.length + resources.length >= total} onClick={() => setOffset(offset + 50)}>{c('下一页', 'Next')}</button></div>
      </div>}
      {tab === 'sync' && <div className="space-y-4">
        {sourceSelect}
        <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (source) void run({ action: 'subscribe', source_id: source.id, consumer_id: consumer, filter: filter ? { q: filter } : {}, include_existing: true }, c('订阅已添加', 'Subscription added')) }}>
          <label className="text-sm">{c('消费者', 'Consumer')}<select aria-label={c('消费者', 'Consumer')} className={`${input} block mt-1`} value={consumer} disabled={busy} onChange={event => setConsumer(event.target.value)}>{state.consumers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="text-sm flex-1">{c('过滤关键词', 'Filter keyword')}<input className={`${input} w-full block mt-1`} value={filter} disabled={busy} onChange={event => setFilter(event.target.value)} /></label>
          <button type="submit" className={button} disabled={busy || !source?.enabled || !source.available || !supports(source, 'subscribe')}>{c('添加订阅', 'Add subscription')}</button>
        </form>
        <p className="text-xs text-content-secondary">{c('订阅不会授予读取权限；投递时仍会检查授权。', 'A subscription does not grant read access. Delivery checks current authorization.')}</p>
        {state.subscriptions.map(item => <section key={item.id} className="rounded-card border border-default bg-surface p-4 space-y-3">
          <div className="flex items-center justify-between gap-3"><h4 className="font-medium">{state.sources.find(row => row.id === item.source_id)?.name} → {state.consumers.find(row => row.id === item.consumer)?.name || item.consumer}</h4><Toggle label={c('启用订阅', 'Enable subscription')} checked={item.enabled} disabled={busy} onChange={enabled => void run({ action: 'subscription', subscription_id: item.id, enabled }, c('已保存', 'Saved'))} /></div>
          {state.deliveries.filter(row => row.subscription_id === item.id).map(row => <div key={row.event_id} className="text-sm flex flex-wrap justify-between gap-2"><span>{row.state === 'delivered' ? c('已投递', 'Delivered') : row.state === 'failed' ? c('投递失败', 'Delivery failed') : c('待投递', 'Pending')} · {row.attempts}</span>{row.error && <span className="text-danger break-words">{row.error}</span>}</div>)}
          <button type="button" className={button} disabled={busy || !item.enabled} onClick={() => void run({ action: 'dispatch', subscription_id: item.id }, c('投递处理完成', 'Delivery attempt completed'))}>{c('重试投递', 'Retry delivery')}</button>
        </section>)}
      </div>}
      {tab === 'storage' && <div className="space-y-4">
        {state.sources.filter(item => item.representation !== 'reference').map(item => <StorageForm key={`${item.id}:${item.storage}:${item.retention_days}`} source={item} busy={busy} save={values => void run({ action: 'source', source_id: item.id, ...values }, c('已保存', 'Saved'))}
          purge={() => { if (window.confirm(c('清理此来源的本地记录，保留来源文件、账号和简报历史？', 'Clear local records while keeping upstream files, accounts and briefing history?'))) void run({ action: 'cleanup', source_id: item.id, all_records: true }, c('已清理', 'Cleared')) }} />)}
        {state.storage.categories.map(item => <section key={item.id} className="rounded-card border border-default bg-surface p-4 space-y-2 text-sm"><div className="flex justify-between gap-3"><h4 className="font-medium">{item.name[getLang() === 'zh' ? 'zh' : 'en']}</h4><span>{bytes(item.bytes)}</span></div><p className="text-xs text-content-secondary break-all">{item.path}</p><p className="text-content-secondary">{item.retention[getLang() === 'zh' ? 'zh' : 'en']}</p>
          {item.actions.filter(action => ['clear_temporary', 'clear_runs'].includes(action)).map(action => <button type="button" key={action} className={button} disabled={busy} onClick={() => { if (window.confirm(c('确认清理这些缓存？', 'Clear these cached files?'))) void run({ action: 'cleanup_storage', cleanup_action: action }, c('已清理', 'Cleared')) }}>{action === 'clear_temporary' ? c('清理临时文件', 'Clear temporary files') : c('清理运行缓存', 'Clear run cache')}</button>)}
          {item.id === 'conversations' && <Link className="text-accent" to="/chat">{c('管理对话', 'Manage conversations')}</Link>}
        </section>)}
      </div>}
    </>}
    </div>
    </main>
  </div>
}

function StorageForm({ source, busy, save, purge }: { source: DataSourceInfo; busy: boolean; save: (values: Record<string, unknown>) => void; purge: () => void }) {
  const [storage, setStorage] = useState(source.storage)
  const [days, setDays] = useState(String(source.retention_days))
  return <form className="rounded-card border border-default bg-surface p-4 space-y-3" onSubmit={event => {
    event.preventDefault()
    if (storage === 'reference' && source.storage !== 'reference' && !window.confirm(c('切换为引用会清除缓存正文，保留来源与业务历史。继续？', 'Reference storage removes cached content while keeping upstream and business history. Continue?'))) return
    save({ storage, retention_days: Number(days) })
  }}><h4 className="font-medium">{source.name}</h4><div className="flex flex-wrap items-end gap-3">
    <label className="text-sm">{c('存储策略', 'Storage policy')}<select aria-label={`${c('存储策略', 'Storage policy')} ${source.name}`} className={`${input} block mt-1`} value={storage} disabled={busy} onChange={event => setStorage(event.target.value as DataSourceInfo['storage'])}><option value="reference">{c('引用', 'Reference')}</option><option value="cache">{c('缓存', 'Cache')}</option><option value="persistent">{c('持久化', 'Persistent')}</option></select></label>
    {storage === 'cache' && <label className="text-sm">{c('保留天数', 'Retention days')}<input type="number" min={1} max={3650} required value={days} disabled={busy} className={`${input} block mt-1 w-28`} onChange={event => setDays(event.target.value)} /></label>}
    <button type="submit" className={button} disabled={busy} aria-label={`${c('保存策略', 'Save policy')} ${source.name}`}>{c('保存策略', 'Save policy')}</button><button type="button" className={`${button} text-danger`} disabled={busy} onClick={purge}>{c('清理本地记录', 'Clear local records')}</button>
  </div></form>
}
