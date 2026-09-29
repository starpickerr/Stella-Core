import React, { useEffect, useState } from 'react'
import { BookOpen, Check, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { ElearningSettings as Config, ElearningSettingsInput } from '../../types'

const fieldClass = 'h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content disabled:opacity-50'
const buttonClass = 'h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const initial: Config = { enabled: true, configured: false, base_url: 'https://elearning.fudan.edu.cn', username: '', courses: [], account_id: '', password_set: false, password_masked: '', token_set: false }

export const ElearningSettings: React.FC = () => {
  const [config, setConfig] = useState(initial)
  const [password, setPassword] = useState('')
  const [courseText, setCourseText] = useState('')
  const [courses, setCourses] = useState<{ id: string; name: string }[]>([])
  const [projectPath, setProjectPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [connected, setConnected] = useState(false)

  const open = (cfg: Config) => {
    setConfig({ ...cfg, enabled: cfg.username ? cfg.enabled : true })
    setPassword(cfg.password_masked)
    setCourseText(cfg.courses.join('\n'))
    setSaved(false); setConnected(false); setCourses([])
  }

  useEffect(() => {
    let cancelled = false
    apiClient.getElearningSettings().then((cfg) => { if (!cancelled) open(cfg) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const chosen = courseText.split(/[\n,，]+/).map((value) => value.trim()).filter(Boolean)
  const payload = (): ElearningSettingsInput => ({ enabled: config.enabled, base_url: config.base_url,
    username: config.username, courses: chosen, ...(password && password !== '********' ? { password } : {}) })
  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setSaved(false)
    try { await operation() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const edit = (changes: Partial<Config>) => { setConfig((value) => ({ ...value, ...changes })); setSaved(false); setConnected(false) }

  return <section className="rounded-card border border-default bg-surface p-5 space-y-4">
    <div className="flex items-center justify-between gap-3">
      <h4 className="flex items-center gap-2 font-semibold text-sm text-content"><BookOpen size={16} />eLearning</h4>
      {config.username && <button type="button" disabled={busy || loading} className={`${buttonClass} text-danger`}
        onClick={() => void run(async () => { await apiClient.deleteElearningSource(); open(initial) })}>{t('briefing_delete')}</button>}
    </div>
    <p className="text-sm text-content-secondary leading-relaxed">{t('briefing_elearning_help')}</p>
    {error && <p role="alert" className="rounded-card p-3 bg-danger-soft text-danger text-sm">{error}</p>}
    {loading && <p className="flex items-center text-content-tertiary text-sm"><Loader2 size={16} className="animate-spin mr-2" />{t('briefing_loading')}</p>}
    <div className="flex flex-wrap gap-2">
      <input aria-label={t('briefing_crawler_path')} value={projectPath} disabled={busy || loading}
        placeholder={t('briefing_crawler_path')} className={`${fieldClass} flex-1 min-w-48`} onChange={(e) => setProjectPath(e.target.value)} />
      <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void run(async () => { open(await apiClient.importElearningCrawler(projectPath.trim() || undefined)); setSaved(true) })}>{t('briefing_import_crawler')}</button>
    </div>
    <form className="grid grid-cols-1 sm:grid-cols-2 gap-3" onSubmit={(event) => { event.preventDefault(); void run(async () => { open(await apiClient.saveElearningSettings(payload())); setSaved(true) }) }}>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_url')}<input required type="url" disabled={busy || loading} value={config.base_url} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ base_url: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_user')}<input required autoComplete="username" disabled={busy || loading} value={config.username} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ username: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_password')}<input type="password" autoComplete="new-password" disabled={busy || loading} value={password} className={`${fieldClass} block w-full mt-1`}
        onFocus={() => { if (password === '********') setPassword('') }} onBlur={() => { if (!password && config.password_set) setPassword('********') }}
        onChange={(e) => { setPassword(e.target.value); setSaved(false); setConnected(false) }} /></label>
      <label className="inline-flex items-center gap-2 text-sm text-content-secondary self-end h-8"><input type="checkbox" disabled={busy || loading} checked={config.enabled} onChange={(e) => edit({ enabled: e.target.checked })} />{t('briefing_source_enabled')}</label>
      <label className="text-xs text-content-secondary sm:col-span-2">{t('briefing_elearning_courses')}<textarea rows={3} disabled={busy || loading} value={courseText}
        placeholder={t('briefing_elearning_courses_help')} className="block w-full mt-1 p-2 rounded-btn border border-default bg-surface text-sm text-content resize-y"
        onChange={(e) => { setCourseText(e.target.value); setSaved(false) }} /></label>
      {!!courses.length && <div className="sm:col-span-2 space-y-2">
        <button type="button" disabled={busy} className="text-xs text-accent hover:underline" onClick={() => setCourseText(courses.map((row) => row.id).join('\n'))}>{t('briefing_all_courses')}</button>
        {courses.map((row) => <label key={row.id} className="flex items-center gap-2 text-sm text-content-secondary"><input type="checkbox" disabled={busy} checked={chosen.includes(row.id)}
          onChange={(event) => { setCourseText((event.target.checked ? [...chosen, row.id] : chosen.filter((id) => id !== row.id)).join('\n')); setSaved(false) }} />{row.name}</label>)}
      </div>}
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
        <button type="submit" disabled={busy || loading} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{t('briefing_save')}</button>
        <button type="button" disabled={busy || loading} className={`${buttonClass} inline-flex items-center gap-1.5`} onClick={() => void run(async () => { setCourses(await apiClient.testElearningSettings(payload())); setConnected(true) })}>
          {busy && <Loader2 size={13} className="animate-spin" />}{t('briefing_elearning_test')}</button>
        {connected && <span role="status" className="inline-flex items-center gap-1 text-xs text-success"><Check size={13} />{t('briefing_mail_connected')}</span>}
        {saved && <span role="status" className="text-xs text-success">{t('briefing_source_saved')}</span>}
      </div>
    </form>
  </section>
}
