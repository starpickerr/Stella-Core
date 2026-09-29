import React from 'react'
import { ArrowLeft } from 'lucide-react'
import Markdown from '../../components/Markdown'
import { ItemList } from './ItemList'
import { t, getLang } from '../../i18n'
import type { BriefingDetail as Detail, BriefingItemStatus } from '../../types'

export const BriefingDetail: React.FC<{
  detail: Detail
  busy: boolean
  onBack: () => void
  onStatus: (id: string, status: BriefingItemStatus) => void
}> = ({ detail, busy, onBack, onStatus }) => {
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
    {briefing.error_message && <div role="alert" className="rounded-card border border-danger-border bg-danger-soft text-danger text-sm p-3 break-words">{briefing.error_message}</div>}
    <div className="grid grid-cols-3 gap-3">
      {(['fetched', 'kept', 'filtered'] as const).map((key) => <div key={key} className="rounded-card bg-surface-2 p-3">
        <div className="text-xl font-semibold text-content">{briefing[`${key}_count`]}</div>
        <div className="text-xs text-content-tertiary mt-1">{t(`briefing_${key}`)}</div>
      </div>)}
    </div>
    {briefing.body && <div className="border-b border-default pb-5"><Markdown content={briefing.body} /></div>}
    <ItemList items={detail.items} busy={busy} onStatus={onStatus} />
  </div>
}
