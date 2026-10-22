import React, { useState } from 'react'
import { Folder, HardDrive } from 'lucide-react'
import type { DataSnapshot, DataSourceInfo } from '../../api/dataTypes'
import { getLang } from '../../i18n'
import { c, button, input, panel, bytes } from './presentation'

export default function DataStorage({ state, busy, save }: { state: DataSnapshot; busy: boolean; save: (body: Record<string, unknown>) => Promise<boolean> }) {
  const lang = getLang() === 'zh' ? 'zh' : 'en'
  return <div className="space-y-5">
    <div><h2 className="text-lg font-semibold">{c('数据存储', 'Data storage')}</h2><p className="mt-1 text-sm text-content-secondary">{c('查看 Stella 数据的实际存储位置和保留方式', 'See where Stella stores data and how it is retained')}</p></div>
    {!!state.storage.roots?.length && <div className={`${panel} p-4 sm:p-5 space-y-4`}>{state.storage.roots.map(root => <div key={root.name.en}>
      <h3 className="text-xs font-medium">{root.name[lang]}</h3><p className="mt-1 select-all break-all font-mono text-xs text-content-secondary">{root.path}</p>
    </div>)}</div>}
    <div className={`${panel} divide-y divide-default`}>{state.storage.categories.map(row => <section key={row.id} className="p-4 sm:p-5 space-y-2">
      <div className="flex items-start gap-3"><Folder size={18} className="shrink-0 mt-0.5 text-content-secondary" /><div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-medium">{row.name[lang]}</h3><span className="shrink-0 text-xs text-content-secondary">{row.exists === false ? c('尚未创建', 'Not created yet') : bytes(row.bytes)}</span></div>
        <p className="mt-2 select-all break-all font-mono text-xs leading-relaxed text-content-secondary">{row.path}</p>
        <p className="mt-2 text-xs leading-relaxed text-content-secondary">{row.retention[lang]}</p>
        {row.actions.filter(action => ['clear_temporary', 'clear_runs'].includes(action)).map(action => <button key={action} type="button" className={`${button} mt-3`} disabled={busy}
          onClick={() => { if (window.confirm(c('仅清理此处的本地缓存，继续？', 'Clear this local cache?'))) void save({ action: 'cleanup_storage', cleanup_action: action }) }}>{action === 'clear_temporary' ? c('清理临时文件', 'Clear temporary files') : c('清理运行缓存', 'Clear run cache')}</button>)}
      </div></div>
    </section>)}</div>
    {state.sources.some(source => source.representation !== 'reference') && <details className={`${panel} p-4 sm:p-5`}>
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium"><HardDrive size={17} />{c('缓存与保留策略', 'Cache and retention policies')}</summary>
      <p className="mt-3 text-xs leading-relaxed text-content-secondary">{c('这些设置仅影响 Core 保存的来源记录。清理本地记录不会删除上游原始内容。', 'These settings affect Core source records. Clearing them does not delete upstream content.')}</p>
      {state.sources.filter(source => source.representation !== 'reference').map(source => <StoragePolicy key={`${source.id}:${source.storage}:${source.retention_days}`} source={source} busy={busy} save={save} />)}
    </details>}
  </div>
}

function StoragePolicy({ source, busy, save }: { source: DataSourceInfo; busy: boolean; save: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [storage, setStorage] = useState(source.storage)
  const [days, setDays] = useState(String(source.retention_days))
  return <form className="mt-4 border-t border-default pt-4 space-y-3" onSubmit={event => {
    event.preventDefault()
    if (storage === 'reference' && source.storage !== 'reference' && !window.confirm(c('切换为引用会移除缓存正文，继续？', 'Switching to reference removes cached content. Continue?'))) return
    void save({ action: 'source', source_id: source.id, storage, retention_days: Number(days) })
  }}><h3 className="text-sm font-medium">{source.name}</h3><div className="flex flex-wrap items-end gap-3">
    <label className="text-xs text-content-secondary">{c('存储策略', 'Storage policy')}<select aria-label={`${c('存储策略', 'Storage policy')} ${source.name}`} className={`${input} block mt-1`} value={storage} disabled={busy} onChange={event => setStorage(event.target.value as DataSourceInfo['storage'])}>
      <option value="reference">{c('引用', 'Reference')}</option><option value="cache">{c('缓存', 'Cache')}</option><option value="persistent">{c('持久化', 'Persistent')}</option></select></label>
    <label className="text-xs text-content-secondary">{c('保留天数', 'Retention days')}<input type="number" min={1} max={3650} aria-label={`${c('保留天数', 'Retention days')} ${source.name}`} className={`${input} mt-1 block w-24`} value={days} disabled={busy} onChange={event => setDays(event.target.value)} /></label>
    <button type="submit" className={button} disabled={busy}>{c('保存', 'Save')}</button>
    <button type="button" className={`${button} text-danger`} disabled={busy} onClick={() => { if (window.confirm(c('清理此来源的 Core 本地记录，保留原始内容？', 'Clear Core records while keeping upstream content?'))) void save({ action: 'cleanup', source_id: source.id, all_records: true }) }}>{c('清理本地记录', 'Clear local records')}</button>
  </div></form>
}
