import React from 'react'
import { Sun, ChevronRight } from 'lucide-react'
import { t, getLang } from '../../i18n'
import type { Briefing } from '../../types'

export const BriefingList: React.FC<{
  briefings: Briefing[]
  selectedId: string | null
  onSelect: (id: string) => void
}> = ({ briefings, selectedId, onSelect }) => (
  <div className="space-y-2">
    {briefings.length === 0 && <p className="text-sm text-content-tertiary py-12 text-center">{t('briefing_empty')}</p>}
    {briefings.map((briefing) => (
      <button key={briefing.id} type="button" onClick={() => onSelect(briefing.id)}
        aria-pressed={selectedId === briefing.id}
        className={`w-full text-left rounded-card border p-4 transition-colors ${selectedId === briefing.id ? 'border-accent bg-accent-soft' : 'border-default bg-surface hover:bg-surface-2'}`}>
        <div className="flex items-center gap-2 text-content font-medium text-sm">
          <Sun size={16} className="text-accent shrink-0" />
          <span className="flex-1 truncate">{getLang() === 'en' ? briefing.id.slice(4, 14) : (briefing.title || briefing.id.slice(4, 14))}</span>
          <ChevronRight size={14} className="text-content-tertiary" />
        </div>
        <div className="flex flex-wrap gap-2 mt-2 text-xs text-content-tertiary">
          <span className={briefing.status === 'failed' ? 'text-danger' : briefing.status === 'partial' ? 'text-warning' : ''}>{t(`briefing_${briefing.status}`)}</span>
          <span>· {briefing.kept_count} {t('briefing_kept')}</span>
          <span>· {briefing.id.slice(4, 14)}</span>
        </div>
      </button>
    ))}
  </div>
)
