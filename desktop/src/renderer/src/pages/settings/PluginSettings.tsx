import React, { useEffect, useMemo, useState } from 'react'
import { Puzzle } from 'lucide-react'

type Props = { baseUrl: string }

type PluginRow = {
  pluginId: string
  sourceLabel: string
  generation: number
  services: string[]
}

type Draft = {
  enabled: boolean
  notes: string
}

/**
 * Plugin settings: vertical plugin list + horizontal category tabs,
 * per-tab explicit save, drafts retained across tabs.
 */
export default function PluginSettings({ baseUrl }: Props) {
  const [rows, setRows] = useState<PluginRow[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<'general' | 'permissions' | 'sources'>('general')
  const [drafts, setDrafts] = useState<Record<string, Record<string, Draft>>>({})
  const [saved, setSaved] = useState<Record<string, Record<string, Draft>>>({})
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${baseUrl}/api/plugins/runtime`)
        const data = await res.json()
        const plugins = Array.isArray(data.plugins) ? data.plugins : []
        setRows(plugins)
        if (!selected && plugins[0]) setSelected(plugins[0].pluginId)
      } catch {
        setRows([])
      }
    })()
  }, [baseUrl, selected])

  const draftKey = selected || ''
  const currentDraft = useMemo(() => {
    const byTab = drafts[draftKey] || {}
    return (
      byTab[tab] ||
      saved[draftKey]?.[tab] || {
        enabled: true,
        notes: ''
      }
    )
  }, [drafts, saved, draftKey, tab])

  const updateDraft = (patch: Partial<Draft>) => {
    if (!selected) return
    setDrafts((prev) => ({
      ...prev,
      [selected]: {
        ...(prev[selected] || {}),
        [tab]: { ...currentDraft, ...patch }
      }
    }))
  }

  const saveTab = () => {
    if (!selected) return
    setSaved((prev) => ({
      ...prev,
      [selected]: {
        ...(prev[selected] || {}),
        [tab]: currentDraft
      }
    }))
    setMessage(`已保存「${tab}」标签草稿（跨标签草稿保留）`)
  }

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <aside className="w-48 flex-shrink-0 border-r border-default pr-3 space-y-1 overflow-y-auto">
        <div className="text-xs text-content-tertiary mb-2">插件</div>
        {rows.length === 0 && (
          <p className="text-sm text-content-secondary">暂无已发布插件贡献</p>
        )}
        {rows.map((row) => (
          <button
            key={row.pluginId}
            type="button"
            className={`w-full text-left px-2 py-1.5 rounded-btn text-sm flex items-center gap-2 ${
              selected === row.pluginId ? 'bg-surface-2 text-content' : 'text-content-secondary hover:bg-surface-2'
            }`}
            onClick={() => setSelected(row.pluginId)}
          >
            <Puzzle size={14} />
            <span className="truncate">{row.pluginId}</span>
          </button>
        ))}
      </aside>
      <section className="flex-1 min-w-0 flex flex-col gap-3">
        <div className="flex gap-2 border-b border-default pb-2">
          {(['general', 'permissions', 'sources'] as const).map((key) => (
            <button
              key={key}
              type="button"
              className={`px-3 h-8 rounded-btn text-sm ${
                tab === key ? 'bg-surface-2 text-content font-medium' : 'text-content-secondary'
              }`}
              onClick={() => setTab(key)}
            >
              {key === 'general' ? '常规' : key === 'permissions' ? '授权' : '来源'}
            </button>
          ))}
        </div>
        {!selected && <p className="text-sm text-content-secondary">选择左侧插件</p>}
        {selected && (
          <>
            <label className="flex items-center gap-2 text-sm text-content">
              <input
                type="checkbox"
                checked={currentDraft.enabled}
                onChange={(e) => updateDraft({ enabled: e.target.checked })}
              />
              启用（保存前不启动读取）
            </label>
            <textarea
              className="w-full min-h-[120px] rounded-btn border border-default bg-surface p-2 text-sm"
              value={currentDraft.notes}
              onChange={(e) => updateDraft({ notes: e.target.value })}
              placeholder="本标签草稿；切换标签会保留"
            />
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="h-8 px-3 rounded-btn bg-accent text-white text-sm"
                onClick={saveTab}
              >
                保存本标签
              </button>
              {message && <span className="text-xs text-content-secondary">{message}</span>}
            </div>
            {tab === 'permissions' && (
              <p className="text-xs text-content-secondary">
                Core 授权独立立即生效；批准后默认不自动选用来源。
              </p>
            )}
            {tab === 'sources' && (
              <p className="text-xs text-content-secondary">
                来源展示选用 / 授权 / 可用性三维状态；缺授权由 Core 在当前页弹窗申请。
              </p>
            )}
          </>
        )}
      </section>
    </div>
  )
}
