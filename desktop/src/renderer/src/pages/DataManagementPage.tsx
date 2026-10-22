import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Database, HardDrive, LayoutList, RefreshCw, Waypoints } from 'lucide-react'
import apiClient from '../api/client'
import type { DataSnapshot } from '../api/dataTypes'
import { t } from '../i18n'
import PageHeader from '../components/PageHeader'
import { useSessionStore } from '../store/sessionStore'
import DataUsage from './data/DataUsage'
import DataStorage from './data/DataStorage'
import DataSources from './data/DataSources'
import DataOverview from './data/DataOverview'
import { c, button, groupSources } from './data/presentation'

const sections = () => [
  { id: 'overview', title: c('总览', 'Overview'), description: c('了解信息源、数据使用和数据存储各自管理什么。', 'Understand the roles of sources, data usage and storage.'), icon: LayoutList },
  { id: 'sources', title: c('信息源', 'Sources'), description: c('Stella 有哪些数据可以使用、数据从哪里来，以及当前是否可用。', 'See which data Stella can use, where it comes from and whether it is available.'), icon: Database },
  { id: 'usage', title: c('数据使用', 'Data usage'), description: c('管理简报等功能与信息源之间的使用关系。', 'Manage which sources are used by features such as Briefing.'), icon: Waypoints },
  { id: 'storage', title: c('数据存储', 'Data storage'), description: c('查看 Stella 相关数据的存储位置和保留方式。', 'See where Stella data is stored and how it is retained.'), icon: HardDrive },
]

export default function DataManagementPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const activeSession = useSessionStore(state => state.activeId)
  const params = new URLSearchParams(location.search)
  const requested = params.get('section') || 'overview'
  const resourceView = requested === 'resources' || requested === 'records'
  const tab = resourceView ? 'sources' : requested === 'sync' ? 'usage' : sections().some(section => section.id === requested) ? requested : 'overview'
  const agent = params.get('agent') || ''
  const session = params.has('session') ? params.get('session') || '' : activeSession || ''
  const scope = useMemo(() => ({ agent, session }), [agent, session])
  const scopeKey = `${agent}:${session}`
  const includeStorage = tab === 'storage'
  const requestKey = `${scopeKey}:${includeStorage}`
  const [state, setState] = useState<DataSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const inFlight = useRef(false)
  const currentScope = useRef(requestKey)
  currentScope.current = requestKey
  const mounted = useRef(true)
  const load = useCallback(async (refresh: boolean, signal?: AbortSignal) => {
    const result = await apiClient.getDataSnapshot(refresh, signal, scope, includeStorage)
    if (!signal?.aborted && mounted.current && currentScope.current === requestKey) setState(result)
  }, [scope, requestKey, includeStorage])
  useEffect(() => {
    const request = new AbortController()
    mounted.current = true
    setState(null); setError(''); setMessage(''); setLoading(true)
    void load(true, request.signal).catch(cause => { if (!request.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause)) })
      .finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => { mounted.current = false; request.abort() }
  }, [load])
  const save = async (body: Record<string, unknown>): Promise<boolean> => {
    if (inFlight.current) return false
    inFlight.current = true; setBusy(true); setError(''); setMessage('')
    try {
      const result = await apiClient.dataCommand(body, scope)
      if (!mounted.current || currentScope.current !== requestKey) return false
      if (result.sync?.errors.length) throw new Error(result.sync.errors.join('\n'))
      await load(false)
      if (mounted.current && currentScope.current === requestKey) setMessage(body.action === 'cleanup_storage' || body.action === 'cleanup' ? c('已清理', 'Cleared') : c('已保存', 'Saved'))
      return true
    } catch (cause) {
      if (mounted.current && currentScope.current === requestKey) setError(cause instanceof Error ? cause.message : String(cause))
      return false
    } finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  const refresh = async () => {
    if (inFlight.current) return
    inFlight.current = true; setBusy(true); setError(''); setMessage('')
    try { await load(true) } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }
  const sectionPath = (next: string) => {
    const query = new URLSearchParams(location.search)
    query.set('section', next); query.delete('source')
    return `/data?${query}`
  }
  const choose = (next: string) => {
    setError(''); setMessage('')
    navigate(sectionPath(next), { replace: true })
  }
  const groups = groupSources(state?.sources || [])
  return <div className="flex-1 flex flex-col min-h-0 min-w-0">
    <PageHeader className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight text-content">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-card bg-accent-soft text-accent"><Database size={23} aria-hidden="true" /></span>{t('menu_data')}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-content-secondary">{c('管理信息源、功能的数据使用和存储位置。', 'Manage information sources, feature usage and storage locations.')}</p>
      </div>
      <button type="button" className={`${button} min-h-10 shrink-0`} aria-label={c('刷新', 'Refresh')} title={c('刷新', 'Refresh')} disabled={loading || busy} onClick={() => void refresh()}><RefreshCw size={17} aria-hidden="true" className={busy ? 'animate-spin motion-reduce:animate-none' : ''} /></button>
    </PageHeader>
    <main data-stella-scroll className="flex-1 min-w-0 overflow-y-auto px-4 sm:px-6 py-5 sm:py-6">
      <div className="max-w-5xl mx-auto space-y-6">
        <nav aria-label={c('数据分类', 'Data sections')} className="flex gap-1 overflow-x-auto border-b border-default pb-3">
          {sections().map(section => <button key={section.id} type="button" aria-current={tab === section.id ? 'page' : undefined}
            className={`flex min-h-10 shrink-0 items-center gap-2 rounded-btn px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-accent ${tab === section.id ? 'bg-accent-soft text-content font-semibold' : 'text-content-secondary hover:bg-surface-2'}`}
            onClick={() => choose(section.id)}><section.icon size={16} aria-hidden="true" className={tab === section.id ? 'text-accent' : 'text-content-tertiary'} />{section.title}</button>)}
        </nav>
        {error && <p role="alert" className="rounded-btn border border-danger/30 p-3 text-sm text-danger whitespace-pre-wrap">{error}</p>}
        {message && <p role="status" className="text-sm text-accent">{message}</p>}
        {loading && <p role="status" className="text-sm text-content-secondary">{c('正在加载数据…', 'Loading data…')}</p>}
        {!loading && !state && <button type="button" className={button} onClick={() => void refresh()}>{c('重试', 'Retry')}</button>}
        {state && <>
          {!!state.errors?.length && <details className="text-xs text-content-secondary"><summary className="cursor-pointer">{c('部分信息源暂时无法更新', 'Some sources could not be refreshed')}</summary><ul className="mt-2 space-y-1">{state.errors.map(row => <li key={row.provider} className="break-words">{row.provider}: {row.message}</li>)}</ul></details>}
          {tab === 'overview' && <DataOverview state={state} groups={groups} to={sectionPath} />}
          {tab === 'sources' && <DataSources groups={groups} scope={scope} />}
          {tab === 'usage' && <DataUsage state={state} busy={busy} save={save} />}
          {tab === 'storage' && <DataStorage state={state} busy={busy} save={save} />}
        </>}
      </div>
    </main>
  </div>
}
