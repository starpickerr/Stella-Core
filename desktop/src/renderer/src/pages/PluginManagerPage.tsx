import React, { useCallback, useEffect, useState } from 'react'
import { Puzzle } from 'lucide-react'

type PluginRow = {
  pluginId: string
  sourceLabel: string
  generation: number
  services: string[]
}

type Props = { baseUrl: string }

/**
 * Host management shell for Plugin Runtime contributions.
 * Remains usable when a worker is failed/stopped (shows empty or last known).
 */
export default function PluginManagerPage({ baseUrl }: Props) {
  const [rows, setRows] = useState<PluginRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${baseUrl}/api/plugins/runtime`)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      setRows(Array.isArray(data.plugins) ? data.plugins : [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [baseUrl])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <div className="flex flex-col h-full min-h-0 p-6 gap-4 overflow-auto">
      <div className="flex items-center gap-3">
        <Puzzle className="w-6 h-6 text-accent" />
        <div>
          <h1 className="text-xl font-semibold text-primary">插件运行时</h1>
          <p className="text-sm text-secondary">统一管理已发布贡献；worker 故障时本页仍可打开。</p>
        </div>
        <button
          type="button"
          className="ml-auto px-3 py-1.5 rounded-md bg-surface-2 text-sm hover:bg-surface-3"
          onClick={() => void refresh()}
        >
          刷新
        </button>
      </div>

      {loading && <p className="text-sm text-secondary">加载中…</p>}
      {error && (
        <p className="text-sm text-danger" role="alert">
          无法读取运行时状态：{error}（管理壳仍可用）
        </p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="text-sm text-secondary">当前没有已发布的插件贡献快照。</p>
      )}
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <li
            key={`${row.pluginId}:${row.generation}`}
            className="rounded-lg border border-border px-4 py-3 bg-surface"
          >
            <div className="font-medium text-primary">{row.pluginId}</div>
            <div className="text-xs text-secondary mt-1">
              来源 {row.sourceLabel} · 代次 {row.generation}
            </div>
            {row.services?.length > 0 && (
              <div className="text-xs text-secondary mt-1">服务：{row.services.join(', ')}</div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
