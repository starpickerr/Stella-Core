import React, { useEffect, useState } from 'react'
import { BookOpen, Check, Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { ElearningSettings as Config, ElearningSettingsInput } from '../../types'

const fieldClass = 'h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content disabled:opacity-50'
const buttonClass = 'h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const initial: Config = { enabled: false, configured: false, base_url: 'https://elearning.fudan.edu.cn', username: '', courses: [], course_options: [], account_id: '', password_set: false, password_masked: '', file_sync_enabled: false, file_sync_root: '' }
const courseName = (value: string): string | null => {
  const name = value.trim().replace(/^[A-Za-z]{2,}[-_]?\d{3,}(?:[.-]\d+)*\s+/, '')
  return name && !/^\d+$/.test(name) ? name : null
}

export const ElearningSettings: React.FC = () => {
  const [config, setConfig] = useState(initial)
  const [password, setPassword] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [courses, setCourses] = useState<{ id: string; name: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [connected, setConnected] = useState(false)

  const open = (cfg: Config) => {
    setConfig(cfg)
    setPassword(cfg.password_masked)
    setChosen(cfg.courses)
    setSaved(false); setConnected(false); setCourses(cfg.course_options ?? [])
  }

  useEffect(() => {
    let cancelled = false
    apiClient.getElearningSettings().then((cfg) => { if (!cancelled) open(cfg) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const payload = (): ElearningSettingsInput => ({ enabled: config.enabled, base_url: config.base_url,
    username: config.username, courses: chosen, ...(password && password !== '********' ? { password } : {}) })
  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setSaved(false)
    try { await operation() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const edit = (changes: Partial<Config>) => {
    if (changes.username !== undefined || changes.base_url !== undefined) { setCourses([]); setChosen([]) }
    setConfig((value) => ({ ...value, ...changes })); setSaved(false); setConnected(false)
  }
  const missingNames = chosen.filter((id) => !courses.some((row) => row.id === id && courseName(row.name))).length

  return <section className="rounded-card border border-default bg-surface p-5 space-y-4">
    <div className="flex items-center justify-between gap-3">
      <h4 className="flex items-center gap-2 font-semibold text-sm text-content"><BookOpen size={16} />eLearning</h4>
      {config.username && <button type="button" disabled={busy || loading} className={`${buttonClass} text-danger`}
        onClick={() => void run(async () => { await apiClient.deleteElearningSource(); open(initial) })}>{t('briefing_delete')}</button>}
    </div>
    <p className="text-sm text-content-secondary leading-relaxed">{t('briefing_elearning_help')}</p>
    {error && <p role="alert" className="rounded-card p-3 bg-danger-soft text-danger text-sm">{error}</p>}
    {loading && <p className="flex items-center text-content-tertiary text-sm"><Loader2 size={16} className="animate-spin mr-2" />{t('briefing_loading')}</p>}
    <form className="grid grid-cols-1 sm:grid-cols-2 gap-3" onSubmit={(event) => { event.preventDefault(); void run(async () => { open(await apiClient.saveElearningSettings(payload())); setSaved(true) }) }}>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_url')}<input required type="url" disabled={busy || loading} value={config.base_url} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ base_url: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_user')}<input required autoComplete="username" disabled={busy || loading} value={config.username} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ username: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_elearning_password')}<input type="password" autoComplete="new-password" disabled={busy || loading} value={password} className={`${fieldClass} block w-full mt-1`}
        onFocus={() => { if (password === '********') setPassword('') }} onBlur={() => { if (!password && config.password_set) setPassword('********') }}
        onChange={(e) => { setPassword(e.target.value); setSaved(false); setConnected(false) }} /></label>
      <label className="inline-flex items-center gap-2 text-sm text-content-secondary self-end h-8"><input type="checkbox" disabled={busy || loading} checked={config.enabled} onChange={(e) => edit({ enabled: e.target.checked })} />{t('briefing_elearning_include_briefing')}</label>
      <fieldset className="sm:col-span-2 rounded-card border border-default p-3 space-y-3">
        <legend className="px-1 text-xs text-content-secondary">{t('briefing_elearning_courses')} · {chosen.length}</legend>
        <p className="text-xs text-content-tertiary">{t('briefing_elearning_courses_help')}</p>
        {courses.length > 0 ? <>
          <div className="flex gap-3">
            <button type="button" disabled={busy} className="text-xs text-accent hover:underline disabled:opacity-50" onClick={() => { setChosen(courses.map((row) => row.id)); setSaved(false) }}>{t('briefing_all_courses')}</button>
            <button type="button" disabled={busy} className="text-xs text-content-secondary hover:underline disabled:opacity-50" onClick={() => { setChosen([]); setSaved(false) }}>{t('briefing_clear_courses')}</button>
          </div>
          <div className="max-h-64 overflow-y-auto space-y-2">{courses.map((row) => <label key={row.id} className="flex items-start gap-2 text-sm text-content-secondary"><input type="checkbox" className="mt-1" disabled={busy} checked={chosen.includes(row.id)}
            onChange={(event) => { setChosen(event.target.checked ? [...chosen, row.id] : chosen.filter((id) => id !== row.id)); setSaved(false) }} /><span>{courseName(row.name) ?? t('briefing_elearning_unnamed_course')}</span></label>)}</div>
        </> : <>
          {connected && <p className="text-xs text-content-tertiary">{t('briefing_elearning_no_courses')}</p>}
        </>}
        {missingNames > 0 && <p className="text-xs text-content-tertiary">{t('briefing_elearning_names_pending').replace('{count}', String(missingNames))}</p>}
      </fieldset>
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
        <button type="submit" disabled={busy || loading || (config.enabled && !chosen.length)} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{t('briefing_save')}</button>
        <button type="button" disabled={busy || loading} className={`${buttonClass} inline-flex items-center gap-1.5`} onClick={() => void run(async () => {
          setConnected(false)
          const options = await apiClient.testElearningSettings(payload())
          setCourses(options)
          setChosen([...new Set(chosen.flatMap((selector) => {
            const matches = options.filter((row) => row.id === selector || (!/^\d+$/.test(selector) && row.name.toLowerCase().includes(selector.toLowerCase())))
            return matches.length === 1 ? [matches[0].id] : []
          }))])
          setConnected(true)
        })}>
          {busy && <Loader2 size={13} className="animate-spin" />}{t('briefing_elearning_test')}</button>
        {connected && <span role="status" className="inline-flex items-center gap-1 text-xs text-success"><Check size={13} />{t('briefing_elearning_connected')}</span>}
        {saved && <span role="status" className="text-xs text-success">{t('briefing_source_saved')}</span>}
      </div>
    </form>
  </section>
}
