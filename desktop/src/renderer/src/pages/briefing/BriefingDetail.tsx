import React, { useEffect, useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import Markdown from '../../components/Markdown'
import { MailList } from './MailList'
import { ItemList } from './ItemList'
import { RevisionGraph } from './RevisionGraph'
import { t, getLang } from '../../i18n'
import type { BriefingDetail as Detail, BriefingItemStatus } from '../../types'

export const BriefingDetail: React.FC<{
  detail: Detail
  loading: boolean
  version: number | null
  onVersion: (number: number | null) => void
  busy: boolean
  onBack: () => void
  onStatus: (id: string, status: BriefingItemStatus) => void
}> = ({ detail, loading, version, onVersion, busy, onBack, onStatus }) => {
  const briefing = detail.briefing
  const [category, setCategory] = useState<'candidate' | 'selected' | 'filtered' | null>(null)
  useEffect(() => { setCategory(null) }, [briefing.id])
  const [sourceFilter, setSourceFilter] = useState('email')
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
        {briefing.window_start && briefing.window_end && <p className="text-xs text-content-secondary leading-relaxed">{t('briefing_window')}：{new Date(briefing.window_start).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })} → {new Date(briefing.window_end).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</p>}
        {Object.keys(briefing.source_windows ?? {}).length > 1 && <details className="text-xs text-content-tertiary">
          <summary className="cursor-pointer">{t('briefing_source_windows')}</summary>
          <div className="space-y-1 mt-2">{Object.entries(briefing.source_windows).map(([id, window]) => <p key={id}>
            {window.name}：{new Date(window.start).toLocaleString()} → {new Date(window.end).toLocaleString()}
          </p>)}</div>
        </details>}
        {version !== null && <div className="rounded-card border border-default bg-surface-2 p-3">
          <p className="text-xs font-medium text-content-secondary">{t('briefing_version_snapshot')} #{version}</p>
          <p className="text-xs text-content-tertiary mt-1 leading-relaxed">{t('briefing_readonly')}</p>
        </div>}
        {briefing.error_message && <div role="alert" className="rounded-card border border-danger-border bg-danger-soft text-danger text-sm p-3 break-words">{briefing.error_message}</div>}
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
        })}
        {category ? <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-content">{sourceName(sourceFilter)} · {categoryLabel(category, sourceFilter)}</h3>
            <button type="button" onClick={() => setCategory(null)} className="text-xs text-accent hover:underline">{t('briefing_overview')}</button>
          </div>
          {briefing.mail_snapshot_available ? <MailList key={`${briefing.id}:${version ?? 'current'}:${briefing.updated_at}`} mail={visibleMail} source={sourceFilter} />
            : <p className="text-sm text-content-tertiary rounded-card bg-surface-2 p-4">{t('briefing_mail_legacy')}</p>}
        </div> : <>
          {briefing.body && <div className="border-b border-default pb-5"><Markdown content={briefing.body} /></div>}
          <ItemList items={detail.items} busy={busy || version !== null} onStatus={onStatus} />
        </>}
      </>}
    </section>
    <RevisionGraph revisions={detail.revisions} version={version} busy={busy} onVersion={onVersion} />
  </div>
}
