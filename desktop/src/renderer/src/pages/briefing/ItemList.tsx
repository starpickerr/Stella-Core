import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { t, getLang } from '../../i18n'
import type { BriefingActionKind, BriefingActionView, BriefingDecision, BriefingItem } from '../../types'
import { DecisionDialog } from './DecisionDialog'
import { actionLabel as label } from './actionLabels'

const button = 'rounded-btn border border-default px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-2 disabled:opacity-50'

export const ItemList: React.FC<{
  items: BriefingItem[]
  actions?: Record<string, BriefingActionView>
  busy: boolean
  onDecision: (id: string, decision: BriefingDecision) => Promise<void>
}> = ({ items, actions = {}, busy, onDecision }) => {
  const [dialog, setDialog] = useState<{ item: BriefingItem; kind: BriefingActionKind; mode: 'create' | 'link' | 'remind' } | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [generating, setGenerating] = useState(false)
  const [batchError, setBatchError] = useState('')
  const candidates = items.filter((item) => actions[item.id]?.todo && !actions[item.id].todo?.business && !['detached', 'deleted'].includes(actions[item.id].todo?.state ?? ''))
  const candidateIds = new Set(candidates.map((item) => item.id))
  const selected = candidates.filter((item) => selectedIds.has(item.id))
  const decideSafely = (id: string, decision: BriefingDecision) => { void onDecision(id, decision).catch(() => {}) }
  const generate = async () => {
    setGenerating(true); setBatchError('')
    let failures = 0
    for (const item of selected) {
      try {
        await onDecision(item.id, { operation: 'create', kind: 'todo', title: item.title,
          due_at: typeof actions[item.id]?.facts.due_at === 'string' ? String(actions[item.id].facts.due_at) : null })
        setSelectedIds((current) => { const next = new Set(current); next.delete(item.id); return next })
      } catch { failures++ }
    }
    if (failures) setBatchError(getLang() === 'zh' ? `${failures} 项事务生成失败，请查看下方原因并重试。` : `${failures} task(s) failed. Review the errors below and retry.`)
    setGenerating(false)
  }
  return (
  <div className="space-y-5">
    {items.length === 0 && <p className="text-sm text-content-tertiary">{t('briefing_no_items')}</p>}
    {candidates.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-default bg-surface-2 px-4 py-3">
      <label className="inline-flex items-center gap-2 text-sm text-content-secondary"><input type="checkbox" aria-label={label('select_all')}
        checked={selected.length === candidates.length} disabled={busy || generating}
        onChange={(event) => setSelectedIds(event.target.checked ? new Set(candidates.map((item) => item.id)) : new Set())} />{label('select_all')}</label>
      <button type="button" disabled={busy || generating || selected.length === 0} onClick={() => void generate()}
        className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast disabled:opacity-50">{label('generate_todos')}{selected.length > 0 ? ` (${selected.length})` : ''}</button>
    </div>}
    {batchError && <p role="alert" className="text-sm text-danger">{batchError}</p>}
    {(['needs_action', 'attention', 'status_update', 'other'] as const).map((section) => {
      const cards = items.filter((item) => (actions[item.id]?.category ?? (item.section === 'action' ? 'needs_action' : 'attention')) === section)
      if (!cards.length) return null
      return <section key={section}>
        <h3 className="text-sm font-semibold text-content mb-3">{label(section)} <span className="text-content-tertiary font-normal">{cards.length}</span></h3>
        <div className="space-y-3">
          {cards.map((item) => (
            <article key={item.id} className={`rounded-card border bg-surface p-4 ${selectedIds.has(item.id) ? 'border-accent' : 'border-default'}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <input type="checkbox" aria-label={`${label('select_item')} ${item.title || item.source}`}
                    checked={candidateIds.has(item.id) && selectedIds.has(item.id)} disabled={busy || generating || !candidateIds.has(item.id)} className="mt-0.5 h-4 w-4 shrink-0"
                    onChange={(event) => setSelectedIds((current) => { const next = new Set(current); event.target.checked ? next.add(item.id) : next.delete(item.id); return next })} />
                  <h4 className="text-sm font-medium text-content break-words">{item.title || item.source}</h4>
                </div>
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
                      {kind !== 'todo' && !['detached', 'deleted'].includes(receipt?.state ?? '') && <button type="button" disabled={busy} className={`${button} text-accent`} onClick={() => setDialog({ item, kind, mode: 'create' })}>{label(`create_${kind}`)}</button>}
                      <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind, mode: 'link' })}>{label('link')}</button>
                    </>}
                    {kind === 'todo' && receipt?.business && <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind: 'reminder', mode: 'remind' })}>{label('reminder')}</button>}
                    {receipt?.state === 'failed' && <button type="button" disabled={busy} className={button} onClick={() => decideSafely(item.id, { operation: 'retry', kind })}>{label('retry')}</button>}
                    {receipt?.state === 'conflict' && <><button type="button" disabled={busy} className={button} onClick={() => decideSafely(item.id, { operation: 'confirm_update', kind })}>{label('confirm_update')}</button><button type="button" disabled={busy} className={button} onClick={() => decideSafely(item.id, { operation: 'keep_current', kind })}>{label('keep_current')}</button></>}
                    <details><summary className="cursor-pointer text-xs text-content-secondary">{label('more')}</summary><div className="mt-2 flex flex-wrap gap-2">{(['keep', 'defer', 'ignore', ...(receipt?.business ? ['unlink'] as const : [])] as const).map((operation) => <button key={operation} type="button" disabled={busy} className={button} onClick={() => decideSafely(item.id, { operation, kind })}>{label(operation)}</button>)}{kind === 'todo' && !view?.calendar && <button type="button" disabled={busy} className={button} onClick={() => setDialog({ item, kind: 'calendar', mode: 'create' })}>{label('create_calendar')}</button>}</div></details>
                  </div>
                </div>
              })}</div>
              {actions[item.id]?.reminder && <p className="mt-2 text-xs text-content-secondary">{label('reminder')} · {label(actions[item.id].reminder!.state)} {actions[item.id].reminder!.error}{actions[item.id].reminder!.state === 'failed' && <button type="button" disabled={busy} className={`ml-2 ${button}`} onClick={() => decideSafely(item.id, { operation: 'retry', kind: 'reminder' })}>{label('retry')}</button>}<button type="button" disabled={busy} className={`ml-2 ${button}`} onClick={() => setDialog({ item, kind: 'reminder', mode: 'remind' })}>{label('reminder')}</button></p>}
              <section className="mt-4 border-t border-default pt-3 text-xs text-content-secondary"><h5 className="font-medium text-content-secondary">{label('details')}</h5><div className="mt-3 space-y-3">
                <p className="whitespace-pre-wrap break-words">{item.snippet}</p>
                {actions[item.id] && <><h5 className="font-medium">{label('source_facts')}</h5><dl>{Object.entries(actions[item.id].facts).filter(([key]) => !['url', 'time_origin'].includes(key)).map(([key, value]) => <div key={key} className="flex flex-wrap gap-2"><dt>{label(key)}</dt><dd className="break-all">{String(value ?? '—')}</dd></div>)}</dl><p>{label('judgment')} · {label(actions[item.id].category)} · {actions[item.id].facts.time_origin === 'ai_inference' ? label('inference') : label('source_facts')}</p>{(['todo', 'calendar', 'reminder'] as const).map((kind) => actions[item.id][kind] && <p key={kind}>{label(kind)} · {label(actions[item.id][kind]!.state)} · {actions[item.id][kind]!.result.operation}</p>)}</>}
              </div></section>
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
