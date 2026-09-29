import React, { useState } from 'react'
import { ChevronDown, ExternalLink } from 'lucide-react'
import { t, getLang } from '../../i18n'
import type { BriefingMail } from '../../types'

export const MailList: React.FC<{ mail: BriefingMail[] }> = ({ mail }) => {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const rows = [...mail].sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime() || a.id.localeCompare(b.id))
  const locale = getLang() === 'zh' ? 'zh-CN' : 'en-US'
  return <div className="space-y-2">
    {!rows.length && <p className="text-sm text-content-tertiary py-6 text-center">{t('briefing_mail_empty')}</p>}
    {rows.map((row) => {
      const expanded = expandedId === row.id
      return <article key={row.id} className={`rounded-card border bg-surface overflow-hidden ${expanded ? 'border-accent' : 'border-default'}`}>
        <button type="button" aria-expanded={expanded} aria-controls={`briefing-mail-${row.id}`} onClick={() => setExpandedId(expanded ? null : row.id)} className="w-full text-left px-4 py-3 hover:bg-surface-2 transition-colors">
          <div className="flex items-center gap-3">
            <span className="flex-1 min-w-0 text-sm font-medium text-content truncate">{row.title || t('briefing_mail_untitled')}</span>
            <span className={`shrink-0 text-[10px] ${row.category === 'selected' ? 'text-success' : 'text-content-tertiary'}`}>{t(`briefing_mail_${row.category}`)}</span>
            <ChevronDown size={14} className={`shrink-0 text-content-tertiary transition-transform ${expanded ? 'rotate-180' : ''}`} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mt-1.5 text-xs text-content-tertiary">
            <span className="truncate">{row.sender || row.sender_email}</span>
            <time dateTime={row.occurred_at} className="shrink-0 tabular-nums">{new Date(row.occurred_at).toLocaleString(locale, { hour12: false })}</time>
          </div>
        </button>
        {expanded && <div id={`briefing-mail-${row.id}`} className="border-t border-default px-4 py-4 space-y-3">
          <h4 className="text-sm font-semibold text-content break-words">{row.title || t('briefing_mail_untitled')}</h4>
          {row.sender_email && <p className="text-xs text-content-secondary break-all">{row.sender_email}</p>}
          {row.category === 'filtered' && <p className="text-xs text-content-tertiary">{t('briefing_filter_reason')}：{['exclude', 'noreply', 'list_unsubscribe'].includes(row.filter_reason) ? t(`briefing_filter_${row.filter_reason}`) : row.filter_reason}</p>}
          {!row.body_available && <p className="text-xs text-content-tertiary">{t('briefing_mail_summary_only')}</p>}
          <div className="text-sm text-content-secondary whitespace-pre-wrap break-words leading-relaxed">{row.body || row.snippet || t('briefing_mail_no_body')}</div>
          {/^(https?:\/\/|mid:)/i.test(row.url) && <a href={row.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><ExternalLink size={12} />{t('briefing_open')}</a>}
        </div>}
      </article>
    })}
  </div>
}
