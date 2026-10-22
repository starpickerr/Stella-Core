import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Database, HardDrive, LayoutList, RefreshCw, Waypoints } from 'lucide-react'
import apiClient from '../api/client'
import type { DataSnapshot } from '../api/dataTypes'
import { t } from '../i18n'
import PageHeader from '../components/PageHeader'
import { useSessionStore } from '../store/sessionStore'
import DataUsage, { SourceIcon } from './data/DataUsage'
import DataStorage from './data/DataStorage'
import SourceResources from './data/SourceResources'
import { c, button, panel, settingsPath, sourceDescription, sourceOrigin, sourceName } from './data/presentation'

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
  const choose = (next: string) => {
    params.set('section', next); params.delete('source')
    setError(''); setMessage('')
    navigate(`/data?${params}`, { replace: true })
  }
  const source = state?.sources.find(source => source.id === params.get('source')) || state?.sources[0]
  return <div className="flex-1 flex flex-col min-h-0">
    <PageHeader><h1 className="text-xl font-bold text-content">{t('menu_data')}</h1></PageHeader>
    <main data-stella-scroll className="flex-1 min-w-0 overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <nav aria-label={c('数据分类', 'Data sections')} className="flex flex-wrap gap-1 rounded-btn bg-surface-2 p-1">
            {sections().map(section => <button key={section.id} type="button" aria-current={tab === section.id ? 'page' : undefined}
              className={`rounded-btn px-3 py-2 text-sm transition-colors ${tab === section.id ? 'bg-surface text-content font-medium shadow-sm' : 'text-content-secondary hover:text-content'}`}
              onClick={() => choose(section.id)}>{section.title}</button>)}
          </nav>
          {!resourceView && <button type="button" className={button} aria-label={c('刷新', 'Refresh')} disabled={loading || busy} onClick={() => void refresh()}><RefreshCw size={15} className={busy ? 'animate-spin' : ''} /></button>}
        </div>
        {error && <p role="alert" className="rounded-btn border border-danger/30 p-3 text-sm text-danger whitespace-pre-wrap">{error}</p>}
        {message && <p role="status" className="text-sm text-accent">{message}</p>}
        {loading && <p role="status" className="text-sm text-content-secondary">{c('正在加载数据', 'Loading data')}</p>}
        {!loading && !state && <button type="button" className={button} onClick={() => void refresh()}>{c('重试', 'Retry')}</button>}
        {state && <>
          {!!state.errors?.length && <details className="text-xs text-content-secondary"><summary className="cursor-pointer">{c('部分信息源暂时无法更新', 'Some sources could not be refreshed')}</summary><ul className="mt-2 space-y-1">{state.errors.map(row => <li key={row.provider} className="break-words">{row.provider}: {row.message}</li>)}</ul></details>}
          {tab === 'overview' && <section className="space-y-5">
            <div><h2 className="text-lg font-semibold">{c('总览', 'Overview')}</h2><p className="mt-1 text-sm leading-relaxed text-content-secondary">{c('从哪里获取数据、哪些功能在使用，以及数据保存在哪里。', 'Understand where data comes from, which features use it and where it is stored.')}</p></div>
            <div className={`${panel} divide-y divide-default`}>{sections().slice(1).map(section => <button key={section.id} type="button" onClick={() => choose(section.id)} className="w-full flex items-start gap-4 p-5 text-left hover:bg-surface-2 transition-colors">
              <section.icon size={21} className="shrink-0 mt-0.5 text-content-secondary" /><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{section.title}</h3><p className="mt-2 text-sm leading-relaxed text-content-secondary">{section.description}</p></div><ArrowRight size={16} className="shrink-0 mt-1 text-content-tertiary" />
            </button>)}</div>
            <p className="text-xs text-content-secondary">{c(`当前已注册 ${state.sources.length} 个信息源。访问权限在安全中管理。`, `${state.sources.length} sources are registered. Access is managed in Security.`)}</p>
          </section>}
          {tab === 'sources' && !resourceView && <section className="space-y-5">
            <div><h2 className="text-lg font-semibold">{c('信息源', 'Sources')}</h2><p className="mt-1 text-sm leading-relaxed text-content-secondary">{sections()[1].description}</p></div>
            {!state.sources.length && <div className={`${panel} p-5 text-sm text-content-secondary`}>{c('尚无已注册的信息源。请先在能力中连接服务，或配置来源账号。', 'No sources are registered. Connect a service in Capabilities or configure a source account first.')}</div>}
            <div className={`${panel} divide-y divide-default`}>{state.sources.map(source => {
              const settings = settingsPath(source)
              const usable = source.enabled && source.available
              return <article key={source.id} data-testid={`data-source-${source.id}`} className="flex items-start gap-3 p-4 sm:p-5">
                <div className="pt-0.5"><SourceIcon source={source} size={20} /></div><div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold break-words">{sourceName(source)}</h3><span className={`rounded-full px-2 py-0.5 text-xs ${usable ? 'bg-accent-soft text-accent' : 'bg-surface-2 text-content-secondary'}`}>{!source.enabled ? c('已停用', 'Disabled') : source.available ? c('可用', 'Available') : c('暂不可用', 'Unavailable')}</span></div>
                  <p className="mt-1.5 text-xs leading-relaxed text-content-secondary">{sourceDescription(source)}</p><p className="mt-1 text-xs text-content-tertiary">{sourceOrigin(source)}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
                    <Link aria-disabled={!usable} onClick={event => { if (!usable) event.preventDefault() }} className={usable ? 'text-accent hover:underline' : 'text-content-tertiary'} to={`/data?${new URLSearchParams({ ...scope, section: 'resources', source: source.id })}`}>{c('浏览资源', 'Browse resources')}</Link>
                    {settings && <Link className="text-content-secondary hover:text-content" to={settings.startsWith('/data/') ? `${settings}?${new URLSearchParams(scope)}` : settings}>{c('配置', 'Configure')}</Link>}
                    {!source.enabled && <button type="button" className="text-accent" disabled={busy} onClick={() => void save({ action: 'source', source_id: source.id, enabled: true })}>{c('启用信息源', 'Enable source')}</button>}
                  </div>
                </div>
              </article>
            })}</div>
            <p className="text-xs leading-relaxed text-content-secondary">{c('这里只展示已经注册的来源。可用性不代表访问授权，读取内容时仍会检查权限。', 'Only registered sources are shown. Availability does not grant access; reading content still checks permissions.')}</p>
            <div className="flex flex-wrap gap-4 text-xs text-accent"><Link to="/skills?tab=mcp">{c('管理来源连接', 'Manage connections')}</Link><Link to="/data/sources/email">{c('配置邮箱', 'Configure email')}</Link><Link to="/data/sources/elearning">{c('配置 eLearning', 'Configure eLearning')}</Link></div>
          </section>}
          {resourceView && source && <SourceResources key={`${source.id}:${scopeKey}`} source={source} scope={scope} back={() => choose('sources')} busy={busy} save={save} />}
          {resourceView && !source && <p className="text-sm text-content-secondary">{c('没有可浏览的信息源', 'No sources to browse')}</p>}
          {tab === 'usage' && <DataUsage state={state} busy={busy} save={save} />}
          {tab === 'storage' && <DataStorage state={state} busy={busy} save={save} />}
        </>}
      </div>
    </main>
  </div>
}
