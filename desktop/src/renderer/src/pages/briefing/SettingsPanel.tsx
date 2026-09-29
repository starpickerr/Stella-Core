import React, { useEffect, useState } from 'react'
import { Loader2, CalendarClock, Filter } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { BriefingRule, BriefingRuleInput } from '../../types'
import { MailboxSettings } from './MailboxSettings'

const fieldClass = 'h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content disabled:opacity-50'
const buttonClass = 'h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const emptyRule: BriefingRuleInput = { action: 'exclude', match_field: 'sender_domain', match_op: 'eq', match_value: '', source: 'email' }
const fields: BriefingRule['match_field'][] = ['sender', 'sender_email', 'sender_domain', 'title', 'list_id']

export const SettingsPanel: React.FC = () => {
  const [rules, setRules] = useState<BriefingRule[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<BriefingRuleInput>({ ...emptyRule })

  useEffect(() => {
    let cancelled = false
    apiClient.getBriefingRules().then((rows) => {
      if (!cancelled) {
        setRules(rows)
      }
    }).catch((err) => { if (!cancelled) setError(String(err instanceof Error ? err.message : err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const mutate = async (operation: () => Promise<unknown>, reset = false) => {
    setBusy(true)
    setError('')
    try {
      await operation()
      setRules(await apiClient.getBriefingRules())
      if (reset) { setEditing(null); setDraft({ ...emptyRule }) }
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally { setBusy(false) }
  }

  return <div className="max-w-3xl mx-auto space-y-6">
    <h2 className="text-lg font-semibold text-content">{t('briefing_settings')}</h2>
    {error && <p role="alert" className="rounded-card p-3 bg-danger-soft text-danger text-sm">{error}</p>}
    {loading && <p className="flex items-center text-content-tertiary text-sm"><Loader2 size={16} className="animate-spin mr-2" />{t('briefing_loading')}</p>}
    <MailboxSettings />
    <section className="rounded-card border border-default bg-surface p-5 space-y-3">
      <h3 className="flex items-center gap-2 font-semibold text-sm text-content"><CalendarClock size={16} />{t('briefing_schedule')}</h3>
      <p className="text-sm text-content-secondary leading-relaxed">{t('briefing_schedule_help')}</p>
    </section>
    <section className="rounded-card border border-default bg-surface p-5 space-y-4">
      <div><h3 className="flex items-center gap-2 font-semibold text-sm text-content"><Filter size={16} />{t('briefing_rules')}</h3><p className="text-xs text-content-tertiary mt-2">{t('briefing_rules_help')}</p></div>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => {
        e.preventDefault()
        if (!busy && draft.match_value.trim()) void mutate(() => editing ? apiClient.updateBriefingRule(editing, draft) : apiClient.createBriefingRule(draft), true)
      }}>
        <select aria-label={t('briefing_include')} className={fieldClass} disabled={busy} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value as BriefingRule['action'] })}>
          <option value="exclude">{t('briefing_exclude')}</option><option value="include">{t('briefing_include')}</option>
        </select>
        <select aria-label={t('briefing_rules')} className={fieldClass} disabled={busy} value={draft.match_field} onChange={(e) => setDraft({ ...draft, match_field: e.target.value as BriefingRule['match_field'] })}>
          {fields.map((field) => <option key={field} value={field}>{t(`briefing_${field}`)}</option>)}
        </select>
        <select aria-label={t('briefing_eq')} className={fieldClass} disabled={busy} value={draft.match_op} onChange={(e) => setDraft({ ...draft, match_op: e.target.value as BriefingRule['match_op'] })}>
          <option value="eq">{t('briefing_eq')}</option><option value="contains">{t('briefing_contains')}</option>
        </select>
        <input required aria-label={t('briefing_match_value')} placeholder={t('briefing_match_value')} value={draft.match_value} disabled={busy}
          onChange={(e) => setDraft({ ...draft, match_value: e.target.value })} className={`${fieldClass} flex-1 min-w-40`} />
        <button type="submit" disabled={busy || !draft.match_value.trim()} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{t(editing ? 'briefing_save' : 'briefing_add_rule')}</button>
        {editing && <button type="button" disabled={busy} className={buttonClass} onClick={() => { setEditing(null); setDraft({ ...emptyRule }) }}>{t('briefing_cancel')}</button>}
      </form>
      {!loading && rules.length === 0 && <p className="text-sm text-content-tertiary">{t('briefing_no_rules')}</p>}
      <div className="space-y-2">{rules.map((rule) => <div key={rule.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-default pt-3">
        <div className={`min-w-0 text-sm text-content ${rule.enabled ? '' : 'opacity-50'}`}>
          <span className="text-content-tertiary">{t(`briefing_${rule.action}`)} · {t(`briefing_${rule.match_field}`)} · {t(`briefing_${rule.match_op}`)}</span>
          <p className="break-all mt-1">{rule.match_value}</p>
        </div>
        <div className="flex gap-2">
          <button type="button" disabled={busy} className={buttonClass} onClick={() => { setEditing(rule.id); setDraft({ ...rule }) }}>{t('briefing_edit')}</button>
          <button type="button" disabled={busy} className={buttonClass} onClick={() => void mutate(() => apiClient.updateBriefingRule(rule.id, { enabled: !rule.enabled }))}>{t(rule.enabled ? 'briefing_disable' : 'briefing_enable')}</button>
          <button type="button" disabled={busy} className={`${buttonClass} text-danger`} onClick={() => void mutate(() => apiClient.deleteBriefingRule(rule.id), editing === rule.id)}>{t('briefing_delete')}</button>
        </div>
      </div>)}</div>
    </section>
  </div>
}
