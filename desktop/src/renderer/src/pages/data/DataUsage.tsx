import React, { useState } from 'react'
import { Database, GraduationCap, Mail, Plus, FileText, X } from 'lucide-react'
import type { DataSnapshot, DataSourceInfo } from '../../api/dataTypes'
import { getLang } from '../../i18n'
import { Toggle } from '../settings/primitives'
import { c, button, input, panel, sourceDescription } from './presentation'

export function SourceIcon({ source, size = 19 }: { source: DataSourceInfo; size?: number }) {
  const Icon = source.provider === 'email' ? Mail : source.provider === 'elearning' ? GraduationCap : Database
  return <Icon size={size} strokeWidth={1.7} className="shrink-0 text-content-secondary" aria-hidden="true" />
}

export default function DataUsage({ state, busy, save }: { state: DataSnapshot; busy: boolean; save: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [adding, setAdding] = useState('')
  const [selectedSource, setSelectedSource] = useState('')
  const consumers = state.usage_consumers || []
  const usages = state.usages || []
  return <div className="space-y-5">
    <div><h2 className="text-lg font-semibold">{c('数据使用', 'Data usage')}</h2><p className="mt-1 text-sm text-content-secondary">{c('配置功能使用的信息源', 'Choose the sources used by each feature')}</p></div>
    {!consumers.length && <p className={`${panel} p-5 text-sm text-content-secondary`}>{c('尚无已注册的数据消费功能。', 'No data-consuming features are registered.')}</p>}
    {consumers.map(consumer => {
      const name = consumer.name[getLang() === 'zh' ? 'zh' : 'en']
      const bindings = usages.filter(row => row.consumer_id === consumer.id)
      const chosen = bindings.filter(row => row.selected).flatMap(row => {
        const source = state.sources.find(source => source.id === row.source_id)
        return source ? [{ ...row, source }] : []
      })
      const candidates = bindings.filter(row => !row.selected).flatMap(row => {
        const source = state.sources.find(source => source.id === row.source_id)
        return source ? [source] : []
      })
      return <section key={consumer.id} data-testid={`data-consumer-${consumer.id}`} className={`${panel} p-4 sm:p-5`}>
        <div className="flex items-center justify-between gap-3 pb-1">
          <h3 className="flex items-center gap-2 font-semibold"><FileText size={19} className="text-content-secondary" />{name}</h3>
          <span className="text-xs text-content-secondary">{c(`${chosen.length} 个信息源`, `${chosen.length} sources`)}</span>
        </div>
        {!consumer.available && <p className="mt-2 text-xs text-content-secondary">{c('功能未启用，已保存的来源选择会保留。', 'The feature is disabled; saved source selections are retained.')}</p>}
        {!chosen.length && <p className="py-5 text-sm text-content-secondary">{c('尚未添加信息源', 'No sources added yet')}</p>}
        <div className="divide-y divide-default">{chosen.map(row => <div key={row.source_id} className="flex items-center gap-3 py-5">
          <SourceIcon source={row.source} />
          <div className="min-w-0 flex-1"><p className="text-sm font-medium break-words">{row.source.name}</p><p className="mt-1 text-xs text-content-secondary break-words">{sourceDescription(row.source)}</p>
            {(!row.source.available || !row.source.enabled) && <p className="mt-1 text-xs text-content-secondary">{c('来源暂不可用', 'Source currently unavailable')}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className={`hidden sm:inline-flex rounded-full px-2 py-0.5 text-xs ${row.enabled ? 'bg-accent-soft text-accent' : 'bg-surface-2 text-content-secondary'}`}>{row.enabled ? c('已启用', 'Enabled') : c('已停用', 'Disabled')}</span>
            <Toggle label={`${name}${c('使用', ' uses ')}${row.source.name}`} checked={row.enabled} disabled={busy}
              onChange={enabled => void save({ action: 'usage', consumer_id: consumer.id, source_id: row.source_id, enabled })} />
            <button type="button" aria-label={c(`移除${name}使用的${row.source.name}`, `Remove ${row.source.name} from ${name}`)} disabled={busy}
              onClick={() => void save({ action: 'usage', consumer_id: consumer.id, source_id: row.source_id, enabled: false, selected: false })}
              className="rounded-btn p-1.5 text-content-tertiary hover:text-danger hover:bg-surface-2 disabled:opacity-50"><X size={15} /></button>
          </div>
        </div>)}</div>
        {adding === consumer.id ? <form className="mt-2 flex flex-wrap gap-2" onSubmit={event => {
          event.preventDefault()
          if (selectedSource) void save({ action: 'usage', consumer_id: consumer.id, source_id: selectedSource, enabled: true }).then(ok => { if (ok) { setAdding(''); setSelectedSource('') } })
        }}>
          <select aria-label={c(`为${name}选择信息源`, `Select a source for ${name}`)} value={selectedSource} onChange={event => setSelectedSource(event.target.value)} className={`${input} flex-1`} disabled={busy}>
            <option value="">{c('选择信息源', 'Choose a source')}</option>{candidates.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
          </select><button type="submit" className={button} disabled={busy || !selectedSource}>{c('添加', 'Add')}</button>
          <button type="button" className={button} disabled={busy} onClick={() => setAdding('')}>{c('取消', 'Cancel')}</button>
        </form> : <button type="button" className="mt-2 flex w-full items-center justify-center gap-2 rounded-full border border-default py-2.5 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50"
          disabled={busy || !candidates.length} title={!candidates.length ? c('所有支持的信息源均已添加', 'All supported sources have been added') : undefined}
          onClick={() => { setAdding(consumer.id); setSelectedSource('') }}><Plus size={17} />{c('添加信息源', 'Add source')}</button>}
      </section>
    })}
    <p className="text-xs leading-relaxed text-content-secondary">{c('此处选择功能使用哪些来源。访问权限仍在安全中管理，停用关系不会删除来源数据。', 'These selections control which sources a feature uses. Access remains managed in Security; disabling a relation does not delete source data.')}</p>
  </div>
}
