import React from 'react'
import { ExternalLink } from 'lucide-react'
import { t, getLang } from '../../i18n'
import type { BriefingItem, BriefingItemStatus } from '../../types'

const statuses: BriefingItemStatus[] = ['undo', 'done', 'follow_up', 'ignored']

export const ItemList: React.FC<{
  items: BriefingItem[]
  busy: boolean
  onStatus: (id: string, status: BriefingItemStatus) => void
}> = ({ items, busy, onStatus }) => (
  <div className="space-y-5">
    {items.length === 0 && <p className="text-sm text-content-tertiary">{t('briefing_no_items')}</p>}
    {(['action', 'fyi'] as const).map((section) => {
      const cards = items.filter((item) => item.section === section)
      if (!cards.length) return null
      return <section key={section}>
        <h3 className="text-sm font-semibold text-content mb-3">{t(`briefing_${section}`)} <span className="text-content-tertiary font-normal">{cards.length}</span></h3>
        <div className="space-y-3">
          {cards.map((item) => (
            <article key={item.id} className={`rounded-card border border-default bg-surface p-4 ${item.status === 'done' || item.status === 'ignored' ? 'opacity-60' : ''}`}>
              <div className="flex items-start justify-between gap-3">
                <h4 className="text-sm font-medium text-content break-words">{item.title || item.source}</h4>
                <select value={item.status} disabled={busy} aria-label={`${item.title}: ${t('briefing_undo')}`}
                  onChange={(e) => onStatus(item.id, e.target.value as BriefingItemStatus)}
                  className="shrink-0 h-7 max-w-28 px-2 rounded-btn border border-default bg-surface text-xs text-content disabled:opacity-50">
                  {statuses.map((status) => <option key={status} value={status}>{t(`briefing_${status}`)}</option>)}
                </select>
              </div>
              <p className="text-xs text-content-tertiary mt-1">{item.sender} · {new Date(item.occurred_at).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US')}</p>
              {item.snippet && <p className="text-sm text-content-secondary mt-2 whitespace-pre-wrap break-words">{item.snippet}</p>}
              {/^(https?:\/\/|mid:)/i.test(item.url) && <a href={item.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-3 text-xs text-accent hover:underline"><ExternalLink size={12} />{t('briefing_open')}</a>}
            </article>
          ))}
        </div>
      </section>
    })}
  </div>
)
