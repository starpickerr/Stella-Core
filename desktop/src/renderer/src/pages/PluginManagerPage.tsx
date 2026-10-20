import React, { useCallback, useEffect, useState } from 'react'
import { Puzzle, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
import { PluginRow, pluginStateLabel } from '../plugins/managementTypes'

type Props = { baseUrl: string }
type Plan = { status: string; core?: { from: string; to: string }; updates?: { pluginId: string; fromVersion: string; toVersion: string }[]; blocked?: { pluginId: string; reason: string }[] }

export default function PluginManagerPage({ baseUrl }: Props) {
  const [rows, setRows] = useState<PluginRow[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const refresh = useCallback(async () => {
    apiClient.setBaseUrl(baseUrl)
    setLoading(true)
    try {
      const data = await apiClient.pluginRequest<{ plugins: PluginRow[] }>('runtime')
      setRows(data.plugins)
      try { setPlan(await apiClient.pluginRequest<Plan>('dual-update-plan')) }
      catch (err) { setPlan(null); setError(String(err)) }
    } catch (err) { setError(String(err)) }
    finally { setLoading(false) }
  }, [baseUrl])
  useEffect(() => { void refresh() }, [refresh])

  async function manage(row: PluginRow, action: string) {
    setBusy(row.pluginId); setError(''); setMessage('')
    try {
      await apiClient.pluginRequest('manage', { action, pluginId: row.pluginId })
      setMessage(`${row.name}：操作已完成`)
      await refresh()
    } catch (err) { setError(String(err)) }
    finally { setBusy(null) }
  }
  return <main className="h-full overflow-auto p-6 space-y-5 text-content">
    <header className="flex flex-wrap items-center gap-3">
      <Puzzle size={24} className="text-accent" />
      <div className="flex-1"><h1 className="text-xl font-semibold">插件</h1><p className="text-sm text-content-secondary">管理安装、运行状态和更新</p></div>
      <Link to="/settings?tab=plugins" className="text-sm text-accent">配置与授权</Link>
      <button type="button" disabled={loading || !!busy} onClick={() => { setError(''); void refresh() }} className="inline-flex items-center gap-2 rounded-btn bg-surface-2 px-3 py-2 text-sm disabled:opacity-50"><RefreshCw size={14} />刷新</button>
    </header>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {message && <p role="status" className="text-sm text-content-secondary">{message}</p>}
    {plan && <section className="border-y border-default py-3 text-sm space-y-1">
      <p>Core {plan.core?.from || '—'} · {plan.updates?.length ? `${plan.updates.length} 个插件可更新` : '插件已是最新版本'}</p>
      {plan.blocked?.map(item => <p key={item.pluginId} className="text-danger">{item.pluginId}：{item.reason}</p>)}
    </section>}
    {loading && <p role="status" className="text-sm text-content-secondary">正在读取已安装插件…</p>}
    {!loading && !rows.length && <p className="text-sm text-content-secondary">尚未安装插件。默认插件会在启动时从配置的目录安装；安装失败时可查看诊断日志。</p>}
    <ul className="divide-y divide-default">{rows.map(row => <li key={row.pluginId} className="py-4 flex flex-wrap items-center gap-4">
      <div className="flex-1 min-w-40"><h2 className="font-medium">{row.name} <span className="ml-2 text-sm text-content-secondary">{row.version || '版本不可读'}</span></h2>
        <p className="text-xs text-content-tertiary mt-1">{row.pluginId}</p>
        {row.error && <p className="text-sm text-danger mt-2">{row.error}</p>}
      </div>
      <span className="text-sm text-content-secondary">{pluginStateLabel[row.intent === 'enabled' ? row.state : row.intent] || row.state}</span>
      <div className="flex flex-wrap gap-2 text-sm">
        {row.intent === 'removed' ? <button className="rounded-btn bg-surface-2 px-3 py-2" disabled={!!busy} onClick={() => void manage(row, 'reinstall')}>重新安装</button> : <>
          <button className="rounded-btn bg-surface-2 px-3 py-2" disabled={!!busy || row.state === 'maintenance'} onClick={() => void manage(row, row.intent === 'enabled' ? 'disable' : 'enable')}>{row.intent === 'enabled' ? '停用' : '启用'}</button>
          {plan?.updates?.some(item => item.pluginId === row.pluginId) && <button className="rounded-btn bg-accent px-3 py-2 text-white" disabled={!!busy} onClick={() => void manage(row, 'update')}>更新</button>}
          {!row.hideUninstall && !row.firstParty && (
            <button className="rounded-btn px-3 py-2 text-content-secondary" disabled={!!busy} onClick={() => void manage(row, 'remove')}>卸载</button>
          )}
        </>}        {busy === row.pluginId && <span role="status" className="self-center text-content-secondary">处理中…</span>}
      </div>
    </li>)}</ul>
    <p className="text-xs text-content-tertiary">停用和卸载保留业务数据。插件启用后，会在首次获准调用时启动。</p>
  </main>
}
