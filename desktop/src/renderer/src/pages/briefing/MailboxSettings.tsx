import React, { useEffect, useState } from 'react'
import { Check, Eye, EyeOff, Loader2, Mail, Plus } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import type { BriefingMailbox, BriefingMailboxInput } from '../../types'

const fieldClass = 'h-8 px-2 rounded-btn border border-default bg-surface text-sm text-content disabled:opacity-50'
const buttonClass = 'h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50'
const emptyMailbox = { host: '', user: '', port: 993, folder: 'INBOX', password: '', enabled: true }
const passwordMask = '********'

export const MailboxSettings: React.FC = () => {
  const [mailboxes, setMailboxes] = useState<BriefingMailbox[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState({ ...emptyMailbox })
  const [passwordDirty, setPasswordDirty] = useState(false)
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [connection, setConnection] = useState<'idle' | 'testing' | 'connected'>('idle')
  const [error, setError] = useState('')
  const selected = mailboxes.find((row) => row.id === selectedId)

  const openMailbox = (row?: BriefingMailbox) => {
    setSelectedId(row?.id ?? null)
    setDraft(row ? { host: row.host, user: row.user, port: Number(row.port) || 993, folder: row.folder, password: row.password_masked, enabled: row.enabled } : { ...emptyMailbox })
    setPasswordDirty(false); setPasswordVisible(false)
    setSaved(false); setConnection('idle'); setError('')
  }

  useEffect(() => {
    let cancelled = false
    apiClient.getBriefingSettings().then((cfg) => {
      if (!cancelled) { setMailboxes(cfg.mailboxes); openMailbox(cfg.mailboxes[0]) }
    }).catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const edit = (changes: Partial<typeof draft>) => {
    setDraft((value) => ({ ...value, ...changes }))
    setSaved(false); setConnection('idle')
  }

  const payload = (): BriefingMailboxInput => ({
    host: draft.host, user: draft.user, port: draft.port, folder: draft.folder, enabled: draft.enabled,
    ...(selectedId ? { id: selectedId, action: 'save' as const } : { action: 'add' as const }),
    ...(passwordDirty && draft.password !== passwordMask ? { password: draft.password } : {}),
  })

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(''); setSaved(false)
    try {
      const { settings: cfg, mailbox: row } = await apiClient.saveBriefingSettings(payload())
      if (!row?.password_set) throw new Error(t('briefing_mail_save_failed'))
      setMailboxes(cfg.mailboxes); openMailbox(row); setSaved(true)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  const remove = async (id: string) => {
    setBusy(true); setError('')
    try {
      const cfg = await apiClient.deleteBriefingMailbox(id)
      setMailboxes(cfg.mailboxes)
      if (id === selectedId) openMailbox(cfg.mailboxes[0])
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  const testConnection = async () => {
    setBusy(true); setError(''); setConnection('testing')
    try { await apiClient.testBriefingSettings(payload()); setConnection('connected') }
    catch (err) { setConnection('idle'); setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  return <section className="rounded-card border border-default bg-surface p-5 space-y-4">
    <div className="flex items-center justify-between gap-3">
      <h3 className="flex items-center gap-2 font-semibold text-sm text-content"><Mail size={16} />{t('briefing_mailbox')}</h3>
      <button type="button" disabled={busy || loading} onClick={() => openMailbox()} className={`${buttonClass} inline-flex items-center gap-1`}><Plus size={14} />{t('briefing_add_mailbox')}</button>
    </div>
    <p className="text-sm text-content-secondary leading-relaxed">{t('briefing_mail_help')}</p>
    {error && <p role="alert" className="rounded-card p-3 bg-danger-soft text-danger text-sm">{error}</p>}
    {loading && <p className="flex items-center text-content-tertiary text-sm"><Loader2 size={16} className="animate-spin mr-2" />{t('briefing_loading')}</p>}
    <div className="space-y-2">{mailboxes.map((row) => <div key={row.id} className={`rounded-card border p-3 flex flex-wrap items-center justify-between gap-3 ${row.id === selectedId ? 'border-accent bg-accent-soft' : 'border-default'}`}>
      <div className="min-w-0">
        <p className="text-sm font-medium text-content break-all">{row.user}</p>
        <p className="text-xs text-content-tertiary mt-1 break-all">{row.host}:{row.port} · {row.folder}</p>
        <p className="text-xs text-content-tertiary mt-1">{t(row.enabled ? 'briefing_source_active' : 'briefing_source_inactive')}</p>
        {!row.configured && <p className="text-xs text-warning mt-1">{t('briefing_mail_missing')}</p>}
      </div>
      <div className="flex gap-2">
        <button type="button" disabled={busy || loading} onClick={() => openMailbox(row)} className={buttonClass}>{t('briefing_edit')}</button>
        <button type="button" disabled={busy || loading} onClick={() => void remove(row.id)} className={`${buttonClass} text-danger`}>{t('briefing_delete')}</button>
      </div>
    </div>)}</div>
    <h4 className="text-sm font-medium text-content">{t(selectedId ? 'briefing_edit_mailbox' : 'briefing_add_mailbox')}</h4>
    <form className="grid grid-cols-1 sm:grid-cols-2 gap-3" onSubmit={(e) => void save(e)}>
      <label className="text-xs text-content-secondary">{t('briefing_host')}<input required value={draft.host} disabled={busy || loading} autoComplete="off" placeholder="imap.gmail.com" className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ host: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_user')}<input required value={draft.user} disabled={busy || loading} autoComplete="username" className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ user: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_password')}<div className="relative mt-1">
        <input type={passwordVisible ? 'text' : 'password'} required={!selected?.password_set} value={draft.password} disabled={busy || loading} autoComplete="new-password" className={`${fieldClass} block w-full pr-9 font-mono`}
          onFocus={() => { if (!passwordDirty && draft.password === passwordMask) setDraft((value) => ({ ...value, password: '' })) }}
          onBlur={() => { if (!passwordDirty) setDraft((value) => ({ ...value, password: selected?.password_masked ?? '' })) }}
          onChange={(e) => { setPasswordDirty(true); edit({ password: e.target.value }) }} />
        <button type="button" disabled={busy || loading} aria-label={t(passwordVisible ? 'briefing_hide_password' : 'briefing_show_password')} onClick={() => setPasswordVisible(!passwordVisible)} className="absolute right-2 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary">{passwordVisible ? <EyeOff size={14} /> : <Eye size={14} />}</button>
      </div></label>
      <label className="text-xs text-content-secondary">{t('briefing_folder')}<input required value={draft.folder} disabled={busy || loading} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ folder: e.target.value })} /></label>
      <label className="text-xs text-content-secondary">{t('briefing_port')}<input type="number" required min={1} max={65535} value={draft.port || ''} disabled={busy || loading} className={`${fieldClass} block w-full mt-1`} onChange={(e) => edit({ port: Number(e.target.value) })} /></label>
      <label className="inline-flex items-center gap-2 text-sm text-content-secondary self-end h-8"><input type="checkbox" disabled={busy || loading} checked={draft.enabled} onChange={(e) => edit({ enabled: e.target.checked })} />{t('briefing_source_enabled')}</label>
      <div className="flex flex-wrap items-end gap-2 sm:col-span-2">
        <button type="submit" disabled={busy || loading} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{t('briefing_save')}</button>
        <button type="button" disabled={busy || loading} onClick={() => void testConnection()} className={`${buttonClass} inline-flex items-center gap-1.5`}>{connection === 'testing' && <Loader2 size={13} className="animate-spin" />}{t(connection === 'testing' ? 'briefing_mail_testing' : 'briefing_mail_test')}</button>
        {connection === 'connected' && <span role="status" className="inline-flex items-center gap-1 text-xs text-success"><Check size={13} />{t('briefing_mail_connected')}</span>}
        {saved && <span role="status" className="text-xs text-success">{t('briefing_mail_saved')}</span>}
      </div>
    </form>
  </section>
}
