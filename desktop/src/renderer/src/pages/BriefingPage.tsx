import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw, Settings, Sun } from 'lucide-react'
import apiClient from '../api/client'
import { t } from '../i18n'
import type { Briefing, BriefingDetail as Detail, BriefingItemStatus, BriefingSource } from '../types'
import { BriefingList } from './briefing/BriefingList'
import { BriefingDetail } from './briefing/BriefingDetail'
import { SettingsPanel } from './briefing/SettingsPanel'
import { useBriefingRunStore } from '../store/briefingRunStore'

const localDay = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

const BriefingPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [briefings, setBriefings] = useState<Briefing[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const generating = useBriefingRunStore((state) => state.running)
  const pendingResultId = useBriefingRunStore((state) => state.pendingResultId)
  const runError = useBriefingRunStore((state) => state.error)
  const runBriefing = useBriefingRunStore((state) => state.run)
  const takeRunResult = useBriefingRunStore((state) => state.takeResult)
  const clearRunError = useBriefingRunStore((state) => state.clearError)
  const [marking, setMarking] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sources, setSources] = useState<BriefingSource[]>([])
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [error, setError] = useState('')
  const [version, setVersion] = useState<number | null>(null)
  const [today, setToday] = useState(() => localDay())
  const todayRow = briefings.find((row) => row.id === `brf-${today}-morning`)
  const todayBriefing = todayRow?.generated_at ? todayRow : undefined
  const [revision, setRevision] = useState(0)
  const listRequest = useRef(0)
  const sourceRequest = useRef(0)

  const loadSources = useCallback(async () => {
    const request = ++sourceRequest.current
    setSourcesLoading(true)
    try {
      const rows = await apiClient.getBriefingSources()
      if (request !== sourceRequest.current) return
      setSources(rows)
    } catch (err) { if (request === sourceRequest.current) setError(err instanceof Error ? err.message : String(err)) }
    finally { if (request === sourceRequest.current) setSourcesLoading(false) }
  }, [])

  const load = useCallback(async (silent = false) => {
    setToday(localDay())
    const request = ++listRequest.current
    if (!silent) { setLoading(true); setError('') }
    try {
      const rows = await apiClient.getBriefings()
      if (request === listRequest.current) setBriefings(rows)
    } catch (err) {
      if (request === listRequest.current) setError(String(err instanceof Error ? err.message : err))
    } finally {
      if (request === listRequest.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void load()
    const timer = window.setInterval(() => void load(true), 30000)
    const onFocus = () => void load(true)
    window.addEventListener('focus', onFocus)
    return () => { listRequest.current++; clearInterval(timer); window.removeEventListener('focus', onFocus) }
  }, [baseUrl, load])

  useEffect(() => {
    if (!settingsOpen) void loadSources()
    return () => { sourceRequest.current++ }
  }, [baseUrl, settingsOpen, loadSources])

  useEffect(() => {
    if (!selectedId) { setDetail(null); setDetailLoading(false); return }
    let cancelled = false
    setDetailLoading(true)
    setDetail((value) => value?.briefing.id === selectedId ? value : null)
    const request = version === null ? apiClient.getBriefing(selectedId) : apiClient.getBriefingRevision(selectedId, version)
    request.then((value) => {
      if (!cancelled) setDetail(value)
    }).catch((err) => {
      if (!cancelled) { setDetail(null); setError(String(err instanceof Error ? err.message : err)) }
    }).finally(() => { if (!cancelled) setDetailLoading(false) })
    return () => { cancelled = true }
  }, [selectedId, baseUrl, revision, version])

  useEffect(() => {
    const latest = briefings.find((row) => row.id === selectedId)
    if (version === null && detail && latest && latest.updated_at !== detail.briefing.updated_at) {
      setRevision((n) => n + 1)
    }
  }, [briefings])

  useEffect(() => {
    if (!pendingResultId) return
    const id = takeRunResult()
    if (!id) return
    setVersion(null)
    setSelectedId(id)
    setRevision((n) => n + 1)
    void load()
  }, [pendingResultId, takeRunResult, load])

  const generate = () => {
    setError('')
    void runBriefing(todayBriefing ? 'update' : 'create')
  }

  const mark = async (id: string, status: BriefingItemStatus) => {
    setMarking(true)
    setError('')
    try {
      const item = await apiClient.updateBriefingItem(id, status)
      setDetail((value) => value ? { ...value, items: value.items.map((row) => row.id === id ? item : row) } : value)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally { setMarking(false) }
  }

  return <div className="flex-1 flex flex-col min-h-0">
    <header className="px-6 pt-5 pb-4 border-b border-default flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold text-content">{t('menu_briefing')}</h1><p className="text-xs text-content-tertiary mt-1">{t('briefing_desc')}</p></div>
      <div className="flex gap-2">
        <button type="button" disabled={generating || marking} onClick={() => { clearRunError(); void load(); void loadSources(); setRevision((n) => n + 1) }} aria-label={t('briefing_refresh')}
          className="h-8 px-2 rounded-btn border border-default text-content-secondary hover:bg-surface-2 disabled:opacity-50"><RefreshCw size={15} /></button>
        <button type="button" onClick={() => setSettingsOpen((open) => !open)} aria-label={t('briefing_settings')} aria-expanded={settingsOpen}
          className={`h-8 px-2 rounded-btn border border-default text-content-secondary hover:bg-surface-2 ${settingsOpen ? 'bg-surface-2' : ''}`}><Settings size={15} /></button>
        <button type="button" disabled={settingsOpen || loading || sourcesLoading || generating || marking || !sources.length} onClick={() => void generate()}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium disabled:opacity-50">
          {generating ? <Loader2 size={14} className="animate-spin" /> : <Sun size={14} />}{t(generating ? 'briefing_generating' : todayBriefing ? 'briefing_update' : 'briefing_generate')}
        </button>
      </div>
    </header>
    {(error || runError) && <div role="alert" className="mx-6 mt-4 p-3 rounded-card bg-danger-soft text-danger text-sm flex items-start gap-3"><span className="flex-1 break-words">{error || runError}</span><button type="button" onClick={() => { clearRunError(); void load(); void loadSources(); setRevision((n) => n + 1) }}>{t('briefing_retry')}</button></div>}
    {settingsOpen ? <div className="flex-1 overflow-y-auto p-6"><SettingsPanel key={baseUrl} onBack={() => setSettingsOpen(false)} /></div> : <div className="flex-1 flex min-h-0">
      <aside className={`w-full lg:w-72 lg:shrink-0 lg:border-r border-default overflow-y-auto p-4 ${selectedId ? 'hidden lg:block' : ''}`}>
        <h2 className="text-xs font-semibold text-content-tertiary mb-3">{t('briefing_history')}</h2>
        {loading ? <div className="flex items-center gap-2 text-sm text-content-tertiary py-8"><Loader2 size={16} className="animate-spin" />{t('briefing_loading')}</div> : <BriefingList briefings={briefings} selectedId={selectedId} onSelect={(id) => { setError(''); setVersion(null); setSelectedId(id) }} />}
      </aside>
      <main className={`flex-1 min-w-0 overflow-y-auto p-6 ${!selectedId ? 'hidden lg:block' : ''}`}>
        {detail ? <BriefingDetail detail={detail} loading={detailLoading} version={version} onVersion={setVersion} busy={marking || generating} onBack={() => setSelectedId(null)} onStatus={(id, status) => void mark(id, status)} />
          : detailLoading ? <div className="flex items-center justify-center text-content-tertiary py-16"><Loader2 size={18} className="animate-spin mr-2" />{t('briefing_loading')}</div>
            : <div className="text-center text-sm text-content-tertiary py-20">{t('briefing_select')}{selectedId && <button type="button" onClick={() => setSelectedId(null)} className="block mx-auto mt-4 text-accent">{t('briefing_back')}</button>}</div>}
      </main>
    </div>}
  </div>
}

export default BriefingPage
