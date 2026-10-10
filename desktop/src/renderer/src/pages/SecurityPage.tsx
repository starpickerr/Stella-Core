import React, { useCallback, useEffect, useState } from 'react'
import { ShieldCheck, RefreshCw, ChevronRight } from 'lucide-react'
import apiClient from '../api/client'
import type { SecurityCenterState, SecurityPolicy, SecurityRecord } from '../api/client'
import { getLang } from '../i18n'
import PageHeader from '../components/PageHeader'
import { useSessionStore } from '../store/sessionStore'
import {
  commonCredentials,
  ruleGroups,
  securityCopy,
  securityReason,
  securityResource,
  securityRuleName,
  securitySecretName,
  securityTrace,
} from './securityLocale'

const tabs = ['overview', 'permissions', 'projects', 'connections', 'secrets', 'activity'] as const
type Tab = (typeof tabs)[number]
const card = 'rounded-card border border-default bg-surface p-5'
const input =
  'rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm text-content focus-visible:outline-2 focus-visible:outline-accent'
const action =
  'rounded-btn bg-accent text-accent-contrast px-3 py-2 text-sm disabled:bg-surface-2 disabled:text-content-tertiary focus-visible:outline-2 focus-visible:outline-accent'
const faded = 'text-sm text-content-secondary'

const PolicyEditor: React.FC<{
  policy: SecurityPolicy
  definitions: SecurityCenterState['mode_definitions']
  copy: ReturnType<typeof securityCopy>
  busy: boolean
  inherit: boolean
  onSave: (patch: SecurityPolicy) => void
  onCancel?: () => void
}> = ({ policy, definitions, copy, busy, inherit, onSave, onCancel }) => {
  const initialBase = policy.base_preset || (policy.preset === 'custom' ? 'workspace-write' : policy.preset) || 'workspace-write'
  const [base, setBase] = useState(initialBase)
  const [rules, setRules] = useState<Record<string, 'allow' | 'confirm' | 'deny'>>({ ...(policy.rules || {}) })
  useEffect(() => {
    setBase(policy.base_preset || (policy.preset === 'custom' ? 'workspace-write' : policy.preset) || 'workspace-write')
    setRules({ ...(policy.rules || {}) })
  }, [policy])
  const baseRules = definitions.find(row => row.id === base)?.rules || {}
  const differences = Object.keys(rules).filter(name => rules[name] !== baseRules[name]).length
  return <div className="space-y-4">
    <label className="block text-sm">{getLang() === 'en' ? 'Base mode' : '基础方案'}
      <select className={`${input} block mt-1 w-full`} value={base}
        onChange={event => setBase(event.target.value as typeof base)}>
        {definitions.filter(row => row.id !== 'custom').map(row => <option key={row.id} value={row.id}>{row.name[getLang() === 'en' ? 'en' : 'zh']}</option>)}
      </select></label>
    <p className="text-xs text-content-secondary">{getLang() === 'en' ? `${differences} differences` : `${differences} 项差异`}</p>
    {ruleGroups.map(group => <section key={group.id}>
      <h3 className="text-xs font-semibold text-content-secondary mb-1">{copy.groups[group.id]}</h3>
      <div className="divide-y divide-default">{group.rules.map(name => <label key={name} className="py-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <span><span className="block text-sm font-medium">{copy.rules[name].name}</span><span className="block text-xs text-content-secondary">{copy.rules[name].help}</span></span>
        <select aria-label={copy.rules[name].name} disabled={busy} className={`${input} w-full sm:w-44`}
          value={rules[name] || (inherit ? '' : baseRules[name])}
          onChange={event => setRules(value => {
            const next = { ...value }
            if (event.target.value) next[name] = event.target.value as 'allow' | 'confirm' | 'deny'
            else delete next[name]
            return next
          })}>
          {inherit && <option value="">{copy.decisions.inherit}</option>}
          <option value="allow">{copy.decisions.allow}</option><option value="confirm">{copy.decisions.confirm}</option><option value="deny">{copy.decisions.deny}</option>
        </select>
      </label>)}</div>
    </section>)}
    <div className="flex flex-wrap gap-3 text-sm">
      <button type="button" className="text-accent" onClick={() => setRules({ ...baseRules })}>{getLang() === 'en' ? 'Restore base' : '恢复基础方案'}</button>
      <button type="button" onClick={() => { setRules({ ...(policy.rules || {}) }); onCancel?.() }}>{getLang() === 'en' ? 'Cancel' : '取消'}</button>
      <button type="button" disabled={busy} className={action} onClick={() => onSave({ preset: 'custom', base_preset: base, rules })}>{getLang() === 'en' ? 'Save custom' : '保存自定义'}</button>
    </div>
  </div>
}

const SecurityPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const copy = securityCopy(getLang())
  const sid = useSessionStore((s) => s.activeId)
  const [tab, setTab] = useState<Tab>(
    new URLSearchParams(window.location.search).get('tab') === 'activity' ? 'activity' : 'overview',
  )
  const [center, setCenter] = useState<SecurityCenterState | null>(null)
  const [records, setRecords] = useState<SecurityRecord[]>([])
  const [availableEvents, setAvailableEvents] = useState<SecurityRecord[]>([])
  const [pending, setPending] = useState<
    {
      id: string
      tool: string
      session: string | null
      summary: string
      resource: string
      risk: string
      reason: string
      expanded_scope: string
      effect: string
    }[]
  >([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [sinceDraft, setSinceDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedProject, setSelectedProject] = useState('')
  const [extraRoot, setExtraRoot] = useState('')
  const [secretName, setSecretName] = useState('')
  const [customSecretName, setCustomSecretName] = useState('')
  const [secretValue, setSecretValue] = useState('')
  const [password, setPassword] = useState('')
  const [showGlobalEditor, setShowGlobalEditor] = useState(false)

  const load = useCallback(async () => {
    try {
      const queryFilters = { ...filters }
      if (queryFilters.since)
        queryFilters.since = String(Math.floor(new Date(queryFilters.since + 'T00:00:00').getTime() / 1000))
      const filtered = Object.values(filters).some(Boolean)
      const [state, events, confirmations, allEvents] = await Promise.all([
        apiClient.getSecurityCenter(sid || undefined),
        apiClient.getSecurityRecords(queryFilters),
        apiClient.getSecurityConfirmations(),
        filtered ? apiClient.getSecurityRecords() : Promise.resolve(null),
      ])
      if (state.status !== 'success') throw new Error(copy.loading)
      setCenter(state)
      setRecords(events)
      setAvailableEvents(allEvents || events)
      setPending(confirmations as typeof pending)
      setError('')
      setSelectedProject((previous) =>
        state.projects.some((item) => item.path === previous)
          ? previous
          : state.project || state.projects[0]?.path || '',
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : copy.saveFailed)
    }
  }, [sid, filters, copy])
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void load()
  }, [baseUrl, load])
  const mutate = async (fn: () => Promise<{ status: string; message?: string }>, success = copy.saved) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await fn()
      if (result.status !== 'success') throw new Error(result.message || copy.saveFailed)
      setNotice(success)
      await load()
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : copy.saveFailed)
      return false
    } finally {
      setBusy(false)
    }
  }
  const saveGlobal = (patch: SecurityPolicy) => {
    if (!center) return Promise.resolve(false)
    return mutate(() => apiClient.saveSecurityPolicy('global', { ...center.global_policy, ...patch }))
  }
  const project = center?.projects.find((item) => item.path === selectedProject)
  const credentialName = secretName === 'other' ? customSecretName.trim().toUpperCase() : secretName
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
  const overrideSummary = (policy: SecurityPolicy) => {
    const entries = Object.entries(policy.rules || {})
    return entries.length ? (
      <div className="flex flex-wrap gap-2 mt-3">
        {entries.map(([name, value]) => (
          <span key={name} className="rounded-btn bg-surface-2 px-2.5 py-1 text-xs text-content-secondary">
            {securityRuleName(copy, name)} · {copy.decisions[value]}
          </span>
        ))}
      </div>
    ) : (
      <p className={`${faded} mt-3`}>{copy.noOverrides}</p>
    )
  }
  const eventList = (items: SecurityRecord[]) =>
    items.length ? (
      <div className="divide-y divide-default">
        {items.map((item, index) => {
          const outcome = (copy.outcomes as Record<string, string>)[item.decision] || copy.reasonFallback
          const event =
            (copy.events as Record<string, string>)[item.event] ||
            (copy.tools as Record<string, string>)[item.tool] ||
            copy.events.tool_decision
          const risk = (copy.risk as Record<string, string>)[item.risk] || copy.risk.L2
          const trace = securityTrace(copy, item.trace || [])
          return (
            <details key={`${item.at}-${index}`} className="group py-3 text-sm">
              <summary className="cursor-pointer list-none flex items-start gap-3 focus-visible:outline-2 focus-visible:outline-accent">
                <span
                  className={`mt-0.5 inline-block size-2.5 rounded-full shrink-0 ${item.decision === 'deny' ? 'bg-danger' : item.decision === 'confirm' ? 'bg-amber-500' : 'bg-accent'}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">
                    {event} · {securityResource(copy, item.resource)}
                  </span>
                  <span className="block text-xs text-content-secondary mt-1">
                    {new Date(item.at * 1000).toLocaleString(getLang() === 'en' ? 'en-US' : 'zh-CN')}
                    {' · '}
                    {risk}
                  </span>
                </span>
                <span className="text-xs font-medium text-content-secondary shrink-0">{outcome}</span>
                <ChevronRight
                  size={15}
                  className="text-content-tertiary shrink-0 transition-transform group-open:rotate-90"
                />
              </summary>
              <div className="mt-3 ml-5 space-y-2 text-content-secondary break-words">
                <p className="text-content">
                  {copy.reason}
                  {copy.fieldSeparator}
                  {securityReason(copy, item)}
                </p>
                <p>
                  {copy.assistant}
                  {copy.fieldSeparator}
                  {item.agent === 'default' ? 'Stella' : item.agent}
                </p>
                {item.project && (
                  <p>
                    {copy.project}
                    {copy.fieldSeparator}
                    {item.project}
                  </p>
                )}
                {item.conversation && (
                  <p>
                    {copy.conversation}
                    {copy.fieldSeparator}
                    {item.conversation}
                  </p>
                )}
                {trace.length > 0 && (
                  <div className="rounded-btn bg-surface-2 px-3 py-2 text-xs space-y-1">
                    <p className="font-medium text-content">{copy.decisionSteps}</p>
                    {trace.map((step, i) => (
                      <p key={i}>{step}</p>
                    ))}
                  </div>
                )}
              </div>
            </details>
          )
        })}
      </div>
    ) : (
      <p className={faded}>{copy.noEvents}</p>
    )

  return (
    <div
      lang={getLang() === 'en' ? 'en-US' : 'zh-CN'}
      className="h-full flex flex-col min-h-0"
    >
      <PageHeader className="flex justify-between items-start gap-4">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <ShieldCheck size={23} className="text-accent" />
            {copy.title}
          </h1>
          <p className="text-sm text-content-secondary mt-1">{copy.subtitle}</p>
        </div>
        <button type="button" className={input} aria-label={copy.refresh} onClick={() => void load()}>
          <RefreshCw size={17} />
        </button>
      </PageHeader>
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5 sm:py-7">
      <div className="max-w-4xl mx-auto space-y-5">
        <nav className="flex gap-2 overflow-x-auto border-b border-default pb-2">
          {tabs.map((name) => (
            <button
              type="button"
              key={name}
              onClick={() => setTab(name)}
              className={`shrink-0 px-3 py-2 rounded-btn text-sm ${tab === name ? 'bg-accent-soft text-accent font-semibold' : 'text-content-secondary hover:bg-surface-2'}`}
            >
              {copy.tabs[name]}
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
          <p className={faded}>{copy.loading}</p>
        ) : (
          <>
            {tab === 'overview' && (
              <div className="space-y-5">
                <section className={card}>
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-1 size-3 rounded-full shrink-0 ${center.summary.status === 'normal' ? 'bg-accent' : 'bg-amber-500'}`}
                    />
                    <div className="min-w-0">
                      <h2 className="text-lg font-semibold">
                        {center.process_isolation.status === 'unavailable'
                          ? (getLang() === 'en' ? 'Process isolation unavailable' : '不支持进程隔离')
                          : center.summary.status === 'normal' ? copy.statusNormal : copy.statusAttention}
                      </h2>
                      <p className={faded}>
                        {center.process_isolation.reason}
                      </p>
                      {center.policy_error && <p role="alert" className="text-danger text-sm mt-2">{center.policy_error}</p>}
                    </div>
                  </div>
                  <div className="mt-5 pt-4 border-t border-default grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                    <div>
                      <span className="text-content-secondary">{copy.currentProtection}</span>
                      <p className="font-medium mt-1">
                        {center.mode_definitions.find(row => row.id === center.effective_mode)?.name[getLang() === 'en' ? 'en' : 'zh'] || center.effective_mode}
                      </p>
                      <p className="text-xs text-content-secondary">{getLang() === 'en' ? 'Source' : '来源'}：{center.policy_source}</p>
                    </div>
                    <div>
                      <span className="text-content-secondary">{copy.connectionsCount}</span>
                      <p className="font-medium mt-1">{center.summary.connection_count}</p>
                    </div>
                    <div>
                      <span className="text-content-secondary">{copy.secretsCount}</span>
                      <p className="font-medium mt-1">{center.summary.secret_count}</p>
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-content-secondary break-all">{getLang() === 'en' ? 'Authorized directories' : '授权目录'}：{center.authorized_roots.join(' · ')}</div>
                </section>
                {pending.length > 0 && (
                  <section className={card}>
                    <h2 className="font-semibold">{copy.reviewActions}</h2>
                    <p className={`${faded} mt-1 mb-3`}>{copy.reviewHelp}</p>
                    {pending.map((item) => (
                      <div
                        key={item.id}
                        className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 py-3 border-t border-default text-sm"
                      >
                        <div className="min-w-0">
                          <p className="font-medium">
                            {(copy.tools as Record<string, string>)[item.tool] || copy.events.tool_decision}
                          </p>
                          <p className="text-content-secondary mt-0.5">
                            {securityResource(copy, item.resource) !==
                              ((copy.tools as Record<string, string>)[item.tool] ||
                                copy.events.tool_decision) && (
                              <>
                                {securityResource(copy, item.resource)}
                                {' · '}
                              </>
                            )}
                            {(copy.risk as Record<string, string>)[item.risk] || copy.risk.L3}
                          </p>
                          {item.summary && (
                            <code className="block text-xs text-content-secondary break-all mt-1">
                              {item.summary}
                            </code>
                          )}
                          <p className="text-xs text-content-secondary mt-1">{item.reason} · {item.effect}</p>
                          {item.expanded_scope && <p className="text-xs text-content-secondary break-all mt-1">{getLang() === 'en' ? 'Expanded scope' : '扩大范围'}：{item.expanded_scope}</p>}
                        </div>
                        <div className="flex gap-2 shrink-0">
                          <button
                            disabled={busy}
                            className={action}
                            onClick={() =>
                              void mutate(() => apiClient.approveSecurityConfirmation(item.id, item.session), copy.approved)
                            }
                          >
                            {copy.allowOnce}
                          </button>
                          <button
                            disabled={busy}
                            className={`${input} text-danger`}
                            onClick={() =>
                              void mutate(() => apiClient.rejectSecurityConfirmation(item.id, item.session), copy.rejected)
                            }
                          >
                            {copy.deny}
                          </button>
                        </div>
                      </div>
                    ))}
                  </section>
                )}
                <section className={card}>
                  <h2 className="font-semibold mb-3">{copy.recentHighRisk}</h2>
                  {eventList(center.summary.recent_high_risk)}
                </section>
                <section className={card}>
                  <h2 className="font-semibold mb-3">{copy.recentDenials}</h2>
                  {eventList(center.summary.recent_denials)}
                </section>
                <button type="button" className="text-sm text-accent" onClick={() => setTab('activity')}>
                  {copy.seeActivity}
                </button>
              </div>
            )}
            {tab === 'permissions' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.presetsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.presetsHelp}</p>
                  <div className="mt-4 grid sm:grid-cols-2 xl:grid-cols-4 gap-2">
                    {center.mode_definitions.map((entry) => (
                      <button
                        type="button"
                        key={entry.id}
                        disabled={busy}
                        onClick={() => {
                          if (entry.id === 'custom') {
                            setShowGlobalEditor(true)
                            const current = center.global_policy
                            const base = current.base_preset || (current.preset !== 'custom' ? current.preset : 'workspace-write')
                            if (current.preset !== 'custom') {
                              saveGlobal({ preset: 'custom', base_preset: base, rules: { ...center.effective_rules } })
                            }
                            return
                          }
                          setShowGlobalEditor(false)
                          saveGlobal({ preset: entry.id, rules: {} })
                        }}
                        aria-pressed={center.effective_mode === entry.id}
                        className={`px-4 py-3 rounded-btn text-left border min-h-28 ${center.effective_mode === entry.id ? 'border-accent bg-accent-soft' : 'border-default hover:bg-surface-2'}`}
                      >
                        <span className="font-semibold text-sm">{entry.name[getLang() === 'en' ? 'en' : 'zh']}</span>
                        {entry.id === 'workspace-write' && (
                          <span className="ml-2 text-xs text-accent">{copy.recommended}</span>
                        )}
                        <span className="block text-xs text-content-secondary mt-2 leading-relaxed">
                          {entry.description[getLang() === 'en' ? 'en' : 'zh']}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
                {(showGlobalEditor || center.global_policy.preset === 'custom') && <section className={card}>
                  <h3 className="font-semibold mb-3">{copy.advanced}</h3>
                  <PolicyEditor policy={center.global_policy} definitions={center.mode_definitions} copy={copy}
                    busy={busy} inherit={false} onSave={(patch) => { void saveGlobal(patch).then(ok => { if (ok) setShowGlobalEditor(false) }) }}
                    onCancel={() => setShowGlobalEditor(false)} />
                </section>}
              </div>
            )}
            {tab === 'projects' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.projectsTitle}</h2>
                  <p className={`${faded} mt-1 mb-3`}>{copy.projectsHelp}</p>
                  <select
                    aria-label={copy.selectProject}
                    className={`${input} w-full`}
                    value={selectedProject}
                    onChange={(event) => setSelectedProject(event.target.value)}
                  >
                    <option value="">{copy.selectProject}</option>
                    {center.projects.map((item) => (
                      <option key={item.path} value={item.path}>
                        {item.name} · {item.path}
                      </option>
                    ))}
                  </select>
                  {project ? (
                    <>
                      {overrideSummary(project.policy)}
                      <details className="mt-4 border-t border-default pt-3">
                        <summary className="cursor-pointer text-sm font-medium text-accent">
                          {copy.projectAdjust}
                        </summary>
                        <div className="mt-4"><PolicyEditor policy={project.policy} definitions={center.mode_definitions}
                          copy={copy} busy={busy} inherit onSave={saveProject} /></div>
                      </details>
                    </>
                  ) : (
                    <p className={`${faded} mt-3`}>{copy.noProject}</p>
                  )}
                </section>
                {sid && (
                  <section className={card}>
                    <h2 className="font-semibold">{copy.conversationTitle}</h2>
                    <p className={`${faded} mt-2`}>{copy.conversationHelp}</p>
                    <p className="text-xs text-content-tertiary mt-1 break-all">
                      {center.project || copy.defaultWorkspace}
                    </p>
                    {overrideSummary(center.conversation_policy)}
                    <details className="mt-4 border-t border-default pt-3">
                      <summary className="cursor-pointer text-sm font-medium text-accent">
                        {copy.conversationAdjust}
                      </summary>
                      <div className="mt-4">
                        <PolicyEditor policy={center.conversation_policy} definitions={center.mode_definitions}
                          copy={copy} busy={busy} inherit onSave={saveConversation} />
                      </div>
                    </details>
                    <label className="block text-sm mt-4">
                      {copy.extraRoot}
                      <span className="block text-xs text-content-secondary mt-1">{copy.extraRootHelp}</span>
                      <div className="flex gap-2 mt-2">
                        <input
                          className={`${input} flex-1`}
                          value={extraRoot}
                          onChange={(event) => setExtraRoot(event.target.value)}
                          placeholder={copy.pathPlaceholder}
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
                          {copy.add}
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
                          {copy.remove}
                        </button>
                      </div>
                    ))}
                  </section>
                )}
              </div>
            )}
            {tab === 'connections' && (
              <div className="space-y-3">
                <div>
                  <h2 className="font-semibold">{copy.connectionsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.connectionsHelp}</p>
                </div>
                {center.connections.length === 0 && <p className={faded}>{copy.noConnections}</p>}
                {center.connections.map((connection) => (
                  <section
                    key={connection.id}
                    className={`${card} flex flex-col sm:flex-row sm:justify-between gap-4 sm:items-center`}
                  >
                    <div className="min-w-0">
                      <h3 className="font-semibold">
                        {(copy.connectionNames as Record<string, string>)[connection.id] || connection.name}
                      </h3>
                      <p className={faded}>
                        {connection.connected
                          ? `${copy.connected} · ${connection.allowed ? copy.accessAllowed : copy.accessRevoked}`
                          : copy.disconnected}
                      </p>
                      {!connection.connected && (
                        <p className="text-xs text-content-tertiary mt-1">{copy.connectInFeature}</p>
                      )}
                      {connection.connected && (
                        <p className="text-xs text-content-tertiary mt-2">
                          {copy.accessRange}
                          {copy.fieldSeparator}
                          {connection.scopes.includes('*')
                            ? copy.allOperations
                            : connection.scopes.length
                              ? connection.scopes
                                  .map((scope) => (copy.operations as Record<string, string>)[scope] || scope)
                                  .join(copy.listSeparator)
                              : copy.allOperations}
                        </p>
                      )}
                      {connection.connected && (
                        <p className="text-xs text-content-tertiary">
                          {copy.lastAccess}
                          {copy.fieldSeparator}
                          {connection.last_access
                            ? new Date(connection.last_access * 1000).toLocaleString(
                                getLang() === 'en' ? 'en-US' : 'zh-CN',
                              )
                            : copy.never}
                        </p>
                      )}
                    </div>
                    {connection.connected && (
                      <button
                        disabled={busy}
                        className={connection.allowed ? input : action}
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
                        {connection.allowed ? copy.revoke : copy.restore}
                      </button>
                    )}
                  </section>
                ))}
              </div>
            )}
            {tab === 'secrets' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.secretsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.secretsHelp}</p>
                  <div className="mt-3 divide-y divide-default">
                    {center.secrets.length === 0 && <p className={`${faded} py-3`}>{copy.noSecrets}</p>}
                    {center.secrets.map((item) => (
                      <div key={item.name} className="flex justify-between items-center gap-3 py-3 text-sm">
                        <div className="min-w-0">
                          <p className="font-medium">{securitySecretName(copy, item.name)}</p>
                          <p className="text-xs text-content-secondary mt-0.5">
                            <code>{item.name}</code> · {copy.source}
                            {copy.fieldSeparator}
                            {(copy.secretSources as Record<string, string>)[item.source] ||
                              copy.secretSources['credential store']}
                          </p>
                        </div>
                        <button
                          disabled={busy}
                          className="text-danger shrink-0"
                          aria-label={`${copy.deleteSecret} ${item.name}`}
                          onClick={() => void mutate(() => apiClient.deleteSecuritySecret(item.name))}
                        >
                          {copy.deleteSecret}
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-2 mt-4">
                    <select
                      className={input}
                      aria-label={copy.selectService}
                      value={secretName}
                      onChange={(event) => setSecretName(event.target.value)}
                    >
                      <option value="">{copy.selectService}</option>
                      {commonCredentials.map(([name]) => (
                        <option key={name} value={name}>
                          {securitySecretName(copy, name)}
                        </option>
                      ))}
                      <option value="other">{copy.otherCredential}</option>
                    </select>
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={input}
                      aria-label={copy.secretValue}
                      placeholder={copy.secretValue}
                      value={secretValue}
                      onChange={(event) => setSecretValue(event.target.value)}
                    />
                    <button
                      disabled={busy || !credentialName || !secretValue}
                      className={action}
                      onClick={() => {
                        void mutate(() => apiClient.saveSecuritySecret(credentialName, secretValue)).then(
                          (ok) => {
                            if (ok) setSecretValue('')
                          },
                        )
                      }}
                    >
                      {copy.saveSecret}
                    </button>
                  </div>
                  {secretName === 'other' && (
                    <label className="block text-xs text-content-secondary mt-3">
                      {copy.customCredentialName}
                      <input
                        className={`${input} block w-full mt-1`}
                        value={customSecretName}
                        onChange={(event) => setCustomSecretName(event.target.value.toUpperCase())}
                      />
                      <span className="block mt-1">{copy.secretNameHelp}</span>
                    </label>
                  )}
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.appPassword}</h2>
                  <p className={`${faded} mt-1`}>{copy.appPasswordHelp}</p>
                  <p className="text-xs text-content-tertiary mt-2">
                    {center.summary.app_password_set ? copy.configured : copy.notConfigured}
                  </p>
                  <div className="flex gap-2 mt-3">
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${input} flex-1`}
                      aria-label={copy.newPassword}
                      placeholder={copy.newPassword}
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
                      {copy.changePassword}
                    </button>
                  </div>
                </section>
              </div>
            )}
            {tab === 'activity' && (
              <section className={card}>
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 mb-3">
                  <div>
                    <h2 className="font-semibold">{copy.activityTitle}</h2>
                    <p className={`${faded} mt-1`}>{copy.activityHelp}</p>
                  </div>
                  <button
                    type="button"
                    className="text-xs text-accent shrink-0 self-end"
                    onClick={() => {
                      setFilters({})
                      setSinceDraft('')
                    }}
                  >
                    {copy.clearFilters}
                  </button>
                </div>
                <div className="grid sm:grid-cols-3 gap-3 mb-4">
                  <label className="text-xs text-content-secondary">
                    {copy.filterAgent}
                    <select
                      className={`${input} w-full mt-1`}
                      value={filters.agent || ''}
                      onChange={(event) => setFilters({ ...filters, agent: event.target.value })}
                    >
                      <option value="">{copy.all}</option>
                      {[...new Set(availableEvents.map((event) => event.agent))].map((agent) => (
                        <option key={agent} value={agent}>
                          {agent === 'default' ? 'Stella' : agent}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {copy.filterProject}
                    <select
                      className={`${input} w-full mt-1`}
                      value={filters.project || ''}
                      onChange={(event) => setFilters({ ...filters, project: event.target.value })}
                    >
                      <option value="">{copy.all}</option>
                      {center.projects.map((item) => (
                        <option key={item.path} value={item.path}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {copy.filterTool}
                    <select
                      className={`${input} w-full mt-1`}
                      value={filters.tool || ''}
                      onChange={(event) => setFilters({ ...filters, tool: event.target.value })}
                    >
                      <option value="">{copy.all}</option>
                      {[...new Set(availableEvents.map((event) => event.tool))].map((tool) => (
                        <option key={tool} value={tool}>
                          {(copy.tools as Record<string, string>)[tool] || tool}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {copy.filterRisk}
                    <select
                      className={`${input} w-full mt-1`}
                      value={filters.risk || ''}
                      onChange={(event) => setFilters({ ...filters, risk: event.target.value })}
                    >
                      <option value="">{copy.all}</option>
                      {(['L0', 'L1', 'L2', 'L3', 'L4'] as const).map((risk) => (
                        <option key={risk} value={risk}>
                          {copy.risk[risk]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {copy.filterDecision}
                    <select
                      className={`${input} w-full mt-1`}
                      value={filters.decision || ''}
                      onChange={(event) => setFilters({ ...filters, decision: event.target.value })}
                    >
                      <option value="">{copy.all}</option>
                      {(
                        [
                          'allow',
                          'confirm',
                          'deny',
                          'policy_change',
                          'secret_use',
                          'external_access',
                        ] as const
                      ).map((outcome) => (
                        <option key={outcome} value={outcome}>
                          {copy.outcomes[outcome]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {copy.filterSince}
                    <input
                      type="text"
                      inputMode="numeric"
                      className={`${input} w-full mt-1`}
                      placeholder={copy.datePlaceholder}
                      value={sinceDraft}
                      onChange={(event) => {
                        const value = event.target.value.trim()
                        setSinceDraft(value)
                        if (
                          !value ||
                          (/^\d{4}-\d{2}-\d{2}$/.test(value) &&
                            !Number.isNaN(new Date(value + 'T00:00:00').getTime()))
                        ) {
                          setFilters({ ...filters, since: value })
                        }
                      }}
                    />
                  </label>
                </div>
                {eventList(records)}
              </section>
            )}
          </>
        )}
      </div>
      </div>
    </div>
  )
}
export default SecurityPage
