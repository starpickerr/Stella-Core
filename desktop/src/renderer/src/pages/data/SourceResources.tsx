import React, { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import type { DataBrowseScope, DataResource, DataSourceInfo } from '../../api/dataTypes'
import apiClient from '../../api/client'
import { c, button, input, panel, sourceDescription, supports, resourceTypeName, sourceName } from './presentation'

export default function SourceResources({ source, scope, back, busy, save }: { source: DataSourceInfo; scope: DataBrowseScope; back: () => void; busy: boolean; save: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [resources, setResources] = useState<DataResource[]>([])
  const [kind, setKind] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState('')
  const [content, setContent] = useState<string | null>(null)
  const request = useRef<AbortController | null>(null)
  const usable = source.enabled && source.available
  const load = useCallback(async () => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setResources([]); setExpanded(''); setContent(null); setError(''); setLoading(true)
    try {
      const result = await apiClient.getDataResources(source.id, query, offset, controller.signal, scope, kind)
      if (!controller.signal.aborted) { setResources(result.resources); setTotal(result.total) }
    } catch (cause) {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : String(cause)); setTotal(0) }
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }, [source.id, scope, query, offset, kind])
  useEffect(() => {
    if (usable) void load()
    else { request.current?.abort(); setResources([]); setExpanded(''); setContent(null); setLoading(false); setTotal(0) }
    return () => request.current?.abort()
  }, [usable, load])
  useEffect(() => {
    const refresh = () => { if (usable) void load() }
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [usable, load])
  const read = async (resource: DataResource) => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setExpanded(resource.id); setContent(null); setError('')
    try {
      const result = await apiClient.readDataResource(source.id, resource.id, controller.signal, scope)
      if (!controller.signal.aborted) setContent(typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2))
    } catch (cause) {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : String(cause)); setExpanded('') }
    }
  }
  const exportData = async () => {
    setError('')
    try {
      const result = await apiClient.dataCommand({ action: 'export', source_id: source.id }, scope)
      if (!result.export) throw new Error(c('导出结果为空', 'Missing export result'))
      const href = URL.createObjectURL(new Blob([JSON.stringify(result.export, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a'); link.href = href; link.download = `stella-${source.kind.replace(/[^A-Za-z0-9_-]/g, '_')}-${Date.now()}.json`; link.click()
      setTimeout(() => URL.revokeObjectURL(href), 1000)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }
  return <div className="space-y-4">
    <button type="button" className="inline-flex items-center gap-1 text-sm text-content-secondary hover:text-content" onClick={back}><ArrowLeft size={15} />{c('返回信息源', 'Back to sources')}</button>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{sourceName(source)}</h2><p className="mt-1 text-sm text-content-secondary">{sourceDescription(source)}</p></div>
      <button type="button" className={button} disabled={busy || loading || !usable} onClick={() => void load()}><RefreshCw size={15} />{c('刷新资源', 'Refresh resources')}</button></div>
    <p className="text-xs leading-relaxed text-content-secondary">{c('按需读取来源内容，不会自动加入当前模型上下文。', 'Source content is read on demand and is not automatically added to the model context.')}</p>
    {error && <p role="alert" className="rounded-btn border border-danger/30 p-3 text-sm text-danger whitespace-pre-wrap">{error}</p>}
    <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); setOffset(0); if (draft === query && offset === 0) void load(); else setQuery(draft) }}>
      <label className="min-w-0 flex-1 text-xs text-content-secondary">{c('搜索资源', 'Search resources')}<input aria-label={c('搜索资源', 'Search resources')} className={`${input} block w-full mt-1`} value={draft} onChange={event => setDraft(event.target.value)} /></label>
      <label className="text-xs text-content-secondary">{c('资源类型', 'Resource type')}<select aria-label={c('资源类型', 'Resource type')} className={`${input} mt-1 block max-w-full`} value={kind} onChange={event => { setKind(event.target.value); setOffset(0) }}>
        <option value="">{c('全部类型', 'All types')}</option>{(source.resource_kinds || [source.kind]).map(type => <option key={type} value={type}>{resourceTypeName(type)}</option>)}
      </select></label>
      <button type="submit" className={button} disabled={!usable || busy}>{c('搜索', 'Search')}</button>
      {supports(source, 'sync') && <button type="button" className={button} disabled={!usable || busy || source.running} onClick={() => void save({ action: 'sync', source_id: source.id }).then(ok => { if (ok) void load() })}>{c('同步', 'Sync')}</button>}
      {supports(source, 'export') && <button type="button" className={button} disabled={!usable || busy} onClick={() => void exportData()}>{c('导出', 'Export')}</button>}
    </form>
    {loading && <p role="status" className="text-sm text-content-secondary">{c('正在读取', 'Loading resources')}</p>}
    {!loading && !resources.length && <p className={`${panel} p-5 text-sm text-content-secondary`}>{usable ? c('没有可显示的资源', 'No resources to show') : c('来源暂不可用，请检查来源配置或能力状态。', 'This source is unavailable. Check its configuration or capability status.')}</p>}
    {resources.map(resource => <article key={resource.id} className={`${panel} p-4 space-y-2`}>
      <h3 className="text-sm font-medium break-words">{resource.name}</h3><p className="text-xs text-content-secondary">{resourceTypeName(resource.kind)}</p>
      <div className="flex flex-wrap gap-4">
        {resource.operations.includes('read') && <button type="button" className="text-sm text-accent" onClick={() => void read(resource)}>{c('查看内容', 'View content')}</button>}
        {supports(source, 'delete') && <button type="button" className="text-sm text-danger" disabled={busy} onClick={() => {
          if (window.confirm(c('仅删除 Core 本地记录，保留来源内容？', 'Delete only the Core record, keeping the original content?'))) void save({ action: 'delete_record', record_id: resource.reference }).then(ok => { if (ok) void load() })
        }}>{c('删除本地记录', 'Delete local record')}</button>}
      </div>
      {expanded === resource.id && <p className="whitespace-pre-wrap break-words text-sm">{content ?? c('正在读取', 'Loading content')}</p>}
    </article>)}
    <div className="flex items-center gap-3 text-sm"><button type="button" className={button} disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{c('上一页', 'Previous')}</button><span className="text-content-secondary">{c(`共 ${total} 项`, `${total} resources`)}</span><button type="button" className={button} disabled={loading || offset + resources.length >= total} onClick={() => setOffset(offset + 50)}>{c('下一页', 'Next')}</button></div>
  </div>
}
