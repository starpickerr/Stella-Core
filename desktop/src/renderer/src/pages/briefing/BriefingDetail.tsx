import React from 'react'
import { ArrowLeft } from 'lucide-react'
import Markdown from '../../components/Markdown'
import { ItemList } from './ItemList'
import { t, getLang } from '../../i18n'
import type { BriefingDetail as Detail, BriefingItemStatus } from '../../types'

export const BriefingDetail: React.FC<{
  detail: Detail
  version: number | null
  onVersion: (number: number | null) => void
  busy: boolean
  onBack: () => void
  onStatus: (id: string, status: BriefingItemStatus) => void
}> = ({ detail, version, onVersion, busy, onBack, onStatus }) => {
  const briefing = detail.briefing
  return <div className="space-y-5">
    <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-xs text-content-secondary hover:text-accent lg:hidden"><ArrowLeft size={14} />{t('briefing_back')}</button>
    <div>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-content">{getLang() === 'en' ? `${briefing.id.slice(4, 14)} · ${t('menu_briefing')}` : briefing.title || briefing.id}</h2>
        <span className={`text-xs shrink-0 ${briefing.status === 'failed' ? 'text-danger' : 'text-content-secondary'}`}>{t(`briefing_${briefing.status}`)}</span>
      </div>
      {briefing.generated_at && <p className="text-xs text-content-tertiary mt-1">{new Date(briefing.generated_at).toLocaleString()}</p>}
    </div>
    {briefing.window_start && briefing.window_end && <p className="text-xs text-content-secondary">{t('briefing_window')}：{new Date(briefing.window_start).toLocaleString()} → {new Date(briefing.window_end).toLocaleString()}</p>}
    <label className="flex flex-wrap items-center gap-2 text-sm text-content-secondary">
      {t('briefing_versions')}
      <select aria-label={t('briefing_versions')} value={version ?? 'current'} disabled={busy} onChange={(event) => onVersion(event.target.value === 'current' ? null : Number(event.target.value))} className="rounded-btn border border-default bg-surface px-2 py-1 text-xs">
        <option value="current">{t('briefing_current')}</option>
        {detail.revisions.map((row) => <option key={row.number} value={row.number}>#{row.number} · {new Date(row.created_at).toLocaleString()} · {t(row.trigger === 'scheduled' ? 'briefing_auto' : row.trigger === 'legacy' ? 'briefing_legacy' : 'briefing_manual')} · {t(`briefing_${row.status}`)}</option>)}
      </select>
    </label>
    {version !== null && <p className="text-xs text-content-tertiary">{t('briefing_readonly')}</p>}
    {briefing.error_message && <div role="alert" className="rounded-card border border-danger-border bg-danger-soft text-danger text-sm p-3 break-words">{briefing.error_message}</div>}
    <div className="grid grid-cols-3 gap-3">
      {(['fetched', 'kept', 'filtered'] as const).map((key) => <div key={key} className="rounded-card bg-surface-2 p-3">
        <div className="text-xl font-semibold text-content">{briefing[`${key}_count`]}</div>
        <div className="text-xs text-content-tertiary mt-1">{t(`briefing_${key}`)}</div>
      </div>)}
    </div>
    {briefing.body && <div className="border-b border-default pb-5"><Markdown content={briefing.body} /></div>}
    <ItemList items={detail.items} busy={busy || version !== null} onStatus={onStatus} />
  </div>
}
