import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import { Group, Row } from './primitives'

type UpdatePlan = {
  updates: { pluginId: string; fromVersion: string; toVersion: string }[]
  blocked: { pluginId: string; reason: string }[]
}

export default function PluginUpdates({ baseUrl }: { baseUrl: string }) {
  const [plan, setPlan] = useState<UpdatePlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const check = useCallback(async () => {
    apiClient.setBaseUrl(baseUrl)
    setLoading(true)
    setError('')
    setPlan(null)
    try {
      const data = await apiClient.pluginRequest<UpdatePlan>('dual-update-plan')
      if (!Array.isArray(data.updates) || !Array.isArray(data.blocked)) throw new Error(t('settings_plugins_invalid_plan'))
      setPlan(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setLoading(false) }
  }, [baseUrl])
  useEffect(() => { void check() }, [check])

  const update = async (pluginId: string) => {
    setBusy(pluginId)
    setError('')
    setMessage('')
    try {
      await apiClient.pluginRequest('manage', { action: 'update', pluginId })
      setMessage(`${pluginId} · ${t('settings_plugins_updated')}`)
      await check()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  return <Group title="Plugins">
    <Row label={t('settings_plugins_updates')} hint={t('settings_plugins_update_hint')}
      control={<button type="button" disabled={loading || !!busy} onClick={() => { setMessage(''); void check() }}
        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn border border-strong text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-60">
        {loading && <Loader2 size={13} className="animate-spin" />}{t('settings_plugins_check')}
      </button>} />
    {error && <p role="alert" className="px-4 py-3 text-sm text-danger">{error}</p>}
    {message && <p role="status" className="px-4 py-3 text-sm text-content-secondary">{message}</p>}
    {loading && <p role="status" className="px-4 py-3 text-sm text-content-tertiary">{t('update_checking')}</p>}
    {plan && !plan.updates.length && !plan.blocked.length && <p className="px-4 py-3 text-sm text-content-tertiary">{t('settings_plugins_latest')}</p>}
    {plan?.updates.map(item => {
      const blocked = plan.blocked.find(entry => entry.pluginId === item.pluginId)
      return <Row key={item.pluginId} label={item.pluginId}
        hint={<><span>{item.fromVersion} → {item.toVersion}</span>{blocked && <span className="block mt-1 text-danger">{blocked.reason}</span>}</>}
        control={<button type="button" aria-label={`${t('settings_plugins_update')} ${item.pluginId}`}
          disabled={loading || !!busy || !!blocked} onClick={() => void update(item.pluginId)}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm font-medium hover:bg-accent-hover disabled:opacity-50">
          {busy === item.pluginId && <Loader2 size={13} className="animate-spin" />}{busy === item.pluginId ? t('settings_plugins_updating') : t('settings_plugins_update')}
        </button>} />
    })}
    {plan?.blocked.filter(item => !plan.updates.some(update => update.pluginId === item.pluginId)).map(item =>
      <Row key={item.pluginId} label={item.pluginId} hint={<span className="text-danger">{item.reason}</span>} />)}
  </Group>
}
