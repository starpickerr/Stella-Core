import React, { useCallback, useEffect, useState } from 'react'
import { ShieldCheck, RefreshCw, ChevronRight } from 'lucide-react'
import apiClient from '../api/client'
import type { SecurityActivityCounts, SecurityCenterState, SecurityPolicy, SecurityRecord } from '../api/client'
import { getLang } from '../i18n'
import PageHeader from '../components/PageHeader'
import { useSessionStore } from '../store/sessionStore'
import type { ToolInfo } from '../types'
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

const toolTitle = (toolId: string, catalog: ToolInfo[]) => {
  const lang = getLang() === 'en' ? 'en' : 'zh'
  const match = catalog.find((item) => item.id === toolId)
  return match?.title?.[lang] || match?.title?.zh || toolId
}

const tabs = ['overview', 'permissions', 'background', 'connections', 'secrets', 'activity', 'privacy'] as const
type Tab = (typeof tabs)[number]

const modeLabel = (
  copy: ReturnType<typeof securityCopy>,
  mode: string | null | undefined,
) => {
  if (!mode) return copy.overviewUnavailable
  return (copy.presets as Record<string, { name: string }>)[mode]?.name || mode
}

const permissionSourceLabel = (
  copy: ReturnType<typeof securityCopy>,
  source: string | undefined,
) => {
  if (source === 'independent') return copy.backgroundSourceIndependent
  if (source === 'project') return copy.backgroundSourceProject
  if (source === 'conversation') return copy.backgroundSourceConversation
  if (source === 'unspecified') return copy.backgroundSourceUnspecified
  return copy.backgroundSourceUnknown
}
const DEFAULT_PRESETS = ['read-only', 'workspace-write', 'full-access'] as const
const SCOPED_PRESETS = ['read-only', 'workspace-write', 'full-access', 'custom'] as const
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
  const [activityCounts, setActivityCounts] = useState<SecurityActivityCounts | null>(null)
  const [toolCatalog, setToolCatalog] = useState<ToolInfo[]>([])
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
  const [projectDraft, setProjectDraft] = useState<SecurityPolicy | null>(null)
  const [conversationDraft, setConversationDraft] = useState<SecurityPolicy | null>(null)

  const load = useCallback(async () => {
    try {
      const queryFilters = { ...filters }
      if (queryFilters.since)
        queryFilters.since = String(Math.floor(new Date(queryFilters.since + 'T00:00:00').getTime() / 1000))
      const filtered = Object.values(filters).some(Boolean)
      const [state, events, confirmations, allEvents, tools] = await Promise.all([
        apiClient.getSecurityCenter(sid || undefined),
        apiClient.getSecurityRecords(queryFilters),
        apiClient.getSecurityConfirmations(),
        filtered ? apiClient.getSecurityRecords() : Promise.resolve(null),
        apiClient.getTools().catch(() => [] as ToolInfo[]),
      ])
      if (state.status !== 'success') throw new Error(copy.loading)
      setCenter(state)
      setRecords(events.records)
      setAvailableEvents(allEvents?.records || events.records)
      setActivityCounts(state.summary.activity_counts || events.counts || null)
      setToolCatalog(tools)
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
  useEffect(() => {
    setProjectDraft(project ? { ...project.policy, rules: { ...(project.policy.rules || {}) } } : null)
  }, [project?.path, project?.policy])
  useEffect(() => {
    if (!center) return
    const policy = center.project ? center.project_policy : center.conversation_policy
    setConversationDraft({ ...policy, rules: { ...(policy.rules || {}) } })
  }, [center?.project, center?.project_policy, center?.conversation_policy])
  const saveProject = (patch: SecurityPolicy) => {
    if (!project) return Promise.resolve(false)
    return mutate(() =>
      apiClient.saveSecurityPolicy(
        'project',
        patch.preset === 'custom' ? patch : { preset: patch.preset, rules: {}, connections: patch.connections || {} },
        { project: project.path, session: sid || undefined },
      ),
      center?.project ? copy.projectAffectsAll : copy.saved,
    )
  }
  const saveConversation = (patch: SecurityPolicy) => {
    if (!sid || !center) return Promise.resolve(false)
    const targetPolicy =
      patch.preset === 'custom' ? patch : { preset: patch.preset, rules: {}, connections: patch.connections || {} }
    return mutate(
      () => apiClient.saveSecurityPolicy('conversation', targetPolicy, { session: sid }),
      center.project ? copy.projectAffectsAll : copy.saved,
    )
  }
  const renderScopedPresets = (
    draft: SecurityPolicy | null,
    setDraft: (value: SecurityPolicy) => void,
    onSave: (patch: SecurityPolicy) => void | Promise<boolean>,
    help: string,
  ) => {
    if (!draft || !center) return null
    const active = draft.preset === 'custom' ? 'custom' : draft.preset
    return (
      <div className="mt-4 space-y-4">
        <p className={faded}>{help}</p>
        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-2">
          {center.mode_definitions
            .filter((entry) => (SCOPED_PRESETS as readonly string[]).includes(entry.id))
            .map((entry) => (
              <button
                type="button"
                key={entry.id}
                disabled={busy}
                onClick={() => {
                  if (entry.id === 'custom') {
                    const base = draft.base_preset || (draft.preset !== 'custom' ? draft.preset : 'workspace-write')
                    const baseRules =
                      center.mode_definitions.find((row) => row.id === base)?.rules || center.effective_rules
                    setDraft({
                      preset: 'custom',
                      base_preset: base,
                      rules: { ...(Object.keys(draft.rules || {}).length ? draft.rules : baseRules) },
                      connections: draft.connections || {},
                      extra_roots: draft.extra_roots,
                    })
                    return
                  }
                  setDraft({ preset: entry.id, rules: {}, connections: draft.connections || {}, extra_roots: draft.extra_roots })
                }}
                aria-pressed={active === entry.id}
                className={`px-4 py-3 rounded-btn text-left border min-h-24 ${active === entry.id ? 'border-accent bg-accent-soft' : 'border-default hover:bg-surface-2'}`}
              >
                <span className="font-semibold text-sm">{entry.name[getLang() === 'en' ? 'en' : 'zh']}</span>
                <span className="block text-xs text-content-secondary mt-2 leading-relaxed">
                  {entry.description[getLang() === 'en' ? 'en' : 'zh']}
                </span>
              </button>
            ))}
        </div>
        {draft.preset === 'custom' ? (
          <PolicyEditor
            policy={draft}
            definitions={center.mode_definitions}
            copy={copy}
            busy={busy}
            inherit={false}
            onSave={(patch) => {
              void onSave(patch)
            }}
            onCancel={() => void load()}
          />
        ) : (
          <button type="button" disabled={busy} className={action} onClick={() => void onSave(draft)}>
            {copy.savePermission}
          </button>
        )}
      </div>
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
          const eventLabel = (copy.events as Record<string, string>)[item.event]
          const namedTool = toolTitle(item.tool, toolCatalog)
          const event =
            item.event === 'tool_decision' || !eventLabel
              ? namedTool
              : eventLabel
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
            {tab === 'overview' && (() => {
              const lang = getLang() === 'en' ? 'en' : 'zh'
              const globalMode = center.global_policy?.preset || 'workspace-write'
              const taskSummary = center.summary.background_tasks
              const connectionPreview = center.connections.slice(0, 3)
              const secretPreview = center.secrets.slice(0, 4)
              const privacyCats = center.privacy?.available === false
                ? null
                : (center.privacy?.categories || []).slice(0, 4)
              return (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.presetsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.overviewDefaultHelp}</p>
                  <p className="font-medium mt-3">{modeLabel(copy, globalMode)}</p>
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.overviewBackgroundTitle}</h2>
                  {!taskSummary || taskSummary.available === false ? (
                    <p className={`${faded} mt-2`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                      <div>
                        <span className="text-content-secondary">{copy.backgroundTitle}</span>
                        <p className="font-medium mt-1">{taskSummary.total ?? copy.overviewUnavailable}</p>
                      </div>
                      <div>
                        <span className="text-content-secondary">{copy.backgroundEnabled}</span>
                        <p className="font-medium mt-1">{taskSummary.enabled ?? copy.overviewUnavailable}</p>
                      </div>
                      <div>
                        <span className="text-content-secondary">{copy.backgroundPaused}</span>
                        <p className="font-medium mt-1">{taskSummary.paused ?? copy.overviewUnavailable}</p>
                      </div>
                      {taskSummary.modes && (
                        <div className="sm:col-span-3 text-xs text-content-secondary">
                          {(['read-only', 'workspace-write', 'full-access', 'custom'] as const).map((mode) => (
                            <span key={mode} className="mr-3">
                              {modeLabel(copy, mode)}：{taskSummary.modes?.[mode] ?? 0}
                            </span>
                          ))}
                          {(taskSummary.unknown || 0) > 0 && (
                            <span>{copy.overviewUnknownPermissions(taskSummary.unknown || 0)}</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.overviewConnectionsTitle}</h2>
                  <p className="font-medium mt-2">
                    {typeof center.summary.connection_count === 'number'
                      ? center.summary.connection_count
                      : copy.overviewUnavailable}
                  </p>
                  <div className="mt-3 space-y-2 text-sm">
                    {connectionPreview.map((item) => (
                      <div key={item.id} className="flex justify-between gap-3">
                        <span>{item.name}</span>
                        <span className="text-content-secondary">
                          {(item.available ?? item.connected)
                            ? (getLang() === 'en' ? 'Connected' : '已连接')
                            : (getLang() === 'en' ? 'Unavailable' : '不可用')}
                          {' · '}
                          {item.allowed === false
                            ? (getLang() === 'en' ? 'Paused' : '已暂停')
                            : (getLang() === 'en' ? 'Allowed' : '允许使用')}
                        </span>
                      </div>
                    ))}
                    {center.connections.length > 3 && (
                      <p className="text-xs text-content-secondary">{copy.overviewMoreItems(center.connections.length - 3)}</p>
                    )}
                  </div>
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.overviewSecretsTitle}</h2>
                  <p className="font-medium mt-2">
                    {typeof center.summary.secret_count === 'number'
                      ? center.summary.secret_count
                      : copy.overviewUnavailable}
                  </p>
                  <div className="mt-3 space-y-2 text-sm">
                    {secretPreview.map((item) => (
                      <div key={item.name} className="flex justify-between gap-3">
                        <span>{securitySecretName(copy, item.name)}</span>
                        <span className="text-content-secondary">
                          {item.configured
                            ? (getLang() === 'en' ? 'Configured' : '已配置')
                            : (getLang() === 'en' ? 'Missing' : '未配置')}
                        </span>
                      </div>
                    ))}
                    {center.secrets.length > 4 && (
                      <p className="text-xs text-content-secondary">{copy.overviewMoreItems(center.secrets.length - 4)}</p>
                    )}
                  </div>
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.overviewActivityTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.activityStatsTitle}</p>
                  {!activityCounts ? (
                    <p className={`${faded} mt-2`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                      <div>
                        <span className="text-content-secondary">{copy.autoAllow}</span>
                        <p className="font-medium mt-1">{activityCounts.auto_allow}</p>
                      </div>
                      <div>
                        <span className="text-content-secondary">{copy.userAuthorized}</span>
                        <p className="font-medium mt-1">{activityCounts.user_authorized}</p>
                      </div>
                      <div>
                        <span className="text-content-secondary">{copy.deniedCount}</span>
                        <p className="font-medium mt-1">{activityCounts.denied}</p>
                      </div>
                      {activityCounts.uncertain && (
                        <p className="sm:col-span-3 text-xs text-content-secondary">{copy.activityStatsUncertain}</p>
                      )}
                    </div>
                  )}
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.overviewPrivacyTitle}</h2>
                  {!privacyCats ? (
                    <p className={`${faded} mt-2`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-3 space-y-2 text-sm">
                      {privacyCats.map((item) => (
                        <div key={item.id} className="flex justify-between gap-3">
                          <span>{item.name[lang]}</span>
                          <span className="text-content-secondary">{copy.privacyBytes(item.bytes)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </div>
              )
            })()}
            {tab === 'permissions' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.presetsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.presetsHelp}</p>
                  <div className="mt-4 grid sm:grid-cols-2 xl:grid-cols-3 gap-2">
                    {center.mode_definitions
                      .filter((entry) => (DEFAULT_PRESETS as readonly string[]).includes(entry.id))
                      .map((entry) => (
                      <button
                        type="button"
                        key={entry.id}
                        disabled={busy}
                        onClick={() => {
                          void saveGlobal({ preset: entry.id, rules: {} })
                        }}
                        aria-pressed={center.global_policy.preset === entry.id}
                        className={`px-4 py-3 rounded-btn text-left border min-h-28 ${center.global_policy.preset === entry.id ? 'border-accent bg-accent-soft' : 'border-default hover:bg-surface-2'}`}
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
                      {renderScopedPresets(projectDraft, setProjectDraft, saveProject, copy.projectSharedHelp)}
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
                    {overrideSummary(center.project ? center.project_policy : center.conversation_policy)}
                    {renderScopedPresets(
                      conversationDraft,
                      setConversationDraft,
                      saveConversation,
                      center.project ? copy.projectSharedHelp : copy.standaloneConversationHelp,
                    )}
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
                            const base = center.project ? center.project_policy : center.conversation_policy
                            void saveConversation({
                              ...base,
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
                          onClick={() => {
                            const base = center.project ? center.project_policy : center.conversation_policy
                            void saveConversation({
                              ...base,
                              extra_roots: (center.conversation_policy.extra_roots || []).filter(
                                (item) => item !== root,
                              ),
                            })
                          }}
                        >
                          {copy.remove}
                        </button>
                      </div>
                    ))}
                  </section>
                )}
              </div>
            )}
            {tab === 'background' && (
              <section className={card}>
                <h2 className="font-semibold">{copy.backgroundTitle}</h2>
                <p className={`${faded} mt-1`}>{copy.backgroundHelp}</p>
                {(center.background_tasks || []).length === 0 ? (
                  <p className={`${faded} mt-4`}>{copy.backgroundEmpty}</p>
                ) : (
                  <div className="mt-4 divide-y divide-default">
                    {(center.background_tasks || []).map((task) => (
                      <div key={task.id} className="py-4 space-y-3 text-sm">
                        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                          <div>
                            <p className="font-medium">{task.name}</p>
                            <p className="text-content-secondary mt-1">
                              {task.enabled ? copy.backgroundEnabled : copy.backgroundPaused}
                              {' · '}
                              {permissionSourceLabel(copy, task.permission_source)}
                              {' · '}
                              {task.unknown
                                ? copy.backgroundSourceUnknown
                                : modeLabel(copy, task.effective_mode)}
                            </p>
                            <p className="text-xs text-content-secondary mt-1">
                              {task.conversation_mode === 'source'
                                ? copy.backgroundContextSource
                                : task.conversation_mode === 'reuse'
                                  ? copy.backgroundContextReuse
                                  : task.conversation_mode === 'new'
                                    ? copy.backgroundContextNew
                                    : copy.backgroundSourceUnspecified}
                            </p>
                            {task.policy_error && (
                              <p className="text-xs text-danger mt-1">{task.policy_error}</p>
                            )}
                          </div>
                          <label className="text-xs text-content-secondary shrink-0">
                            {copy.backgroundSavePermission}
                            <select
                              className={`${input} block mt-1`}
                              disabled={busy}
                              value={task.run_permission_mode || 'inherit'}
                              onChange={(event) => {
                                const value = event.target.value
                                if (!window.confirm(copy.backgroundConfirmChange)) {
                                  event.target.value = task.run_permission_mode || 'inherit'
                                  return
                                }
                                void mutate(
                                  () =>
                                    apiClient.updateTask(task.id, {
                                      run_permission_mode: value as 'read-only' | 'workspace-write' | 'full-access' | 'inherit',
                                    }),
                                  copy.saved,
                                )
                              }}
                            >
                              <option value="inherit">{copy.decisions.inherit}</option>
                              <option value="read-only">{copy.presets['read-only'].name}</option>
                              <option value="workspace-write">{copy.presets['workspace-write'].name}</option>
                              <option value="full-access">{copy.presets['full-access'].name}</option>
                            </select>
                          </label>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
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
                              : copy.undeclaredScopes}
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
                {activityCounts && (
                  <div className="mb-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                    <div className="rounded-btn bg-surface-2 px-3 py-2">
                      <span className="text-content-secondary">{copy.autoAllow}</span>
                      <p className="font-medium mt-1">{activityCounts.auto_allow}</p>
                    </div>
                    <div className="rounded-btn bg-surface-2 px-3 py-2">
                      <span className="text-content-secondary">{copy.userAuthorized}</span>
                      <p className="font-medium mt-1">{activityCounts.user_authorized}</p>
                    </div>
                    <div className="rounded-btn bg-surface-2 px-3 py-2">
                      <span className="text-content-secondary">{copy.deniedCount}</span>
                      <p className="font-medium mt-1">{activityCounts.denied}</p>
                    </div>
                    {activityCounts.uncertain && (
                      <p className="sm:col-span-3 text-xs text-content-secondary">{copy.activityStatsUncertain}</p>
                    )}
                  </div>
                )}
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
                          {toolTitle(tool, toolCatalog)}
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
            {tab === 'privacy' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className="font-semibold">{copy.privacyTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.privacyHelp}</p>
                  {center.privacy?.available === false ? (
                    <p className={`${faded} mt-4`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-4 divide-y divide-default">
                      {(center.privacy?.categories || []).map((item) => {
                        const lang = getLang() === 'en' ? 'en' : 'zh'
                        return (
                          <div key={item.id} className="py-4 text-sm space-y-2">
                            <p className="font-medium">{item.name[lang]}</p>
                            <p className="text-content-secondary break-all">
                              {copy.privacyPath}
                              {copy.fieldSeparator}
                              {item.path}
                            </p>
                            <p className="text-content-secondary">
                              {copy.privacySize}
                              {copy.fieldSeparator}
                              {copy.privacyBytes(item.bytes)}
                            </p>
                            <p className="text-content-secondary">
                              {copy.privacyRetention}
                              {copy.fieldSeparator}
                              {item.retention[lang]}
                            </p>
                            {item.id === 'conversations' && (
                              <p className="text-xs text-content-secondary">{copy.privacyManageSessions}</p>
                            )}
                            <div className="flex flex-wrap gap-2 pt-1">
                              {item.actions.includes('clear_temporary') && (
                                <button
                                  type="button"
                                  disabled={busy}
                                  className={action}
                                  onClick={() => {
                                    if (!window.confirm(copy.privacyConfirmClear)) return
                                    void mutate(() => apiClient.cleanupPrivacy('clear_temporary'), copy.saved)
                                  }}
                                >
                                  {copy.privacyClearTemp}
                                </button>
                              )}
                              {item.actions.includes('clear_security_activity') && (
                                <button
                                  type="button"
                                  disabled={busy}
                                  className={`${input} text-danger`}
                                  onClick={() => {
                                    if (!window.confirm(copy.privacyConfirmClear)) return
                                    void mutate(() => apiClient.cleanupPrivacy('clear_security_activity'), copy.saved)
                                  }}
                                >
                                  {copy.privacyClearActivity}
                                </button>
                              )}
                              {item.actions.includes('clear_runs') && (
                                <button
                                  type="button"
                                  disabled={busy}
                                  className={`${input} text-danger`}
                                  onClick={() => {
                                    if (!window.confirm(copy.privacyConfirmClear)) return
                                    void mutate(() => apiClient.cleanupPrivacy('clear_runs'), copy.saved)
                                  }}
                                >
                                  {copy.privacyClearRuns}
                                </button>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </section>
                <section className={card}>
                  <h2 className="font-semibold">{copy.privacyExternalTitle}</h2>
                  <div className="mt-3 space-y-3 text-sm">
                    {(center.privacy?.external_transfers || []).map((item) => (
                      <div key={item.id}>
                        <p className="font-medium">{item.name}</p>
                        <p className="text-content-secondary mt-1">
                          {item.note[getLang() === 'en' ? 'en' : 'zh']}
                        </p>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </>
        )}
      </div>
      </div>
    </div>
  )
}
export default SecurityPage
