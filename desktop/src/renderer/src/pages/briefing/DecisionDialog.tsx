import React, { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import type { BriefingActionKind, BriefingActionView, BriefingDecision, BriefingItem, CalendarEvent, Todo } from '../../types'
import { actionLabel as label } from './actionLabels'

const button = 'rounded-btn border border-default px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const input = 'mt-1 block w-full rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content'
const localInput = (value: unknown) => {
  if (typeof value !== 'string' || !value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export const DecisionDialog: React.FC<{
  item: BriefingItem; view?: BriefingActionView; kind: BriefingActionKind; mode: 'create' | 'link' | 'remind'
  onClose: () => void; onDecision: (decision: BriefingDecision) => Promise<void>
}> = ({ item, view, kind, mode, onClose, onDecision }) => {
  const dialogRef = useRef<HTMLElement>(null)
  const previousFocus = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null)
  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>('input, button')?.focus()
    return () => { previousFocus.current?.focus() }
  }, [])
  const [title, setTitle] = useState(item.title)
  const [due, setDue] = useState(localInput(view?.facts.due_at))
  const [planned, setPlanned] = useState('')
  const [parent, setParent] = useState('')
  const [remind, setRemind] = useState('')
  const [start, setStart] = useState(localInput(view?.facts.start_at))
  const [end, setEnd] = useState(localInput(view?.facts.end_at))
  const [remember, setRemember] = useState(false)
  const [query, setQuery] = useState('')
  const [targets, setTargets] = useState<(Todo | CalendarEvent)[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true)
    apiClient.getBriefingTargets(kind === 'calendar' ? 'calendar' : 'todo', query)
      .then((rows) => { if (active) setTargets(rows) })
      .catch((err) => { if (active) setError(String(err instanceof Error ? err.message : err)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [kind, query])
  const submit = async (decision: BriefingDecision) => {
    setBusy(true); setError('')
    try { await onDecision(decision); onClose() }
    catch (err) { setError(String(err instanceof Error ? err.message : err)) }
    finally { setBusy(false) }
  }
  const heading = label(mode === 'link' ? 'link' : mode === 'remind' ? 'reminder' : `create_${kind}`)
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onKeyDown={(event) => {
    if (event.key === 'Escape' && !busy) onClose()
    if (event.key !== 'Tab') return
    const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex="0"]') ?? []).filter((element) => element.offsetParent !== null)
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-label={heading} className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-card border border-default bg-surface p-5 shadow-xl">
      <h3 className="text-base font-semibold text-content">{heading}</h3>
      <p className="mt-2 text-xs text-content-secondary">{label('creation_help')}</p>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      {mode === 'link' ? <div className="mt-4 space-y-3">
        <label className="block text-sm text-content-secondary">{label(`search_${kind}`)}<input autoFocus className={input} value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        {loading ? <Loader2 className="animate-spin" size={16} /> : targets.length ? targets.map((target) => <button key={target.id} type="button" disabled={busy} className={`${button} block w-full text-left`} onClick={() => void submit({ operation: 'link', kind, target_id: target.id })}>{target.title}{'status' in target ? ` · ${label(target.status)}` : ''}</button>) : <p className="text-sm text-content-tertiary">{label('no_targets')}</p>}
        <button type="button" disabled={busy} onClick={onClose} className={button}>{label('cancel')}</button>
      </div> : <form className="mt-4 space-y-3" onSubmit={(event) => {
        event.preventDefault()
        const decision: BriefingDecision = { operation: mode, kind, remember }
        if (mode === 'create') {
          decision.title = title
          if (kind === 'todo') {
            decision.parent_id = parent || null; decision.planned_on = planned || null
            decision.due_at = due ? new Date(due).toISOString() : null
            if (remind) decision.remind_at = new Date(remind).toISOString()
          } else { decision.start_at = new Date(start).toISOString(); decision.end_at = new Date(end).toISOString() }
        } else { decision.remind_at = new Date(remind).toISOString() }
        void submit(decision)
      }}>
        {mode === 'create' && <label className="block text-sm text-content-secondary">{label('title')}<input autoFocus required className={input} value={title} onChange={(event) => setTitle(event.target.value)} /></label>}
        {mode === 'create' && kind === 'todo' && <>
          <label className="block text-sm text-content-secondary">{label('due')}<input type="datetime-local" className={input} value={due} onChange={(event) => setDue(event.target.value)} /></label>
          <label className="block text-sm text-content-secondary">{label('planned')}<input type="date" className={input} value={planned} onChange={(event) => setPlanned(event.target.value)} /></label>
          <label className="block text-sm text-content-secondary">{label('parent')}<select className={input} value={parent} onChange={(event) => setParent(event.target.value)}><option value="">{label('none')}</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.title}</option>)}</select></label>
        </>}
        {mode === 'create' && kind === 'calendar' && <>
          <label className="block text-sm text-content-secondary">{label('start')}<input required type="datetime-local" className={input} value={start} onChange={(event) => setStart(event.target.value)} /></label>
          <label className="block text-sm text-content-secondary">{label('end')}<input required type="datetime-local" className={input} value={end} onChange={(event) => setEnd(event.target.value)} /></label>
          {view?.facts.time_origin === 'ai_inference' && <p className="text-sm text-content-secondary">{label('inference')}</p>}
        </>}
        {(kind === 'todo' || kind === 'reminder') && <label className="block text-sm text-content-secondary">{label('remind')}<input required={kind === 'reminder'} type="datetime-local" className={input} value={remind} onChange={(event) => setRemind(event.target.value)} /></label>}
        {mode === 'create' && <label className="flex items-start gap-2 text-xs text-content-secondary"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />{label('remember')}</label>}
        <div className="flex justify-end gap-2 pt-2"><button type="button" disabled={busy} onClick={onClose} className={button}>{label('cancel')}</button><button type="submit" disabled={busy} className={`${button} bg-accent text-accent-contrast`}>{busy ? <Loader2 size={14} className="animate-spin" /> : label('confirm')}</button></div>
      </form>}
    </section>
  </div>
}
