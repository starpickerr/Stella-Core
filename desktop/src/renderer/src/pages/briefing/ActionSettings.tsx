import React, { useEffect, useState } from 'react'
import apiClient from '../../api/client'
import { getLang } from '../../i18n'
import type { BriefingAuthorization, BriefingPreferences, BriefingSource } from '../../types'
import { actionLabel as label } from './actionLabels'

const button = 'rounded-btn border border-default px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const input = 'mt-1 block w-full rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content'
const initialPreferences: BriefingPreferences = { show_low_priority: true, show_ongoing: true, important_types: [], reminder_frequency: 'daily', summary_detail: 'brief' }

export const ActionSettings: React.FC = () => {
  const zh = getLang() === 'zh'
  const [preferences, setPreferences] = useState(initialPreferences)
  const [rules, setRules] = useState<BriefingAuthorization[]>([])
  const [sources, setSources] = useState<BriefingSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [rule, setRule] = useState({ information_type: 'assignment', course_id: '', kind: 'todo' as BriefingAuthorization['kind'], mode: 'suggest' as BriefingAuthorization['mode'], reminder_minutes: 1440 })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const copy = (chinese: string, english: string) => zh ? chinese : english
  useEffect(() => {
    let active = true
    Promise.all([apiClient.getBriefingPreferences(), apiClient.getBriefingAuthorizations(), apiClient.getBriefingSources()])
      .then(([settings, authorizations, available]) => { if (active) { setPreferences(settings); setRules(authorizations); setSources(available); setSourceId(available[0]?.id ?? '') } })
      .catch((err) => { if (active) setError(String(err instanceof Error ? err.message : err)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  const mutate = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('')
    try { await operation() } catch (err) { setError(String(err instanceof Error ? err.message : err)) }
    finally { setBusy(false) }
  }
  return <section className="space-y-4 rounded-card border border-default bg-surface p-5">
    <h3 className="text-sm font-semibold text-content">{copy('信息处理与自动操作授权', 'Information handling and authorization')}</h3>
    <p className="text-xs text-content-secondary">{label('preference_help')}</p>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {message && <p role="status" className="text-sm text-accent">{message}</p>}
    {loading ? <p role="status" className="text-sm text-content-tertiary">{copy('正在加载…', 'Loading…')}</p> : <>
      <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void mutate(async () => { setPreferences(await apiClient.saveBriefingPreferences(preferences)); setMessage(copy('偏好已保存', 'Preferences saved')) }) }}>
        <label className="flex items-center gap-2 text-sm text-content-secondary"><input type="checkbox" checked={preferences.show_low_priority} onChange={(event) => setPreferences({ ...preferences, show_low_priority: event.target.checked })} />{copy('显示低优先级动态', 'Show low priority updates')}</label>
        <label className="flex items-center gap-2 text-sm text-content-secondary"><input type="checkbox" checked={preferences.show_ongoing} onChange={(event) => setPreferences({ ...preferences, show_ongoing: event.target.checked })} />{copy('显示持续关注事项', 'Show ongoing items')}</label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-content-secondary">{copy('关注频率', 'Follow-up frequency')}<select className={input} value={preferences.reminder_frequency} onChange={(event) => setPreferences({ ...preferences, reminder_frequency: event.target.value as BriefingPreferences['reminder_frequency'] })}><option value="daily">{copy('每日关注未解决事项', 'Daily unresolved items')}</option><option value="changes">{copy('仅有变化时', 'Changes only')}</option><option value="deadline">{copy('变化或临近截止', 'Changes or deadline approaching')}</option></select></label>
        </div>
        <label className="block text-xs text-content-secondary">{copy('优先关注的信息类型（逗号分隔）', 'Important information types (comma separated)')}<input className={input} value={preferences.important_types.join(',')} onChange={(event) => setPreferences({ ...preferences, important_types: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) })} /></label>
        <button type="submit" disabled={busy} className={button}>{copy('保存显示偏好', 'Save display preferences')}</button>
      </form>
      <form className="space-y-3 border-t border-default pt-4" onSubmit={(event) => {
        event.preventDefault()
        const source = sources.find((row) => row.id === sourceId)
        if (!source) return
        void mutate(async () => { await apiClient.saveBriefingAuthorization({ ...rule, source: source.source, account_id: source.account_id }); setRules(await apiClient.getBriefingAuthorizations()) })
      }}>
        <h4 className="text-sm font-medium text-content">{copy('来源处理规则', 'Source handling rules')}</h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-content-secondary">{copy('授权来源', 'Authorized source')}<select required className={input} value={sourceId} onChange={(event) => setSourceId(event.target.value)}>{sources.map((source) => <option key={source.id} value={source.id}>{source.name} · {source.account_id}</option>)}</select></label>
          <label className="text-xs text-content-secondary">{copy('信息类型', 'Information type')}<select aria-label={copy('信息类型', 'Information type')} className={input} value={rule.information_type} onChange={(event) => setRule({ ...rule, information_type: event.target.value })}>{['assignment', 'grade', 'meeting', 'material', 'file', 'competition', 'announcement', 'action', 'information'].map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
          <label className="text-xs text-content-secondary">{copy('课程范围', 'Course scope')}<input className={input} placeholder={copy('留空表示此账号的同类信息', 'Empty means this type in this account')} value={rule.course_id} onChange={(event) => setRule({ ...rule, course_id: event.target.value })} /></label>
          <label className="text-xs text-content-secondary">{copy('授权操作', 'Authorized operation')}<select className={input} value={rule.kind} onChange={(event) => { const kind = event.target.value as BriefingAuthorization['kind']; setRule({ ...rule, kind, mode: kind === 'todo' ? 'suggest' : rule.mode }) }}><option value="todo">{label('create_todo')}</option><option value="calendar">{label('create_calendar')}</option><option value="sync">{copy('同步已关联对象的外部事实', 'Sync external facts on linked objects')}</option><option value="reminder">{label('reminder')}</option></select></label>
          <label className="text-xs text-content-secondary">{copy('处理方式', 'Handling')}<select className={input} value={rule.mode} onChange={(event) => setRule({ ...rule, mode: event.target.value as BriefingAuthorization['mode'] })}><option value="suggest">{copy('建议，等待确认', 'Suggest and confirm')}</option>{rule.kind !== 'todo' && <option value="auto">{copy('授权自动执行', 'Authorize automatically')}</option>}<option value="briefing_only">{label('keep')}</option></select></label>
        </div>
        {rule.kind === 'reminder' && <label className="block text-xs text-content-secondary">{copy('提前提醒的分钟数', 'Minutes before deadline')}<input required type="number" min={1} max={43200} className={input} value={rule.reminder_minutes} onChange={(event) => setRule({ ...rule, reminder_minutes: Number(event.target.value) })} /></label>}
        <button type="submit" disabled={busy || !sources.length} className={button}>{copy('保存授权规则', 'Save authorization rule')}</button>
      </form>
      <div className="space-y-2">{rules.map((saved) => <div key={saved.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-default pt-3 text-xs text-content-secondary"><span className="break-all">{saved.source} · {saved.account_id} · {saved.information_type} · {saved.course_id || copy('全部课程', 'All courses')} · {label(saved.kind)} · {saved.kind === 'todo' ? copy('手动生成', 'Manual generation') : saved.mode}</span><button type="button" disabled={busy} className={button} onClick={() => void mutate(async () => { await apiClient.deleteBriefingAuthorization(saved.id); setRules(await apiClient.getBriefingAuthorizations()) })}>{copy('撤销', 'Revoke')}</button></div>)}</div>
    </>}
  </section>
}
