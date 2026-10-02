import React, { useEffect, useState } from 'react'
import { Upload, Trash2, Heart, Loader2 } from 'lucide-react'
import apiClient, { type HealthSnapshot } from '../api/client'
import { t } from '../i18n'

const HealthPage: React.FC<{baseUrl: string}> = ({baseUrl}) => {
  const [data, setData] = useState<HealthSnapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [source, setSource] = useState('')
  const load = async () => { setData(await apiClient.getHealthData()) }
  useEffect(() => { apiClient.setBaseUrl(baseUrl); void load().catch(e => setMessage(String(e))) }, [baseUrl])
  const upload = async (file?: File) => {
    if (!file) return
    setBusy(true); setMessage('')
    try {
      const result = await apiClient.importHealth(file)
      if (result.status !== 'success') throw new Error(result.message)
      setMessage(`${t('health_added')}: ${result.added} · ${t('health_duplicates')}: ${result.duplicates}`)
      await load()
    } catch(e) { setMessage(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const remove = async (id: string) => {
    if (!window.confirm(t('health_delete_confirm'))) return
    setBusy(true)
    try { await apiClient.deleteHealthImport(id); await load() }
    catch(e) { setMessage(String(e)) }
    finally { setBusy(false) }
  }
  const sources = [...new Set(data?.summary.map(row => row.source) || [])]
  return <div className="flex-1 overflow-y-auto p-6">
    <div className="max-w-5xl mx-auto space-y-5">
      <h2 className="text-xl font-bold text-content flex items-center gap-2"><Heart size={20}/>{t('menu_health')}</h2>
      <p className="text-sm text-content-secondary">{t('health_local_desc')}</p>
      <div className="rounded-card border border-default p-4 space-y-3">
        <label className="inline-flex items-center gap-2 px-3 py-2 bg-accent text-white rounded-btn cursor-pointer">
          {busy ? <Loader2 size={16} className="animate-spin"/> : <Upload size={16}/>} {t('health_import')}
          <input type="file" accept=".xml,.zip,.csv" disabled={busy} className="hidden" onChange={e => { void upload(e.target.files?.[0]); e.target.value = '' }}/>
        </label>
        <p className="text-xs text-content-tertiary">{t('health_import_help')}</p>
        <p className="text-xs text-content-secondary select-text">CSV: type,source,device,unit,value,start,end,created</p>
        {message && <p className="text-sm text-content whitespace-pre-wrap">{message}</p>}
      </div>
      <div className="flex items-center gap-3 text-sm text-content-secondary">
        <span>{t('health_samples')}: {data?.sample_count || 0}</span>
        <select className="rounded-btn bg-surface border border-default p-2" value={source} onChange={e => setSource(e.target.value)}><option value="">{t('health_all_sources')}</option>{sources.map(s => <option key={s}>{s}</option>)}</select>
      </div>
      <p className="text-xs text-content-tertiary">{t('health_source_note')}</p>
      <div className="overflow-x-auto rounded-card border border-default">
        <table className="w-full text-xs text-content-secondary"><thead className="bg-surface-2"><tr>{['health_time','health_type','health_source','health_unit','health_value'].map(key => <th key={key} className="text-left p-3">{t(key as Parameters<typeof t>[0])}</th>)}</tr></thead>
          <tbody>{data?.summary.filter(row => !source || row.source === source).map((row,index) => <tr key={index} className="border-t border-default"><td className="p-3">{row.day}</td><td className="p-3 break-all">{['HKQuantityTypeIdentifierStepCount','HKQuantityTypeIdentifierHeartRate','HKQuantityTypeIdentifierBodyMass','HKCategoryTypeIdentifierSleepAnalysis','steps','weight','heart_rate','sleep'].includes(row.type) ? t(('health_metric_'+row.type.replace('HKQuantityTypeIdentifier','').replace('HKCategoryTypeIdentifier','')) as Parameters<typeof t>[0]) : row.type}</td><td className="p-3"><p>{row.source}</p><p className="text-content-tertiary break-all max-w-sm">{row.device}</p></td><td className="p-3">{row.sleep_hours !== undefined ? 'h' : row.unit}</td><td className="p-3">{row.sleep_hours !== undefined ? row.sleep_hours : row.type === 'HKQuantityTypeIdentifierStepCount' || row.type === 'steps' ? row.total : row.average?.toFixed(2) ?? '—'} <span className="text-content-tertiary">{row.count} {t('health_sample_suffix')}</span></td></tr>)}</tbody>
        </table>
      </div>
      <div className="rounded-card border border-default p-4 space-y-3">
        <h3 className="font-medium text-content">{t('health_imports')}</h3>
        {data?.imports.map(item => <div key={item.id} className="flex gap-3 items-center text-sm text-content-secondary"><div className="flex-1"><p>{item.filename}</p><p className="text-xs text-content-tertiary">{new Date(item.imported_at).toLocaleString()} · {item.records}</p></div><button disabled={busy} onClick={() => void remove(item.id)} title={t('health_delete')} className="p-2 text-danger"><Trash2 size={15}/></button></div>)}
      </div>
      <details className="text-xs text-content-secondary"><summary>{t('health_raw')}</summary>{data?.samples.filter(row => !source || row.source === source).map((row,i) => <p key={i} className="mt-2 select-text">{row.start} → {row.end} · {row.source} · {row.type} · {row.value} {row.unit}</p>)}</details>
    </div>
  </div>
}
export default HealthPage
