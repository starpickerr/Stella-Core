import React, { useCallback, useEffect, useState } from 'react'
import { Shield, RefreshCw } from 'lucide-react'
import apiClient from '../api/client'
import type { SecurityCenterState, SecurityPolicy, SecurityRecord } from '../api/client'
import { getLang } from '../i18n'
import { useSessionStore } from '../store/sessionStore'

const ruleNames = [
  'managed',
  'workspace_read',
  'workspace_write',
  'workspace_outside',
  'shell',
  'git',
  'network',
  'install',
  'background',
  'external',
  'high_risk',
] as const
const zhRules: Record<string, string> = {
  managed: 'Agent 内部资源',
  workspace_read: '读取工作区',
  workspace_write: '写入工作区',
  workspace_outside: '工作区外访问',
  shell: '终端命令',
  git: 'Git 操作',
  network: '网络访问',
  install: '软件安装',
  background: '后台进程',
  external: '外部服务',
  high_risk: '高风险操作',
}
const enRules: Record<string, string> = {
  managed: 'Agent managed storage',
  workspace_read: 'Workspace read',
  workspace_write: 'Workspace write',
  workspace_outside: 'Outside workspace access',
  shell: 'Shell',
  git: 'Git operations',
  network: 'Network',
  install: 'Software install',
  background: 'Background process',
  external: 'External services',
  high_risk: 'High risk operations',
}
const tabs = ['overview', 'permissions', 'projects', 'connections', 'secrets', 'activity'] as const
type Tab = (typeof tabs)[number]
const labels: Record<Tab, [string, string]> = {
  overview: ['总览', 'Overview'],
  permissions: ['Agent 权限', 'Agent permissions'],
  projects: ['项目权限', 'Projects'],
  connections: ['连接与访问', 'Connections'],
  secrets: ['凭据', 'Credentials'],
  activity: ['安全活动', 'Activity'],
}
const card = 'rounded-card border border-default bg-surface p-5'
const input = 'rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm'
const action = 'rounded-btn bg-accent text-accent-contrast px-3 py-2 text-sm disabled:opacity-50'
const faded = 'text-sm text-content-secondary'

const SecurityPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const en = getLang() === 'en'
  const sid = useSessionStore((s) => s.activeId)
  const [tab, setTab] = useState<Tab>(
    new URLSearchParams(window.location.search).get('tab') === 'activity' ? 'activity' : 'overview',
  )
  const [center, setCenter] = useState<SecurityCenterState | null>(null)
  const [records, setRecords] = useState<SecurityRecord[]>([])
  const [pending, setPending] = useState<
    {
      id: string
      tool: string
      session: string | null
      summary: string
      resource: string
      risk: string
      reason: string
    }[]
  >([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedProject, setSelectedProject] = useState('')
  const [extraRoot, setExtraRoot] = useState('')
  const [secretName, setSecretName] = useState('')
  const [secretValue, setSecretValue] = useState('')
  const [password, setPassword] = useState('')

  const load = useCallback(async () => {
    try {
      const queryFilters = { ...filters }
      if (queryFilters.since) queryFilters.since = String(Math.floor(new Date(queryFilters.since).getTime() / 1000))
      const [state, events, confirmations] = await Promise.all([
        apiClient.getSecurityCenter(sid || undefined),
        apiClient.getSecurityRecords(queryFilters),
        apiClient.getSecurityConfirmations(),
      ])
      if (state.status !== 'success') throw new Error(state.message || 'Unable to load security state')
      setCenter(state)
      setRecords(events)
      setPending(confirmations as typeof pending)
      setError('')
      setSelectedProject((previous) =>
        state.projects.some((item) => item.path === previous)
          ? previous
          : state.project || state.projects[0]?.path || '',
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [sid, filters])
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void load()
  }, [baseUrl, load])
  const mutate = async (fn: () => Promise<{ status: string; message?: string }>) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await fn()
      if (result.status !== 'success') throw new Error(result.message || (en ? 'Save failed' : '保存失败'))
      setNotice(en ? 'Saved' : '已保存')
      await load()
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      return false
    } finally {
      setBusy(false)
    }
  }
  const saveGlobal = (patch: SecurityPolicy) => {
    if (!center) return
    void mutate(() => apiClient.saveSecurityPolicy('global', { ...center.global_policy, ...patch }))
  }
  const project = center?.projects.find((item) => item.path === selectedProject)
  const saveProject = (patch: SecurityPolicy) => {
    if (!project) return
    void mutate(() =>
      apiClient.saveSecurityPolicy(
        'project',
        { ...project.policy, ...patch },
        { project: project.path, session: sid || undefined },
      ),
    )
  }
  const saveConversation = (patch: SecurityPolicy) => {
    if (!sid || !center) return
    void mutate(() =>
      apiClient.saveSecurityPolicy(
        'conversation',
        { ...center.conversation_policy, ...patch },
        { session: sid },
      ),
    )
  }
  const selectRule = (
    value: string,
    current: SecurityPolicy,
    onSave: (policy: SecurityPolicy) => void,
    name: string,
  ) => {
    const rules = { ...(current.rules || {}) }
    if (value === '') delete rules[name]
    else rules[name] = value as 'allow' | 'confirm' | 'deny'
    onSave({ rules })
  }
  const ruleTable = (policy: SecurityPolicy, onSave: (patch: SecurityPolicy) => void, inherit: boolean) => (
    <div className="divide-y divide-default">
      {ruleNames.map((name) => (
        <div key={name} className="py-2 flex items-center justify-between gap-3 text-sm">
          <span>{(en ? enRules : zhRules)[name]}</span>
          <select
            disabled={busy}
            className={input}
            value={policy.rules?.[name] || ''}
            onChange={(event) => selectRule(event.target.value, policy, onSave, name)}
          >
            <option value="">{inherit ? (en ? 'Inherit' : '继承') : en ? 'Preset' : '预设'}</option>
            <option value="allow">Allow</option>
            <option value="confirm">Confirm</option>
            <option value="deny">Deny</option>
          </select>
        </div>
      ))}
    </div>
  )
  const eventList = (items: SecurityRecord[]) =>
    items.length ? (
      <div className="divide-y divide-default">
        {items.map((item, index) => (
          <details key={`${item.at}-${index}`} className="py-3 text-sm">
            <summary className="cursor-pointer flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-content-tertiary">{new Date(item.at * 1000).toLocaleString()}</span>
              <strong
                className={
                  item.decision === 'deny'
                    ? 'text-danger'
                    : item.decision === 'confirm'
                      ? 'text-amber-500'
                      : 'text-accent'
                }
              >
                {item.decision.toUpperCase()}
              </strong>
              <span>
                {item.event || item.tool} · {item.operation}
              </span>
              <span className="text-content-tertiary">{item.risk}</span>
            </summary>
            <div className="mt-2 pl-4 space-y-1 text-content-secondary break-all">
              <p>
                {en ? 'Resource' : '资源'}: {item.resource}
              </p>
              <p>
                {en ? 'Agent / conversation' : 'Agent / 对话'}: {item.agent} / {item.conversation || '—'}
              </p>
              <p>
                {en ? 'Project' : '项目'}: {item.project || '—'}
              </p>
              <p>
                {en ? 'Reason' : '原因'}: {item.reason}
              </p>
              <div className="text-xs">
                {item.trace?.map((step, i) => (
                  <p key={i}>{step}</p>
                ))}
              </div>
            </div>
          </details>
        ))}
      </div>
    ) : (
      <p className={faded}>{en ? 'No events yet.' : '暂无记录。'}</p>
    )

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-5xl mx-auto space-y-5">
        <header className="flex justify-between items-center">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Shield size={23} />
            Stella Security Center
          </h1>
          <button type="button" aria-label={en ? 'Refresh' : '刷新'} onClick={() => void load()}>
            <RefreshCw size={17} />
          </button>
        </header>
        <nav className="flex gap-2 overflow-x-auto border-b border-default pb-2">
          {tabs.map((name) => (
            <button
              type="button"
              key={name}
              onClick={() => setTab(name)}
              className={`shrink-0 px-3 py-2 rounded-btn text-sm ${tab === name ? 'bg-accent-soft text-accent font-semibold' : 'text-content-secondary hover:bg-surface-2'}`}
            >
              {labels[name][en ? 1 : 0]}
            </button>
          ))}
        </nav>
        {notice && (
          <p role="status" className="text-sm text-accent">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        {!center ? (
          <p className={faded}>{en ? 'Loading security state…' : '正在加载安全状态…'}</p>
        ) : (
          <>
            {tab === 'overview' && (
              <div className="space-y-5">
                <div className="grid sm:grid-cols-4 gap-3">
                  {[
                    [
                      en ? 'Status' : '安全状态',
                      center.summary.status === 'normal'
                        ? en
                          ? 'Normal'
                          : '正常'
                        : en
                          ? 'Needs review'
                          : '需查看',
                    ],
                    [en ? 'Default policy' : '默认策略', center.global_policy.preset || 'standard'],
                    [en ? 'Connections' : '已授权连接', String(center.summary.connection_count)],
                    [en ? 'Credentials' : '已配置凭据', String(center.summary.secret_count)],
                  ].map(([title, value]) => (
                    <div className={card} key={title}>
                      <p className="text-xs text-content-tertiary">{title}</p>
                      <p className="text-xl font-semibold mt-2">{value}</p>
                    </div>
                  ))}
                </div>
                {pending.length > 0 && (
                  <section className={card}>
                    <h2 className="font-semibold mb-3">{en ? 'Awaiting confirmation' : '待确认操作'}</h2>
                    {pending.map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-4 py-2 text-sm">
                        <span>
                          {item.tool} · {item.resource} · {item.risk}
                          <br />
                          <code className="text-xs break-all">{item.summary}</code>
                          <br />
                          <span className="text-content-secondary">{item.reason}</span>
                        </span>
                        <div className="flex gap-2 shrink-0">
                          <button disabled={busy} className={action}
                            onClick={() => void mutate(() => apiClient.approveSecurityConfirmation(item.id))}>
                            {en ? 'Allow once' : '允许一次'}
                          </button>
                          <button disabled={busy} className={`${input} text-danger`}
                            onClick={() => void mutate(() => apiClient.rejectSecurityConfirmation(item.id))}>
                            {en ? 'Deny' : '拒绝'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </section>
                )}
                <section className={card}>
                  <h2 className="font-semibold mb-3">{en ? 'Recent high risk events' : '近期高风险事件'}</h2>
                  {eventList(center.summary.recent_high_risk)}
                </section>
                <section className={card}>
                  <h2 className="font-semibold mb-3">{en ? 'Recent denials' : '近期权限拒绝'}</h2>
                  {eventList(center.summary.recent_denials)}
                </section>
              </div>
            )}
            {tab === 'permissions' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{en ? 'Default agent policy' : 'Agent 默认策略'}</h2>
                  <p className={`${faded} mt-2`}>
                    {en
                      ? 'Agent skills and internal state are managed independently from project files.'
                      : 'Agent 的 Skill 和内部状态与项目文件分别授权。'}
                  </p>
                  <div className="mt-4 flex gap-2 flex-wrap">
                    {(['strict', 'standard', 'custom'] as const).map((preset) => (
                      <button
                        type="button"
                        key={preset}
                        disabled={busy}
                        onClick={() => saveGlobal({ preset, rules: {} })}
                        className={`px-4 py-2 rounded-btn text-sm border ${center.global_policy.preset === preset ? 'border-accent text-accent bg-accent-soft' : 'border-default'}`}
                      >
                        {
                          {
                            strict: en ? 'Strict' : '严格',
                            standard: en ? 'Standard · recommended' : '标准 · 推荐',
                            custom: en ? 'Custom' : '自定义',
                          }[preset]
                        }
                      </button>
                    ))}
                  </div>
                </section>
                <section className={card}>
                  <h2 className="font-semibold mb-2">{en ? 'Advanced rules' : '高级权限'}</h2>
                  {ruleTable(center.global_policy, saveGlobal, false)}
                </section>
                <p className="text-xs text-content-tertiary">
                  {en
                    ? 'Shell and child processes use argument checks; they are not an operating system sandbox.'
                    : '终端与子进程经过参数检查，但不提供操作系统级隔离。'}
                </p>
              </div>
            )}
            {tab === 'projects' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold mb-3">{en ? 'Project policy' : '项目权限'}</h2>
                  <select
                    className={`${input} w-full`}
                    value={selectedProject}
                    onChange={(event) => setSelectedProject(event.target.value)}
                  >
                    <option value="">{en ? 'Select a project' : '选择项目'}</option>
                    {center.projects.map((item) => (
                      <option key={item.path} value={item.path}>
                        {item.name} · {item.path}
                      </option>
                    ))}
                  </select>
                  {project ? (
                    <>
                      <p className={`${faded} mt-3`}>
                        {en ? 'Only differences from the default are saved.' : '仅保存与默认策略不同的权限。'}
                      </p>
                      <div className="mt-3">{ruleTable(project.policy, saveProject, true)}</div>
                    </>
                  ) : (
                    <p className={`${faded} mt-3`}>
                      {en ? 'Open a project to manage its permissions.' : '打开项目后即可管理项目权限。'}
                    </p>
                  )}
                </section>
                {sid && (
                  <section className={card}>
                    <h2 className="font-semibold">{en ? 'This conversation' : '当前对话临时权限'}</h2>
                    <p className={`${faded} mt-2`}>
                      {center.project || (en ? 'Default workspace' : '默认工作区')}
                    </p>
                    <div className="mt-3">
                      {ruleTable(center.conversation_policy, saveConversation, true)}
                    </div>
                    <label className="block text-sm mt-4">
                      {en ? 'Additional directory' : '额外授权目录'}
                      <div className="flex gap-2 mt-2">
                        <input
                          className={`${input} flex-1`}
                          value={extraRoot}
                          onChange={(event) => setExtraRoot(event.target.value)}
                          placeholder="/path/to/directory"
                        />
                        <button
                          disabled={busy || !extraRoot.trim()}
                          className={action}
                          onClick={() => {
                            saveConversation({
                              extra_roots: [
                                ...(center.conversation_policy.extra_roots || []),
                                extraRoot.trim(),
                              ],
                            })
                            setExtraRoot('')
                          }}
                        >
                          {en ? 'Add' : '添加'}
                        </button>
                      </div>
                    </label>
                    {(center.conversation_policy.extra_roots || []).map((root) => (
                      <div key={root} className="flex justify-between items-center text-sm mt-2">
                        <span className="break-all">{root}</span>
                        <button
                          disabled={busy}
                          className="text-danger"
                          onClick={() =>
                            saveConversation({
                              extra_roots: (center.conversation_policy.extra_roots || []).filter(
                                (item) => item !== root,
                              ),
                            })
                          }
                        >
                          {en ? 'Remove' : '移除'}
                        </button>
                      </div>
                    ))}
                  </section>
                )}
              </div>
            )}
            {tab === 'connections' && (
              <div className="space-y-3">
                {center.connections.map((connection) => (
                  <section key={connection.id} className={`${card} flex justify-between gap-4 items-start`}>
                    <div>
                      <h2 className="font-semibold">{connection.name}</h2>
                      <p className={faded}>
                        {connection.connected
                          ? en
                            ? 'Connected'
                            : '已连接'
                          : en
                            ? 'Not connected'
                            : '未连接'}{' '}
                        ·{' '}
                        {connection.allowed
                          ? en
                            ? 'Access allowed'
                            : '允许访问'
                          : en
                            ? 'Access revoked'
                            : '访问已撤销'}
                      </p>
                      <p className="text-xs text-content-tertiary mt-2">
                          Scope: {connection.scopes.includes('*')
                            ? en ? 'All operations' : '全部操作'
                            : connection.scopes.length ? connection.scopes.join(', ') : '—'}
                      </p>
                      <p className="text-xs text-content-tertiary">
                        {en ? 'Last access' : '最近访问'}:{' '}
                        {connection.last_access
                          ? new Date(connection.last_access * 1000).toLocaleString()
                          : '—'}
                      </p>
                    </div>
                    <button
                      disabled={busy}
                      className={action}
                      onClick={() =>
                        void mutate(() =>
                          apiClient.updateSecurityConnection(
                            connection.id,
                            !connection.allowed,
                            connection.scopes,
                          ),
                        )
                      }
                    >
                      {connection.allowed
                        ? en
                          ? 'Revoke access'
                          : '撤销访问'
                        : en
                          ? 'Reauthorize'
                          : '重新授权'}
                    </button>
                  </section>
                ))}
              </div>
            )}
            {tab === 'secrets' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{en ? 'Agent credentials' : 'Agent 凭据'}</h2>
                  <p className={`${faded} mt-2`}>
                    {en
                      ? 'Configured status is visible here. Credential values are never shown.'
                      : '此处仅显示配置状态，不显示凭据明文。'}
                  </p>
                  <div className="mt-3 divide-y divide-default">
                    {center.secrets.map((item) => (
                      <div key={item.name} className="flex justify-between items-center py-2 text-sm">
                        <span>
                          {item.name} <span className="text-content-tertiary">· {item.source}</span>
                        </span>
                        <button
                          disabled={busy}
                          className="text-danger"
                          onClick={() => void mutate(() => apiClient.deleteSecuritySecret(item.name))}
                        >
                          {en ? 'Delete' : '删除'}
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-2 mt-4">
                    <input
                      className={input}
                      placeholder={en ? 'Credential name' : '凭据名称'}
                      value={secretName}
                      onChange={(event) => setSecretName(event.target.value.toUpperCase())}
                    />
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={input}
                      placeholder={en ? 'New value' : '新凭据值'}
                      value={secretValue}
                      onChange={(event) => setSecretValue(event.target.value)}
                    />
                    <button
                      disabled={busy || !secretName || !secretValue}
                      className={action}
                      onClick={() => {
                        void mutate(() => apiClient.saveSecuritySecret(secretName, secretValue)).then((ok) => {
                          if (ok) setSecretValue('')
                        })
                      }}
                    >
                      {en ? 'Save' : '保存'}
                    </button>
                  </div>
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{en ? 'App access password' : '应用访问密码'}</h2>
                  <p className={`${faded} mt-2`}>
                    {center.summary.app_password_set
                      ? en
                        ? 'Configured'
                        : '已设置'
                      : en
                        ? 'Not configured'
                        : '未设置'}
                  </p>
                  <div className="flex gap-2 mt-3">
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${input} flex-1`}
                      placeholder={en ? 'New app password' : '新应用密码'}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                    <button
                      disabled={busy || !password}
                      className={action}
                      onClick={() => {
                        void mutate(() => apiClient.updateConfig({ web_password: password })).then((ok) => {
                          if (ok) setPassword('')
                        })
                      }}
                    >
                      {en ? 'Change password' : '修改密码'}
                    </button>
                  </div>
                </section>
              </div>
            )}
            {tab === 'activity' && (
              <section className={card}>
                <div className="flex items-center justify-between gap-3 mb-3">
                  <h2 className="font-semibold">{en ? 'Security activity' : '安全活动'}</h2>
                  <button className="text-xs text-accent" onClick={() => setFilters({})}>
                    {en ? 'Clear filters' : '清除筛选'}
                  </button>
                </div>
                <div className="grid sm:grid-cols-3 gap-2 mb-4">
                  {['agent', 'project', 'tool', 'risk', 'decision', 'since'].map((key) =>
                    key === 'risk' || key === 'decision' ? (
                      <select
                        key={key}
                        className={input}
                        value={filters[key] || ''}
                        onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
                      >
                        <option value="">{key}</option>
                        {(key === 'risk'
                          ? ['L0', 'L1', 'L2', 'L3', 'L4']
                          : ['allow', 'confirm', 'deny', 'policy_change', 'secret_use', 'external_access']
                        ).map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    ) : key === 'since' ? (
                      <label key={key} className="text-xs text-content-secondary">
                        {en ? 'From' : '起始时间'}
                        <input type="datetime-local" className={`${input} w-full mt-1`}
                          value={filters.since || ''}
                          onChange={(event) => setFilters({ ...filters, since: event.target.value })} />
                      </label>
                    ) : (
                      <input
                        key={key}
                        className={input}
                        placeholder={key}
                        value={filters[key] || ''}
                        onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
                      />
                    ),
                  )}
                </div>
                {eventList(records)}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
export default SecurityPage
