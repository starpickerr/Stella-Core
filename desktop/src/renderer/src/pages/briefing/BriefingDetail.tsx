import React, { useEffect, useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { MailList } from './MailList'
import { ItemList } from './ItemList'
import { RevisionGraph } from './RevisionGraph'
import { t, getLang } from '../../i18n'
import type { BriefingDetail as Detail, BriefingDecision } from '../../types'
import { actionLabel as label } from './actionLabels'

export const BriefingDetail: React.FC<{
  detail: Detail
  loading: boolean
  version: number | null
  onVersion: (number: number | null) => void
  busy: boolean
  onBack: () => void
  onDecision: (id: string, decision: BriefingDecision) => Promise<void>
}> = ({ detail, loading, version, onVersion, busy, onBack, onDecision }) => {
  const briefing = detail.briefing
  const [category, setCategory] = useState<'candidate' | 'selected' | 'filtered' | null>(null)
  useEffect(() => { setCategory(null) }, [briefing.id])
  const [sourceFilter, setSourceFilter] = useState('email')
  const [overview, setOverview] = useState(false)
  const [tracked, setTracked] = useState<Pick<Detail, 'items' | 'actions' | 'preferences'> | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [overviewError, setOverviewError] = useState('')
  useEffect(() => {
    if (!overview || version !== null) return
    let active = true
    setOverviewLoading(true); setOverviewError('')
    apiClient.getBriefingOverview().then((value) => { if (active) setTracked(value) })
      .catch((err) => { if (active) setOverviewError(String(err instanceof Error ? err.message : err)) })
      .finally(() => { if (active) setOverviewLoading(false) })
    return () => { active = false }
  }, [overview, version, detail])
  const display = overview && version === null && tracked ? tracked : detail
  const preferences = detail.preferences
  const visibleItems = display.items.filter((item) => {
    const view = display.actions?.[item.id]
    if (!view || overview || version !== null) return true
    const important = preferences?.important_types.includes(view.information_type)
    if (!important && preferences?.show_low_priority === false && view.category === 'other') return false
    if (view.change_type !== 'unchanged') return true
    if (['failed', 'conflict'].includes(view.todo?.state ?? '') || ['failed', 'conflict'].includes(view.calendar?.state ?? '')) return true
    const deadline = view.facts.due_at ? Date.parse(String(view.facts.due_at)) : NaN
    const completed = view.todo?.business && 'status' in view.todo.business && ['completed', 'cancelled'].includes(view.todo.business.status)
    if (!completed && deadline < Date.now() + 3 * 86400000) return true
    return preferences?.show_ongoing !== false && (!preferences || preferences.reminder_frequency === 'daily') && (item.status === 'follow_up' || (view.category === 'needs_action' && !completed))
  })
  const snapshots = detail.mail ?? []
  const sourceTypes = [...new Set([...snapshots.map((row) => row.source), ...Object.values(briefing.source_windows ?? {}).map((window) => window.source)])]
  if (!sourceTypes.length) sourceTypes.push('email')
  const sourceName = (source: string) => source === 'email' ? t('briefing_email_section') : source === 'elearning' ? 'eLearning' : source
  const visibleMail = snapshots.filter((row) => row.source === sourceFilter && (category === 'candidate' || row.category === category))
  const categoryLabel = (key: string, source: string) => t(`${source === 'email' ? 'briefing_mail' : 'briefing_source'}_${key}`)
  return <div className="flex flex-col-reverse md:flex-row items-start gap-6">
    <section aria-busy={loading} className="min-w-0 w-full flex-1 space-y-5">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-accent lg:hidden"><ArrowLeft size={14} />{t('briefing_back')}</button>
      {loading ? <div role="status" className="flex items-center justify-center text-content-tertiary py-16"><Loader2 size={18} className="animate-spin mr-2" />{t('briefing_loading')}</div> : <>
        <div>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-content">{getLang() === 'en' ? `${briefing.id.slice(4, 14)} · ${t('menu_briefing')}` : briefing.title || briefing.id}</h2>
            <span className={`text-xs shrink-0 ${briefing.status === 'failed' ? 'text-danger' : 'text-content-secondary'}`}>{t(`briefing_${briefing.status}`)}</span>
          </div>
          <p className="text-sm text-content-secondary mt-2">{t('briefing_item_count')}：<span className="font-semibold text-content tabular-nums">{detail.items.length}</span></p>
          {briefing.generated_at && <p className="text-xs text-content-tertiary mt-1">{new Date(briefing.generated_at).toLocaleString()}</p>}
        </div>
        {version !== null && <div className="rounded-card border border-default bg-surface-2 p-3">
          <p className="text-xs font-medium text-content-secondary">{t('briefing_version_snapshot')} #{version}</p>
          <p className="text-xs text-content-tertiary mt-1 leading-relaxed">{t('briefing_readonly')}</p>
        </div>}
        {briefing.error_message && <div role="alert" className="rounded-card border border-danger-border bg-danger-soft text-danger text-sm p-3 break-words">{briefing.error_message}</div>}
        <details className="rounded-card border border-default p-3"><summary className="cursor-pointer text-sm font-medium text-content-secondary">{label('source_details')}</summary><div className="mt-3 space-y-4">
          {briefing.window_start && briefing.window_end && <p className="text-xs text-content-secondary leading-relaxed">{t('briefing_window')}：{new Date(briefing.window_start).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })} → {new Date(briefing.window_end).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</p>}
          {Object.keys(briefing.source_windows ?? {}).length > 0 && <div className="space-y-1 text-xs text-content-secondary">{Object.entries(briefing.source_windows).map(([id, window]) => <p key={id}>{window.name}：{new Date(window.start).toLocaleString()} → {new Date(window.end).toLocaleString()}</p>)}</div>}
          {sourceTypes.map((source) => {
          const rows = snapshots.filter((row) => row.source === source)
          const categories = [
            { key: 'candidate' as const, count: briefing.mail_snapshot_available ? rows.length : briefing.fetched_count },
            { key: 'selected' as const, count: briefing.mail_snapshot_available ? rows.filter((row) => row.category === 'selected').length : briefing.kept_count },
            { key: 'filtered' as const, count: briefing.mail_snapshot_available ? rows.filter((row) => row.category === 'filtered').length : briefing.filtered_count },
          ]
          return <section key={source} className="space-y-3" aria-label={sourceName(source)}>
            <h3 className="text-sm font-semibold text-content">{sourceName(source)}</h3>
            <div className="grid grid-cols-3 gap-3" role="group" aria-label={sourceName(source)}>
              {categories.map((row) => <button key={row.key} type="button" aria-pressed={sourceFilter === source && category === row.key}
                onClick={() => { setSourceFilter(source); setCategory(sourceFilter === source && category === row.key ? null : row.key) }}
                className={`rounded-card border p-3 text-left transition-colors ${sourceFilter === source && category === row.key ? 'border-accent bg-accent-soft' : 'border-transparent bg-surface-2 hover:border-default'}`}>
                <span className="block text-xl font-semibold text-content tabular-nums">{row.count}</span>
                <span className="block text-xs text-content-secondary mt-1">{categoryLabel(row.key, source)}</span>
                <span className="block text-[10px] text-content-tertiary mt-0.5 capitalize">{row.key}</span>
              </button>)}
            </div>
          </section>
        })}</div></details>
        {category ? <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-content">{sourceName(sourceFilter)} · {categoryLabel(category, sourceFilter)}</h3>
            <button type="button" onClick={() => setCategory(null)} className="text-xs text-accent hover:underline">{t('briefing_overview')}</button>
          </div>
          {briefing.mail_snapshot_available ? <MailList key={`${briefing.id}:${version ?? 'current'}:${briefing.updated_at}`} mail={visibleMail} source={sourceFilter} />
            : <p className="text-sm text-content-tertiary rounded-card bg-surface-2 p-4">{t('briefing_mail_legacy')}</p>}
        </div> : <>
          <div className="flex flex-wrap gap-2" role="group" aria-label={label('overview')}><button type="button" aria-pressed={!overview} onClick={() => setOverview(false)} className={`rounded-btn px-3 py-1.5 text-xs ${!overview ? 'bg-accent-soft text-accent' : 'text-content-secondary'}`}>{label('incremental')}</button><button type="button" aria-pressed={overview} onClick={() => setOverview(true)} className={`rounded-btn px-3 py-1.5 text-xs ${overview ? 'bg-accent-soft text-accent' : 'text-content-secondary'}`}>{label('overview')}</button></div>
          {!visibleItems.length && detail.items.length > 0 && <p role="status" className="text-sm text-content-tertiary">{label('no_changes')}</p>}
          {overviewError && <p role="alert" className="text-sm text-danger">{overviewError}</p>}
          {overviewLoading && <p role="status" className="text-sm text-content-tertiary">{t('briefing_loading')}</p>}
          <ItemList items={visibleItems} actions={display.actions} mail={detail.mail}
            emptyReportBody={overview && version === null ? '' : briefing.body}
            busy={busy || version !== null || overviewLoading} onDecision={onDecision} />
        </>}
      </>}
    </section>
    <RevisionGraph revisions={detail.revisions} version={version} busy={busy} onVersion={onVersion} />
  </div>
}
