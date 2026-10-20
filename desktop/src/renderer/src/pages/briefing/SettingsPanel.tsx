import React, { useEffect, useState } from 'react'
import { ArrowLeft, Loader2, Filter } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { BriefingRule, BriefingRuleInput } from '../../types'
import { MailboxSettings } from './MailboxSettings'
import { ElearningSettings } from './ElearningSettings'
import { ActionSettings } from './ActionSettings'

const buttonClass = 'h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const emptyRule: BriefingRuleInput = { text: '', source: '*' }

export const SettingsPanel: React.FC<{ onBack?: () => void }> = ({ onBack }) => {
  const [defaultText, setDefaultText] = useState('')
  const [rules, setRules] = useState<BriefingRule[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<BriefingRuleInput>({ ...emptyRule })

  useEffect(() => {
    let cancelled = false
    apiClient.getBriefingRuleDocuments().then((cfg) => {
      if (!cancelled) {
        setRules(cfg.rules); setDefaultText(cfg.default_text); setDraft({ ...emptyRule, text: cfg.default_text })
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
      if (reset) { setEditing(null); setDraft({ ...emptyRule, text: defaultText }) }
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally { setBusy(false) }
  }

  // Embedded in settings → plugins: same vertical rhythm as General/Assistant (space-y-8).
  return <div className={onBack ? 'max-w-3xl mx-auto space-y-6' : 'space-y-8'}>
    {onBack && <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold text-content">{t('briefing_settings')}</h2>
      <button type="button" onClick={onBack} className={`inline-flex items-center gap-1.5 ${buttonClass}`}>
        <ArrowLeft size={14} />{t('briefing_back_to_briefing')}
      </button>
    </div>}
    {error && <p role="alert" className="rounded-card p-3 bg-danger-soft text-danger text-sm">{error}</p>}
    {loading && <p className="flex items-center text-content-tertiary text-sm"><Loader2 size={16} className="animate-spin mr-2" />{t('briefing_loading')}</p>}
    <section className="space-y-4" aria-label={t('briefing_source_management')}>
      <div className="px-1">
        <h3 className="text-sm font-semibold text-content">{t('briefing_source_management')}</h3>
        <p className="text-xs text-content-tertiary mt-0.5">{t('briefing_source_management_help')}</p>
      </div>
      <MailboxSettings />
      <ElearningSettings />
    </section>
    <ActionSettings />
    <section className="rounded-card border border-default bg-surface p-5 space-y-4">
      <div><h3 className="flex items-center gap-2 font-semibold text-sm text-content"><Filter size={16} />{t('briefing_rules')}</h3><p className="text-xs text-content-tertiary mt-2">{t('briefing_rules_help')}</p></div>
      <form className="space-y-3" onSubmit={(e) => {
        e.preventDefault()
        if (!busy && draft.text.trim()) void mutate(() => editing ? apiClient.updateBriefingRule(editing, draft) : apiClient.createBriefingRule(draft), true)
      }}>
        <label className="block text-xs text-content-secondary">{t('briefing_rule_document')}
          <textarea required aria-label={t('briefing_rule_document')} placeholder={t('briefing_rule_placeholder')} value={draft.text} disabled={busy || loading} rows={14}
            onChange={(e) => setDraft({ ...draft, text: e.target.value })} className="block w-full mt-2 p-3 rounded-card border border-default bg-surface text-sm text-content leading-relaxed font-mono resize-y disabled:opacity-50" />
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy || loading || !draft.text.trim()} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{t(editing ? 'briefing_save' : 'briefing_add_rule')}</button>
          {editing && <button type="button" disabled={busy} className={buttonClass} onClick={() => { setEditing(null); setDraft({ ...emptyRule, text: defaultText }) }}>{t('briefing_cancel')}</button>}
        </div>
      </form>
      {!loading && rules.length === 0 && <p className="text-sm text-content-tertiary">{t('briefing_no_rules')}</p>}
      <div className="space-y-2">{rules.map((rule) => <div key={rule.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-default pt-3">
        <div className={`min-w-0 text-sm text-content ${rule.enabled ? '' : 'opacity-50'}`}>
          <p className="whitespace-pre-wrap break-words leading-relaxed">{rule.text}</p>
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
