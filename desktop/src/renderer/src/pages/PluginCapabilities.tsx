import React, { useCallback, useEffect, useState } from 'react'
import CapabilityRefreshButton from '../components/CapabilityRefreshButton'
import { Link, useLocation } from 'react-router-dom'
import { currentSettingsOrigin } from './settings/origin'
import { apiClient } from '../api/client'
import { Card, Grid } from '../components/CapabilityCards'
import { PluginRow, pluginStateLabel } from '../plugins/managementTypes'
import { t } from '../i18n'
import { Toggle } from './settings/primitives'

type Props = { baseUrl: string }

export default function PluginCapabilities({ baseUrl }: Props) {
  const location = useLocation()
  const origin = () => currentSettingsOrigin(location.pathname, location.search)
  const [rows, setRows] = useState<PluginRow[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const refresh = useCallback(async () => {
    apiClient.setBaseUrl(baseUrl)
    setLoading(true); setError('')
    try {
      const data = await apiClient.pluginRequest<{ plugins: PluginRow[] }>('runtime')
      if (!Array.isArray(data.plugins)) throw new Error('无法读取插件目录')
      setRows(data.plugins)
    } catch (err) { setError(String(err)) }
    finally { setLoading(false) }
  }, [baseUrl])
  useEffect(() => { void refresh() }, [refresh])

  async function manage(row: PluginRow, action: string) {
    if (busy || loading) return
    setBusy(row.pluginId); setError(''); setMessage('')
    try {
      await apiClient.pluginRequest('manage', { action, pluginId: row.pluginId })
      setMessage(`${row.name}：操作已完成`)
      await refresh()
    } catch (err) { setError(String(err)) }
    finally { setBusy(null) }
  }
  return <div className="space-y-3 text-content">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-content">{t('menu_plugins')}</h2>
      <div className="flex flex-wrap items-center gap-3">
        <Link state={origin()} to="/skills?tab=plugins&view=settings" className="text-sm text-accent">配置与授权</Link>
        <CapabilityRefreshButton loading={loading} disabled={!!busy} onRefresh={() => void refresh()} />
      </div>
    </header>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {message && <p role="status" className="text-sm text-content-secondary">{message}</p>}
    {loading && <p role="status" className="text-sm text-content-secondary">正在读取已安装插件…</p>}
    {!loading && !error && !rows.length && <p className="text-sm text-content-secondary">尚未安装插件。默认插件会在启动时从配置的目录安装；安装失败时可查看诊断日志。</p>}
    <Grid>{rows.map(row => <Card key={row.pluginId} label={row.name}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-words text-sm font-semibold">{row.name} <span className="ml-2 text-sm text-content-secondary">{row.version || '版本不可读'}</span></h3>
        <Toggle label={row.name} checked={row.intent === 'enabled'}
          disabled={loading || !!busy || row.intent === 'removed' || ['maintenance', 'draining'].includes(row.state)}
          onChange={enabled => void manage(row, enabled ? 'enable' : 'disable')} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-content-tertiary">
        <p className="break-all">{row.pluginId}</p>
        <span>{pluginStateLabel[row.intent === 'enabled' ? row.state : row.intent] || row.state}</span>
      </div>
      {row.error && <p className="text-sm text-danger">{row.error}</p>}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Link state={origin()} className="rounded-btn px-3 py-2 text-accent" to={`/skills?tab=plugins&view=settings&plugin=${encodeURIComponent(row.pluginId)}`}>设置</Link>
        {row.intent === 'removed' ? <button className="rounded-btn bg-surface-2 px-3 py-2" disabled={loading || !!busy} onClick={() => void manage(row, 'reinstall')}>重新安装</button> : !row.hideUninstall && !row.firstParty && (
          <button className="rounded-btn px-3 py-2 text-content-secondary" disabled={loading || !!busy} onClick={() => void manage(row, 'remove')}>卸载</button>
        )}
        {busy === row.pluginId && <span role="status" className="self-center text-content-secondary">处理中…</span>}
      </div>
    </Card>)}</Grid>
  </div>
}
