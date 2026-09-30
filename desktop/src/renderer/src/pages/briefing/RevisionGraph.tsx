import React from 'react'
import { t, getLang } from '../../i18n'
import type { BriefingDetail } from '../../types'

export const RevisionGraph: React.FC<{
  revisions: BriefingDetail['revisions']
  version: number | null
  busy: boolean
  onVersion: (number: number | null) => void
}> = ({ revisions, version, busy, onVersion }) => {
  const rows = [...revisions].sort((a, b) => b.number - a.number)
  const locale = getLang() === 'zh' ? 'zh-CN' : 'en-US'
  return <aside className="w-full md:w-52 md:shrink-0 md:sticky md:top-0 md:border-l border-default md:pl-5">
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-xs font-semibold text-content-secondary">{t('briefing_versions')}</h3>
      <span className="text-xs tabular-nums text-content-tertiary">{rows.length}</span>
    </div>
    <nav aria-label={t('briefing_versions')} className="max-h-64 md:max-h-[calc(100vh-14rem)] overflow-y-auto pr-1">
      <ol className="relative ml-2">
        <li className="relative pl-4 pb-3">
          <span aria-hidden="true" className="absolute left-0 top-[18px] bottom-0 w-0.5 bg-inset" />
          <button type="button" disabled={busy} onClick={() => onVersion(null)} aria-current={version === null ? 'true' : undefined}
            className={`w-full text-left rounded-card px-3 py-2.5 transition-colors disabled:opacity-50 ${version === null ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'}`}>
            <span aria-hidden="true" className={`absolute -left-[5px] top-3 h-3 w-3 rounded-full border-2 border-accent bg-accent ${version === null ? 'ring-4 ring-accent-soft' : ''}`} />
            <span className="block text-xs font-semibold">{t('briefing_current')}</span>
            <span className="block text-[11px] text-content-tertiary mt-1 leading-relaxed">{t('briefing_version_live')}</span>
          </button>
        </li>
        {rows.map((row, index) => {
          const selected = version === row.number
          const failed = row.status === 'failed'
          const date = new Date(row.created_at)
          return <li key={row.number} className="relative pl-4 pb-3">
            <span aria-hidden="true" className={`absolute left-0 top-0 w-0.5 bg-inset ${index === rows.length - 1 ? 'h-[18px]' : 'bottom-0'}`} />
            <button type="button" disabled={busy} onClick={() => onVersion(row.number)} aria-current={selected ? 'true' : undefined}
              className={`w-full text-left rounded-card px-3 py-2.5 transition-colors disabled:opacity-50 ${selected ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'}`}>
              <span aria-hidden="true" className={`absolute -left-[5px] top-3 h-3 w-3 rounded-full border-2 ${selected ? 'border-accent bg-accent ring-4 ring-accent-soft' : failed ? 'border-danger bg-surface' : row.status === 'partial' ? 'border-warning bg-surface' : 'border-accent bg-surface'}`} />
              <span className="flex items-center justify-between gap-2 text-xs font-medium tabular-nums">
                <time dateTime={row.created_at}>{date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time>
                <span className="text-[10px] text-content-tertiary">#{row.number}</span>
              </span>
              <span className="block mt-1 text-[11px] text-content-tertiary">{date.toLocaleDateString(locale, { month: 'short', day: 'numeric' })} · {t(row.trigger === 'scheduled' ? 'briefing_auto' : row.trigger === 'legacy' ? 'briefing_legacy' : 'briefing_manual')}</span>
              <span className={`block mt-1 text-[11px] ${failed ? 'text-danger' : 'text-content-tertiary'}`}>{t(`briefing_${row.status}`)}</span>
            </button>
          </li>
        })}
      </ol>
    </nav>
  </aside>
}
