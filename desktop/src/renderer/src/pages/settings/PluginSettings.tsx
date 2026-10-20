import React, { useEffect, useRef, useState } from 'react'
import { apiClient } from '../../api/client'
import { Grant, Method, PluginRow, SettingsDescriptor, SettingsField, SettingsSnapshot } from '../../plugins/managementTypes'
import { Dropdown, Group, Row, SaveRow, TextInput, Toggle } from './primitives'

type Draft = { snapshot: SettingsSnapshot; values: Record<string, unknown>; conflict?: boolean }
type Request = { requestId: string; consumerPluginId: string; capability: string; purpose: string; resources: {kind: string; id: string}[]; methods: string[] }
const input = 'w-full rounded-btn border border-default bg-surface px-3 py-2 text-sm'
const button = 'rounded-btn bg-surface-2 px-3 py-2 text-sm disabled:opacity-50'

function fieldControl(
  field: SettingsField,
  draft: Draft | undefined,
  busy: boolean,
  edit: (name: string, value: unknown) => void,
) {
  const disabled = !draft || busy
  const raw = draft?.values[field.key]
  const enumValues = field.validation?.enum
  const useEnum = field.type === 'enum' || (field.type === 'string' && Array.isArray(enumValues) && enumValues.length > 0)
  if (field.secret) {
    return <p className="text-sm text-content-secondary">请通过插件的安全连接页面更新凭据</p>
  }
  if (field.type === 'boolean') {
    return (
      <Toggle
        checked={!!raw}
        disabled={disabled}
        label={field.title}
        onChange={(checked) => edit(field.key, checked)}
      />
    )
  }
  if (useEnum && enumValues) {
    const options = enumValues.map((value) => {
      const key = String(value)
      return { value: key, label: (field.enumLabels?.[key] ?? key) || '（空）' }
    })
    return (
      <div className="w-72 max-w-full">
        <Dropdown
          value={String(raw ?? '')}
          disabled={disabled}
          options={options}
          onChange={(next) => {
            const matched = enumValues.find((value) => String(value) === next)
            edit(field.key, matched)
          }}
        />
      </div>
    )
  }
  return (
    <div className="w-full max-w-xl">
      <TextInput
        disabled={disabled}
        type={['integer', 'number'].includes(field.type) ? 'number' : 'text'}
        placeholder={field.placeholder || ''}
        value={String(raw ?? '')}
        onChange={(e) => edit(field.key, ['integer', 'number'].includes(field.type) ? Number(e.target.value) : e.target.value)}
      />
    </div>
  )
}

export default function PluginSettings({ baseUrl }: { baseUrl: string }) {
  const [rows, setRows] = useState<PluginRow[]>([])
  const [selected, setSelected] = useState('')
  const [descriptors, setDescriptors] = useState<SettingsDescriptor[]>([])
  const [tab, setTab] = useState('permissions')
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [methods, setMethods] = useState<Method[]>([])
  const [grants, setGrants] = useState<Grant[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [capability, setCapability] = useState('')
  const [consumer, setConsumer] = useState('')
  const [purpose, setPurpose] = useState('interactive')
  const [resourceKind, setResourceKind] = useState('user')
  const [resourceIds, setResourceIds] = useState('')
  const [request, setRequest] = useState<Request | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const row = rows.find(item => item.pluginId === selected)
  const available = row?.intent === 'enabled' && !['maintenance', 'failed'].includes(row.state)
  const categories = descriptors.flatMap(descriptor => descriptor.categories.map(category => ({ ...category, descriptor })))
  const category = categories.find(item => `${item.descriptor.id}/${item.id}` === tab)
  const key = `${selected}/${tab}`
  const draft = drafts[key]
  const fields = category?.descriptor.fields.filter(field => field.category === category.id) || []

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let cancelled = false
    void apiClient.pluginRequest<{plugins: PluginRow[]}>('runtime').then(data => {
      if (!cancelled) { setRows(data.plugins); setSelected(value => value || data.plugins[0]?.pluginId || '') }
    }).catch(err => { if (!cancelled) setError(String(err)) })
    return () => { cancelled = true }
  }, [baseUrl])
  useEffect(() => {
    if (!selected) return
    let cancelled = false
    setDescriptors([]); setMethods([]); setGrants([]); setError(''); setMessage(''); setConsumer(selected); setResourceKind('user')
    void apiClient.pluginRequest<SettingsDescriptor[]>('settings', {action: 'describe', pluginId: selected})
      .then(result => { if (!cancelled) setDescriptors(result) }).catch(err => { if (!cancelled) setError(String(err)) })
    void apiClient.pluginRequest<Grant[]>('authorization', {action: 'list', pluginId: selected})
      .then(result => { if (!cancelled) setGrants(result) }).catch(err => { if (!cancelled) setError(String(err)) })
    if (available) void apiClient.pluginRequest<{methods: Method[]}[]>('authorization', {action: 'describe', pluginId: selected})
      .then(services => { if (!cancelled) { const all = services.flatMap(service => service.methods); setMethods(all); setCapability(all[0]?.permissions[0] || '') } })
      .catch(err => { if (!cancelled) setError(String(err)) })
    return () => { cancelled = true }
  }, [selected, available])
  useEffect(() => {
    if (!category || draft) return
    let cancelled = false
    void apiClient.pluginRequest<SettingsSnapshot>('settings', {action: 'read', pluginId: selected, settingsId: category.descriptor.id, category: category.id})
      .then(snapshot => { if (!cancelled) setDrafts(previous => previous[key] ? previous : {...previous, [key]: {snapshot, values: snapshot.values}}) })
      .catch(err => { if (!cancelled) setError(String(err)) })
    return () => { cancelled = true }
  }, [selected, category?.id, category?.descriptor.id, draft, key])
  useEffect(() => { if (request) dialog.current?.showModal() }, [request])

  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work() } catch (err) { setError(String(err)) } finally { setBusy(false) }
  }
  async function reloadGrants() { setGrants(await apiClient.pluginRequest<Grant[]>('authorization', {action: 'list', pluginId: selected})) }
  async function save() {
    if (!category || !draft) return
    await action(async () => {
      const changes = Object.fromEntries(Object.entries(draft.values).filter(([name, value]) => JSON.stringify(value) !== JSON.stringify(draft.snapshot.values[name])))
      if (!Object.keys(changes).length) { setMessage('本类别没有未保存的修改'); return }
      try {
        const snapshot = await apiClient.pluginRequest<SettingsSnapshot>('settings', {action: 'save', pluginId: selected, settingsId: category.descriptor.id, category: category.id, expectedRevision: draft.snapshot.revision, changes})
        setDrafts(previous => ({...previous, [key]: {snapshot, values: snapshot.values}})); setMessage('本类别已保存')
      } catch (err) {
        setDrafts(previous => ({...previous, [key]: {...draft, conflict: true}})); throw new Error(`${String(err)}。草稿已保留。`)
      }
    })
  }
  async function mergeLatest() {
    if (!category || !draft) return
    await action(async () => {
      const snapshot = await apiClient.pluginRequest<SettingsSnapshot>('settings', {action: 'read', pluginId: selected, settingsId: category.descriptor.id, category: category.id})
      const edits = Object.fromEntries(Object.entries(draft.values).filter(([name, value]) => JSON.stringify(value) !== JSON.stringify(draft.snapshot.values[name])))
      setDrafts(previous => ({...previous, [key]: {snapshot, values: {...snapshot.values, ...edits}}}))
      setMessage('已读取最新版本，保留了你的修改；请核对后保存。')
    })
  }
  async function propose() {
    if (!row) return
    await action(async () => {
      const resources = resourceKind === 'user' ? [{kind: 'user', id: row.userId}] : resourceIds.split('\n').map(id => id.trim()).filter(Boolean).map(id => ({kind: resourceKind, id}))
      setRequest(await apiClient.pluginRequest<Request>('authorization', {action: 'request', pluginId: selected, spec: {consumerPluginId: consumer, capability, resources, purpose, methods: methods.filter(method => method.permissions.includes(capability)).map(method => method.name)}}))
    })
  }
  const edit = (name: string, value: unknown) => setDrafts(previous => ({...previous, [key]: {...previous[key], values: {...previous[key].values, [name]: value}}}))

  return <div className="flex flex-col sm:flex-row gap-5 min-h-80 text-content">
    <nav aria-label="选择插件" className="flex sm:flex-col sm:w-36 sm:shrink-0 gap-1 overflow-auto sm:border-r border-default sm:pr-3">
      {!rows.length && <p className="text-sm text-content-secondary">暂无已安装插件</p>}
      {rows.map(item => <button type="button" disabled={busy} key={item.pluginId} onClick={() => setSelected(item.pluginId)} className={`${button} whitespace-nowrap text-left ${selected === item.pluginId ? 'font-semibold' : 'text-content-secondary'}`}>{item.name}</button>)}
    </nav>
    <section className="min-w-0 flex-1 space-y-4">
      {row && <header><h4 className="font-semibold">{row.name}</h4><p className="text-xs text-content-tertiary mt-1">{row.pluginId} · {row.version || '版本不可读'}</p></header>}
      {selected && <div role="tablist" aria-label="插件配置类别" className="flex gap-2 overflow-auto border-b border-default pb-2"><button role="tab" aria-selected={tab === 'permissions'} className={button} onClick={() => setTab('permissions')}>授权</button>{categories.map(item => {const id = `${item.descriptor.id}/${item.id}`; return <button role="tab" aria-selected={tab === id} key={id} className={`${button} whitespace-nowrap`} onClick={() => setTab(id)}>{item.title}</button>})}</div>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {!category && message && <p role="status" className="text-sm text-content-secondary">{message}</p>}
      {tab === 'permissions' && row && <div className="space-y-4">
        <p className="text-sm text-content-secondary">授权独立生效，交互与后台需要分别批准。批准后不会自动选用来源。</p>
        {!available && <p className="text-sm text-content-secondary">插件当前不可用，已有授权仍可查看和撤销。</p>}
        {grants.map(grant => <div key={grant.grantId} className="border-b border-default py-3 text-sm space-y-1"><div className="flex flex-wrap items-center gap-2"><strong className="break-all">{grant.capability}</strong><span>{grant.purpose === 'background' ? '后台' : '交互'}</span><button className={`${button} ml-auto`} disabled={busy || grant.revoked} onClick={() => void action(async () => {await apiClient.pluginRequest('authorization', {action: 'revoke', grantId: grant.grantId}); await reloadGrants(); setMessage('授权已撤销')})}>{grant.revoked ? '已撤销' : '撤销'}</button></div><p className="text-content-secondary break-all">使用方：{grant.consumerPluginId}</p><p className="text-content-secondary break-all">范围：{grant.resources.map(resource => `${resource.kind}: ${resource.id}`).join('；')}</p></div>)}
        {available && !!methods.length && <fieldset disabled={busy} className="border-t border-default pt-4 space-y-3"><legend className="text-sm font-medium px-1">申请授权</legend>
          <label className="block text-sm">能力<select className={`${input} mt-1`} value={capability} onChange={e => setCapability(e.target.value)}>{[...new Set(methods.flatMap(method => method.permissions))].map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="block text-sm">使用方<select className={`${input} mt-1`} value={consumer} onChange={e => setConsumer(e.target.value)}>{rows.filter(item => item.intent === 'enabled').map(item => <option key={item.pluginId} value={item.pluginId}>{item.name}</option>)}</select></label>
          <label className="block text-sm">用途<select className={`${input} mt-1`} value={purpose} onChange={e => setPurpose(e.target.value)}><option value="interactive">交互操作</option><option value="background">后台任务</option></select></label>
          <label className="block text-sm">资源范围<select className={`${input} mt-1`} value={resourceKind} onChange={e => setResourceKind(e.target.value)}><option value="user">当前用户的全部资源</option>{selected === 'stella.email' && <option value="folder">指定邮箱来源</option>}{selected === 'stella.elearning' && <option value="course">指定课程</option>}</select></label>
          {resourceKind !== 'user' && <label className="block text-sm">稳定资源 ID（每行一个）<textarea className={`${input} mt-1`} value={resourceIds} onChange={e => setResourceIds(e.target.value)} /></label>}
          <button className={button} disabled={busy || !capability} onClick={() => void propose()}>审阅授权范围</button>
        </fieldset>}
      </div>}
      {category && (
        <Group title={category.title}>
          {!fields.length && <p className="text-sm text-content-secondary">此类别没有独立配置项。</p>}
          {fields.map((field) => (
            <Row
              key={field.key}
              label={field.title}
              hint={field.description}
              control={field.type === 'boolean' ? fieldControl(field, draft, busy, edit) : undefined}
            >
              {field.type === 'boolean' ? null : fieldControl(field, draft, busy, edit)}
            </Row>
          ))}
          {!!fields.filter((field) => !field.secret).length && (
            <div className="space-y-2 pt-2">
              <SaveRow status={message} onSave={() => void save()} label="保存本类别" />
              {draft?.conflict && (
                <button type="button" className={button} disabled={busy} onClick={() => void mergeLatest()}>
                  读取最新版本并保留修改
                </button>
              )}
            </div>
          )}
        </Group>
      )}
    </section>
    <dialog ref={dialog} onCancel={e => {if (busy) e.preventDefault(); else setRequest(null)}} className="m-auto w-[min(32rem,90vw)] rounded-card border border-default bg-surface p-6 text-content backdrop:bg-black/40">
      {request && <div className="space-y-4"><h3 className="text-lg font-semibold">批准插件授权</h3><p className="text-sm break-all">允许 {request.consumerPluginId} 使用 {request.capability}（{request.purpose === 'background' ? '后台任务' : '交互操作'}）。</p><p className="text-sm break-all">{request.resources.map(resource => `${resource.kind}: ${resource.id}`).join('；')}</p><p className="text-xs text-content-secondary break-all">方法：{request.methods.join('、')}</p>{error && <p role="alert" className="text-sm text-danger">{error}</p>}<div className="flex justify-end gap-2"><button className={button} disabled={busy} onClick={() => {dialog.current?.close(); setRequest(null)}}>取消</button><button className="rounded-btn bg-accent px-3 py-2 text-white text-sm disabled:opacity-50" disabled={busy} onClick={() => void action(async () => {await apiClient.pluginRequest('authorization', {action: 'approve', requestId: request.requestId}); await reloadGrants(); dialog.current?.close(); setRequest(null); setMessage('授权已生效，来源选用保持原来的设置。')})}>批准并立即生效</button></div></div>}
    </dialog>
  </div>
}
