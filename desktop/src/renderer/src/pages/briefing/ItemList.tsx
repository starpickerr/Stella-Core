import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { t, getLang } from '../../i18n'
import type { BriefingActionKind, BriefingActionView, BriefingDecision, BriefingItem, BriefingItemStatus } from '../../types'
import { DecisionDialog } from './DecisionDialog'
import { actionLabel as label } from './actionLabels'

const statuses: BriefingItemStatus[] = ['undo', 'done', 'follow_up', 'ignored']
const button = 'rounded-btn border border-default px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-2 disabled:opacity-50'

export const ItemList: React.FC<{
  items: BriefingItem[]
  actions?: Record<string, BriefingActionView>
  busy: boolean
  onStatus: (id: string, status: BriefingItemStatus) => void
  onDecision: (id: string, decision: BriefingDecision) => Promise<void>
}> = ({ items, actions = {}, busy, onStatus, onDecision }) => {
  const [dialog, setDialog] = useState<{ item: BriefingItem; kind: BriefingActionKind; mode: 'create' | 'link' | 'remind' } | null>(null)
  return (
  <div className="space-y-5">
    {items.length === 0 && <p className="text-sm text-content-tertiary">{t('briefing_no_items')}</p>}
    {(['needs_action', 'attention', 'status_update', 'other'] as const).map((section) => {
      const cards = items.filter((item) => (actions[item.id]?.category ?? (item.section === 'action' ? 'needs_action' : 'attention')) === section)
      if (!cards.length) return null
      return <section key={section}>
        <h3 className="text-sm font-semibold text-content mb-3">{label(section)} <span className="text-content-tertiary font-normal">{cards.length}</span></h3>
        <div className="space-y-3">
          {cards.map((item) => (
            <article key={item.id} className="rounded-card border border-default bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h4 className="text-sm font-medium text-content break-words">{item.title || item.source}</h4>
                <select value={item.status} disabled={busy} aria-label={`${item.title}: ${label('info')}`}
                  onChange={(e) => onStatus(item.id, e.target.value as BriefingItemStatus)}
                  className="shrink-0 h-7 max-w-28 px-2 rounded-btn border border-default bg-surface text-xs text-content disabled:opacity-50">
                  {statuses.map((status) => <option key={status} value={status}>{label(status === 'ignored' ? 'information_ignored' : status)}</option>)}
                </select>
              </div>
              <p className="text-xs text-content-tertiary mt-1">{item.sender} · {new Date(item.occurred_at).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US')}</p>
              <p className="mt-2 text-xs text-content-secondary">{label(actions[item.id]?.change_type ?? 'new')} · {item.score >= 90 ? 'P0' : item.score >= 70 ? 'P1' : 'P2'}{actions[item.id]?.facts.due_at ? ` · ${label('due')} ${new Date(String(actions[item.id].facts.due_at)).toLocaleString()}` : ''}</p>
              {item.snippet && <p className="text-sm text-content-secondary mt-2 line-clamp-2 break-words">{item.snippet}</p>}
              {Boolean(actions[item.id]?.facts.submission_status) && <p className="mt-2 text-xs text-content-secondary">{label('source_facts')} · {label(String(actions[item.id].facts.submission_status))}{actions[item.id].facts.score !== undefined ? ` · ${actions[item.id].facts.score}` : ''}</p>}
              <div className="mt-3 space-y-3">{(['todo', 'calendar'] as const).map((kind) => {
                const view = actions[item.id]
                const receipt = view?.[kind]
                if (kind === 'calendar' && !receipt) return null
                return <div key={kind} className="space-y-2">
                  {receipt && <p className={`text-xs ${['failed', 'conflict'].includes(receipt.state) ? 'text-danger' : 'text-content-secondary'}`}>{label(receipt.state)}{receipt.business && 'status' in receipt.business ? ` · ${label('business')}: ${label(receipt.business.status)}` : ''}</p>}
                  {receipt?.error && <p role="alert" className="text-xs text-danger break-words">{receipt.error}</p>}
                  <div className="flex flex-wrap items-center gap-2">
                    {receipt?.business ? <Link className={`${button} text-accent`} to={kind === 'todo' ? '/todos' : '/calendar'} state={kind === 'todo' ? { todoId: receipt.target_id } : { eventId: receipt.target_id }}>{label(`view_${kind}`)}</Link> : <>
                      {!['detached', 'deleted'].includes(receipt?.state ?? '') && <button type="button" disabled={busy} className={`${button} text-accent`} onClick={() => setDialog({ item, kind, mode: 'create' })}>{label(`create_${kind}`)}</button>}
                      <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind, mode: 'link' })}>{label('link')}</button>
                    </>}
                    {kind === 'todo' && receipt?.business && <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind: 'reminder', mode: 'remind' })}>{label('reminder')}</button>}
                    {receipt?.state === 'failed' && <button type="button" disabled={busy} className={button} onClick={() => void onDecision(item.id, { operation: 'retry', kind })}>{label('retry')}</button>}
                    {receipt?.state === 'conflict' && <><button type="button" disabled={busy} className={button} onClick={() => void onDecision(item.id, { operation: 'confirm_update', kind })}>{label('confirm_update')}</button><button type="button" disabled={busy} className={button} onClick={() => void onDecision(item.id, { operation: 'keep_current', kind })}>{label('keep_current')}</button></>}
                    <details><summary className="cursor-pointer text-xs text-content-secondary">{label('more')}</summary><div className="mt-2 flex flex-wrap gap-2">{(['keep', 'defer', 'ignore', ...(receipt?.business ? ['unlink'] as const : [])] as const).map((operation) => <button key={operation} type="button" disabled={busy} className={button} onClick={() => void onDecision(item.id, { operation, kind })}>{label(operation)}</button>)}{kind === 'todo' && !view?.calendar && <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind: 'calendar', mode: 'create' })}>{label('create_calendar')}</button>}</div></details>
                  </div>
                </div>
              })}</div>
              {actions[item.id]?.reminder && <p className="mt-2 text-xs text-content-secondary">{label('reminder')} · {label(actions[item.id].reminder!.state)} {actions[item.id].reminder!.error}{actions[item.id].reminder!.state === 'failed' && <button type="button" disabled={busy} className={`ml-2 ${button}`} onClick={() => void onDecision(item.id, { operation: 'retry', kind: 'reminder' })}>{label('retry')}</button>}<button type="button" disabled={busy} className={`ml-2 ${button}`} onClick={() => setDialog({ item, kind: 'reminder', mode: 'remind' })}>{label('reminder')}</button></p>}
              <details className="mt-3 text-xs text-content-secondary"><summary className="cursor-pointer">{label('details')}</summary><div className="mt-3 space-y-3">
                <p className="whitespace-pre-wrap break-words">{item.snippet}</p>
                {actions[item.id] && <><h5 className="font-medium">{label('source_facts')}</h5><dl>{Object.entries(actions[item.id].facts).filter(([key]) => !['url', 'time_origin'].includes(key)).map(([key, value]) => <div key={key} className="flex flex-wrap gap-2"><dt>{label(key)}</dt><dd className="break-all">{String(value ?? '—')}</dd></div>)}</dl><p>{label('judgment')} · {label(actions[item.id].category)} · {actions[item.id].facts.time_origin === 'ai_inference' ? label('inference') : label('source_facts')}</p>{(['todo', 'calendar', 'reminder'] as const).map((kind) => actions[item.id][kind] && <p key={kind}>{label(kind)} · {label(actions[item.id][kind]!.state)} · {actions[item.id][kind]!.result.operation}</p>)}</>}
              </div></details>
              {/^(https?:\/\/|mid:)/i.test(item.url) && <a href={item.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-3 text-xs text-accent hover:underline"><ExternalLink size={12} />{t('briefing_open')}</a>}
            </article>
          ))}
        </div>
      </section>
    })}
    {dialog && <DecisionDialog key={`${dialog.item.id}:${dialog.kind}:${dialog.mode}`} {...dialog} view={actions[dialog.item.id]} onClose={() => setDialog(null)} onDecision={(decision) => onDecision(dialog.item.id, decision)} />}
  </div>
  )
}
