import React, { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ChevronRight, ExternalLink } from 'lucide-react'
import Markdown from '../../components/Markdown'
import { getLang, t } from '../../i18n'
import type { BriefingActionView, BriefingDecision, BriefingItem, BriefingMail } from '../../types'
import { actionLabel as label } from './actionLabels'
import { DecisionDialog } from './DecisionDialog'

const textValue = (value: unknown): string => typeof value === 'string' ? value.trim() : ''

export const ItemList: React.FC<{
  items: BriefingItem[]
  actions?: Record<string, BriefingActionView>
  mail?: BriefingMail[]
  emptyReportBody?: string
  busy: boolean
  onDecision: (id: string, decision: BriefingDecision) => Promise<void>
}> = ({ items, actions = {}, mail = [], emptyReportBody = '', busy, onDecision }) => {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [batchError, setBatchError] = useState('')
  const [linkQueue, setLinkQueue] = useState<string[]>([])
  const linkingSucceeded = useRef(false)
  const detailHeading = useRef<HTMLHeadingElement>(null)
  const rowButtons = useRef(new Map<string, HTMLButtonElement>())
  const returnFocusId = useRef<string | null>(null)
  useEffect(() => {
    if (focusedId) detailHeading.current?.focus()
    else if (returnFocusId.current) {
      rowButtons.current.get(returnFocusId.current)?.focus()
      returnFocusId.current = null
    }
  }, [focusedId])
  const focused = items.find((item) => item.id === focusedId)
  const selected = items.filter((item) => selectedIds.has(item.id))
  const eligible = selected.filter((item) => {
    const receipt = actions[item.id]?.todo
    return !receipt?.business && !['detached', 'deleted'].includes(receipt?.state ?? '') &&
      receipt?.result?.operation !== 'matching_required'
  })
  const needsLink = selected.filter((item) => {
    const receipt = actions[item.id]?.todo
    return !receipt?.business && (['detached', 'deleted'].includes(receipt?.state ?? '') ||
      receipt?.result?.operation === 'matching_required')
  })
  const actionableCount = eligible.length + needsLink.length
  const linkItem = items.find((item) => item.id === linkQueue[0])
  const allSelected = items.length > 0 && selected.length === items.length

  const toggle = (id: string, checked: boolean) => setSelectedIds((current) => {
    const next = new Set(current)
    if (checked) next.add(id)
    else next.delete(id)
    return next
  })

  const generate = async () => {
    setGenerating(true)
    setBatchError('')
    let failures = 0
    let firstError = ''
    for (const item of eligible) {
      try {
        const dueAt = actions[item.id]?.facts.due_at
        await onDecision(item.id, { operation: 'create', kind: 'todo', title: item.title,
          due_at: typeof dueAt === 'string' ? dueAt : null })
        toggle(item.id, false)
      } catch (error) {
        failures++
        if (!firstError) firstError = error instanceof Error ? error.message : String(error)
      }
    }
    if (failures) setBatchError((getLang() === 'zh' ? `${failures} 项事务未建立。` : `${failures} task(s) could not be created.`) + ` ${firstError}`)
    if (needsLink.length) setLinkQueue(needsLink.map((item) => item.id))
    setGenerating(false)
  }

  const snapshotFor = (item: BriefingItem) => mail.find((row) => row.id === item.source_item_id ||
    (row.source === item.source && row.account_id === item.account_id && row.source_id === item.source_id))

  return <section aria-label={label('summary')} className="space-y-4">
    <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-default bg-base py-3">
      <div>
        <h3 className="text-base font-semibold text-content">{label('summary')}</h3>
        <p className="mt-0.5 text-xs text-content-tertiary">{items.length} {label('report_entries')}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
          <input type="checkbox" aria-label={label('select_all')} checked={allSelected} disabled={busy || generating || !items.length}
            onChange={(event) => setSelectedIds(event.target.checked ? new Set(items.map((item) => item.id)) : new Set())} />
          {label('select_all')}
        </label>
        <button type="button" disabled={busy || generating || actionableCount === 0} onClick={() => void generate()}
          className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:bg-accent-hover disabled:opacity-50">
          {label('generate_todos')}{actionableCount > 0 ? ` (${actionableCount})` : ''}
        </button>
      </div>
    </div>
    {selected.length > 0 && actionableCount < selected.length && <p role="status" className="text-xs text-content-secondary">
      {getLang() === 'zh' ? `已选 ${selected.length} 项，其中 ${selected.length - actionableCount} 项已关联事务。` :
        `${selected.length} selected; ${selected.length - actionableCount} already have a linked task.`}
    </p>}
    {needsLink.length > 0 && <p role="status" className="text-xs text-content-secondary">
      {getLang() === 'zh' ? `${needsLink.length} 项需在建立事务时选择已有事务。` : `${needsLink.length} item(s) require choosing an existing task.`}
    </p>}
    {batchError && <p role="alert" className="text-sm text-danger">{batchError}</p>}
    {!items.length && (emptyReportBody
      ? <article className="rounded-card border border-default bg-surface p-5"><Markdown content={emptyReportBody} /></article>
      : <p className="rounded-card border border-default bg-surface p-5 text-sm text-content-tertiary">{t('briefing_no_items')}</p>)}
    {focused ? (() => {
      const snapshot = snapshotFor(focused)
      const payload = focused.payload ?? {}
      const sourceBody = [payload.body, payload.content, payload.description, snapshot?.body].map(textValue).find(Boolean) || focused.snippet
      const reason = textValue(payload._briefing_reason) || textValue(snapshot?.filter_reason)
      const report = textValue(payload._briefing_report)
      const members = Array.isArray(payload._briefing_members) ? payload._briefing_members.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object') : []
      const category = actions[focused.id]?.category ?? (focused.section === 'action' ? 'needs_action' : 'attention')
      const sourceUrl = focused.url || snapshot?.url || ''
      return <article className="rounded-card border border-default bg-surface p-5 sm:p-6">
        <button type="button" onClick={() => setFocusedId(null)} className="mb-5 inline-flex items-center gap-1 text-sm text-accent hover:underline">
          <ArrowLeft size={15} />{label('return_report')}
        </button>
        <div className="space-y-2 border-b border-default pb-5">
          <span className="text-xs font-medium text-accent">{label(category)}</span>
          <h4 ref={detailHeading} tabIndex={-1} className="text-lg font-semibold leading-snug text-content break-words">{focused.title || focused.source}</h4>
          <p className="text-xs text-content-tertiary">{focused.sender} · {new Date(focused.occurred_at).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US')}</p>
        </div>
        <div className="space-y-6 py-5">
          <section aria-label={label('item_content')}>
            <h5 className="mb-2 text-sm font-semibold text-content">{label('item_content')}</h5>
            {report ? <Markdown content={report} /> : <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-content-secondary">{sourceBody || label('content_unavailable')}</p>}
          </section>
          <section aria-label={label('judgment_reason')} className="border-t border-default pt-5">
            <h5 className="mb-2 text-sm font-semibold text-content">{label('judgment_reason')}</h5>
            {members.length > 1 ? members.map((member, index) => <div key={index} className="mb-3 text-sm text-content-secondary">
              <p className="font-medium text-content">{textValue(member.title) || focused.title}</p>
              <p>{textValue(member.reason) || label('reason_unavailable')}</p>
            </div>) : <p className="text-sm leading-relaxed text-content-secondary">{reason || label('reason_unavailable')}</p>}
            <p className="mt-2 text-xs text-content-tertiary">{label('judgment')}：{label(category)}</p>
          </section>
          {(report || members.length > 1) && <section aria-label={label('source_content')} className="border-t border-default pt-5">
            <h5 className="mb-2 text-sm font-semibold text-content">{label('source_content')}</h5>
            {(members.length ? members : [{ title: focused.title, body: sourceBody, url: sourceUrl }]).map((member, index) => {
              const url = textValue(member.url) || (members.length === 1 ? sourceUrl : '')
              return <div key={index} className="mb-4 last:mb-0">
                {members.length > 1 && <p className="mb-1 text-sm font-medium text-content">{textValue(member.title)}</p>}
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-content-secondary">{textValue(member.body) || label('content_unavailable')}</p>
                {/^(https?:\/\/|mid:)/i.test(url) && <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"><ExternalLink size={15} />{t('briefing_open')}</a>}
              </div>
            })}
          </section>}
        </div>
        {!report && members.length <= 1 && /^(https?:\/\/|mid:)/i.test(sourceUrl) &&
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"><ExternalLink size={15} />{t('briefing_open')}</a>}
        {!members.some((member) => /^(https?:\/\/|mid:)/i.test(textValue(member.url))) && !/^(https?:\/\/|mid:)/i.test(sourceUrl) &&
          <p className="text-xs text-content-tertiary">{label('no_source_link')}</p>}
      </article>
    })() : items.length > 0 && <div className="overflow-hidden rounded-card border border-default bg-surface divide-y divide-default">
      {items.map((item) => {
        const view = actions[item.id]
        return <div key={item.id} className={`flex items-start gap-3 px-4 py-4 transition-colors hover:bg-surface-2 ${selectedIds.has(item.id) ? 'bg-accent-soft' : ''}`}>
          <input type="checkbox" aria-label={`${label('select_item')} ${item.title || item.source}`}
            checked={selectedIds.has(item.id)} disabled={busy || generating} className="mt-1 h-4 w-4 shrink-0 cursor-pointer"
            onChange={(event) => toggle(item.id, event.target.checked)} />
          <button type="button" ref={(node) => { if (node) rowButtons.current.set(item.id, node); else rowButtons.current.delete(item.id) }}
            aria-label={`${label('view_item')} ${item.title || item.source}`} onClick={() => { returnFocusId.current = item.id; setFocusedId(item.id) }}
            className="group flex min-w-0 flex-1 items-start justify-between gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            <span className="min-w-0 space-y-1.5">
              {view?.todo?.business ? <span className="block text-xs font-medium text-accent">{label('unresolved' in view.todo.business ? view.todo.business.access === 'denied' ? 'linked_task_denied' : 'linked_task_unavailable' : 'linked_task')}</span> : null}
              <span className="block text-sm font-medium leading-snug text-content break-words group-hover:text-accent">{item.title || item.source}</span>
              <span className="block text-sm text-content-secondary line-clamp-2 break-words">{item.snippet}</span>
              <span className="block text-xs text-content-tertiary">{item.sender} · {new Date(item.occurred_at).toLocaleString(getLang() === 'zh' ? 'zh-CN' : 'en-US')}</span>
            </span>
            <ChevronRight size={17} className="mt-5 shrink-0 text-content-tertiary group-hover:text-accent" />
          </button>
        </div>
      })}
    </div>}
    {linkItem && <DecisionDialog key={linkItem.id} item={linkItem} view={actions[linkItem.id]} kind="todo" mode="link"
      onClose={() => { setLinkQueue((current) => linkingSucceeded.current ? current.slice(1) : []); linkingSucceeded.current = false }}
      onDecision={async (decision) => { await onDecision(linkItem.id, decision); toggle(linkItem.id, false); linkingSucceeded.current = true }} />}
  </section>
}
