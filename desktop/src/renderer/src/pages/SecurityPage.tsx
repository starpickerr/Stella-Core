import React, { useCallback, useEffect, useState } from 'react'
import { ShieldCheck, RefreshCw, ChevronRight, SlidersHorizontal, Clock3, Link2, KeyRound, Activity, Database, LockKeyhole, ArrowUpRight, type LucideIcon } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import type { InheritedMcpGrant, SecurityActivityCounts, SecurityCenterState, SecurityPolicy, SecurityRecord } from '../api/client'
import { getLang } from '../i18n'
import PluginSettings from './settings/PluginSettings'
import PageHeader from '../components/PageHeader'
import { useSessionStore } from '../store/sessionStore'
import { SECURITY_POLICY_CHANGED } from '../store/securityPolicyEvents'
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

const tabs = ['overview', 'permissions', 'background', 'connections', 'secrets', 'activity', 'privacy', 'plugins'] as const
type Tab = (typeof tabs)[number]
const tabIcons: Record<Tab, LucideIcon> = {
  overview: ShieldCheck, permissions: SlidersHorizontal, background: Clock3,
  connections: Link2, secrets: KeyRound, activity: Activity, privacy: Database, plugins: LockKeyhole,
}

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
const card = 'min-w-0 rounded-card border border-default bg-surface p-5 sm:p-6'
const overviewCard = `${card} shadow-sm`
const metricValue = 'text-3xl font-semibold tracking-tight tabular-nums leading-none'
const heading = 'text-base font-semibold text-content leading-snug'
const input =
  'min-w-0 min-h-10 rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content hover:border-strong focus-visible:outline-2 focus-visible:outline-accent'
const action =
  'min-h-10 shrink-0 rounded-btn bg-accent text-accent-contrast px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:bg-surface-2 disabled:text-content-tertiary focus-visible:outline-2 focus-visible:outline-accent'
const faded = 'text-sm leading-relaxed text-content-secondary'

const McpGrantEditor: React.FC<{ grant: InheritedMcpGrant; busy: boolean; onSave: (value: Parameters<typeof apiClient.updateMcpAccess>[0]) => void }> = ({ grant, busy, onSave }) => {
  const en = getLang() === 'en'
  const [allowed, setAllowed] = useState(!grant.revoked)
  const [purposes, setPurposes] = useState(grant.purposes.join(', '))
  const [resources, setResources] = useState(JSON.stringify(grant.resources, null, 2))
  const [expiry, setExpiry] = useState(grant.valid_until || '')
  const [error, setError] = useState('')
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    try {
      const parsed: unknown = JSON.parse(resources)
      if (!Array.isArray(parsed) || parsed.some(row => !row || typeof row.kind !== 'string' || typeof row.id !== 'string')) throw new Error(en ? 'Invalid resource list' : '资源列表格式错误')
      if (!window.confirm(en ? 'Apply these authorization changes?' : '确认应用此授权范围？')) return
      setError('')
      onSave({ id: grant.id, revision: grant.revision, revoked: !allowed, purposes: purposes.split(',').map(value => value.trim()).filter(Boolean), resources: parsed, valid_until: expiry || null })
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }
  const state = grant.revoked ? (en ? 'Revoked' : '已撤销') : grant.valid_until && Date.parse(grant.valid_until) <= Date.now() ? (en ? 'Expired' : '已过期') : (en ? 'Active' : '有效')
  return <form onSubmit={submit} data-testid={'mcp-grant-' + grant.id} className="space-y-3 border-t border-default py-4 text-sm">
    <div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{grant.server} · {grant.consumer || (en ? 'Parent authorization' : '父级授权')}</span><span>{state}</span></div>
    <p className="break-all text-content-secondary">{[...grant.capabilities, ...grant.methods].join(' · ')}</p>
    <label className="flex items-center gap-2"><input type="checkbox" checked={allowed} disabled={busy} onChange={event => setAllowed(event.target.checked)} />{en ? 'Allow this authorization' : '允许使用此授权'}</label>
    <details><summary className="cursor-pointer text-accent">{en ? 'Scope and validity' : '使用范围与有效期'}</summary><div className="mt-3 grid gap-3">
      <label className="grid gap-1">{en ? 'Purposes (comma separated)' : '用途（英文逗号分隔）'}<input className={input} value={purposes} disabled={busy} onChange={event => setPurposes(event.target.value)} /></label>
      {grant.scoped && <><label className="grid gap-1">{en ? 'Resource references (JSON)' : '资源引用（JSON）'}<textarea className={input} rows={3} value={resources} disabled={busy} onChange={event => setResources(event.target.value)} /></label>
      <label className="grid gap-1">{en ? 'Expiry (ISO date with timezone; empty for no expiry)' : '到期时间（含时区的 ISO 日期，留空为不限时）'}<input className={input} placeholder="2026-12-31T23:59:59+08:00" value={expiry} disabled={busy} onChange={event => setExpiry(event.target.value)} /></label></>}
    </div></details>
    {error && <p role="alert" className="text-danger">{error}</p>}
    <button className={action} disabled={busy} type="submit">{en ? 'Save authorization' : '保存授权'}</button>
  </form>
}

const SectionTitle: React.FC<{ icon: LucideIcon; to?: string; children: React.ReactNode }> = ({ icon: Icon, to, children }) => {
  const title = <>
    <span className="flex size-8 shrink-0 items-center justify-center rounded-btn bg-accent-soft text-accent">
      <Icon size={17} aria-hidden="true" />
    </span>
    <span className="min-w-0 flex-1">{children}</span>
    {to && <ChevronRight size={17} aria-hidden="true" className="shrink-0 text-content-tertiary group-hover:text-accent-active" />}
  </>
  return <h2 className={heading}>
    {to ? <Link to={to} className="group flex min-h-10 items-center gap-2.5 rounded-btn hover:text-accent-active dark:hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">{title}</Link>
      : <span className="flex items-center gap-2.5">{title}</span>}
  </h2>
}

const OverviewMetrics: React.FC<{ items: { label: string; value: React.ReactNode }[] }> = ({ items }) => (
  <dl className="grid grid-cols-3 divide-x divide-default">
    {items.map(item => <div key={item.label} className="min-w-0 px-3 first:pl-0 last:pr-0">
      <dt className="min-h-10 text-xs leading-5 text-content-secondary">{item.label}</dt>
      <dd className={`${typeof item.value === 'number' ? metricValue : 'text-sm font-medium leading-5'} mt-1`}>{item.value}</dd>
    </div>)}
  </dl>
)

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
  const location = useLocation()
  const navigate = useNavigate()
  const requestedTab = new URLSearchParams(location.search).get('tab')
  const tab: Tab = (tabs as readonly string[]).includes(requestedTab || '') ? requestedTab as Tab : 'overview'
  const setTab = (next: Tab) => navigate(next === 'overview' ? '/security' : `/security?tab=${next}`)
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
  useEffect(() => {
    const onPolicyChanged = () => { void load() }
    window.addEventListener(SECURITY_POLICY_CHANGED, onPolicyChanged)
    return () => window.removeEventListener(SECURITY_POLICY_CHANGED, onPolicyChanged)
  }, [load])
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
    // Global defaults only store product presets. Do not carry legacy custom
    // fields (base_preset / rule overrides) from an older global snapshot.
    return mutate(() =>
      apiClient.saveSecurityPolicy('global', {
        preset: patch.preset,
        rules: {},
        connections: patch.connections || center.global_policy.connections || {},
      }),
    )
  }
  const project = center?.projects.find((item) => item.path === selectedProject)
  const credentialName = secretName === 'other' ? customSecretName.trim().toUpperCase() : secretName
  const requestedSecret = new URLSearchParams(location.search).get('secret') || ''
  useEffect(() => { setSecretName(requestedSecret); setSecretValue('') }, [requestedSecret])
  const credentialOptions = [...new Set([
    ...commonCredentials.map(([name]) => name),
    ...(center?.secrets.map(item => item.name) || []),
    ...(secretName && secretName !== 'other' ? [secretName] : []),
  ])]
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
      className="h-full flex flex-col min-h-0 min-w-0"
    >
      <PageHeader className="flex justify-between items-start gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-card bg-accent-soft text-accent">
              <ShieldCheck size={23} aria-hidden="true" />
            </span>
            {copy.title}
          </h1>
          <p className={`${faded} mt-2`}>{copy.subtitle}</p>
        </div>
        <button type="button" className={`${input} shrink-0`} aria-label={copy.refresh} title={copy.refresh} onClick={() => void load()}>
          <RefreshCw size={17} />
        </button>
      </PageHeader>
      <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 py-5 sm:py-6">
      <div className="max-w-5xl mx-auto space-y-6">
        <nav aria-label={copy.title} className="flex gap-1 overflow-x-auto border-b border-default pb-3">
          {tabs.map((name) => {
            const Icon = tabIcons[name]
            return (
            <button
              type="button"
              key={name}
              onClick={() => setTab(name)}
              aria-current={tab === name ? 'page' : undefined}
              className={`flex items-center gap-2 shrink-0 min-h-10 px-3 py-2 rounded-btn text-sm focus-visible:outline-2 focus-visible:outline-accent ${tab === name ? 'bg-accent-soft text-content font-semibold' : 'text-content-secondary hover:bg-surface-2'}`}
            >
              <Icon size={16} aria-hidden="true" className={tab === name ? 'text-accent' : 'text-content-tertiary'} />
              {copy.tabs[name]}
            </button>
          )})}
        </nav>
        {notice && (
          <p role="status" className="rounded-btn border border-default bg-accent-soft px-4 py-3 text-sm text-content">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-btn border border-danger-border bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
        )}
        {!center ? (
          <p className={faded}>{copy.loading}</p>
        ) : (
          <>
            {tab === 'overview' && (() => {
              const globalMode = center.global_policy?.preset || 'workspace-write'
              const taskSummary = center.summary.background_tasks
              const connectionPreview = center.connections.slice(0, 3)
              const secretPreview = center.secrets.slice(0, 4)
              const dataResources = center.data_access?.resources || []
              return (
              <div className="grid lg:grid-cols-2 gap-4 sm:gap-5">
                <section className={`${overviewCard} lg:col-span-2 flex flex-col lg:flex-row lg:items-center gap-5 lg:gap-8`}>
                  <div className="min-w-0 flex-1">
                    <SectionTitle icon={ShieldCheck} to="/security?tab=permissions">{copy.presetsTitle}</SectionTitle>
                    <p className={`${faded} mt-3`}>{copy.overviewDefaultHelp}</p>
                  </div>
                  <div className="shrink-0 rounded-btn bg-accent-soft px-5 py-4 lg:min-w-52">
                    <p className="text-xs text-content-secondary">{copy.currentProtection}</p>
                    <p className="text-2xl font-semibold tracking-tight mt-1.5">{modeLabel(copy, globalMode)}</p>
                  </div>
                </section>
                <section className={overviewCard}>
                  <SectionTitle icon={Clock3} to="/security?tab=background">{copy.overviewBackgroundTitle}</SectionTitle>
                  {!taskSummary || taskSummary.available === false ? (
                    <p className={`${faded} mt-4`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-5">
                      <OverviewMetrics items={[
                        { label: copy.overviewTotalTasks, value: taskSummary.total ?? copy.overviewUnavailable },
                        { label: copy.backgroundEnabled, value: taskSummary.enabled ?? copy.overviewUnavailable },
                        { label: copy.backgroundPaused, value: taskSummary.paused ?? copy.overviewUnavailable },
                      ]} />
                      {taskSummary.modes && (
                        <div className="mt-5 border-t border-default pt-3 flex flex-wrap gap-x-3 gap-y-2 text-xs leading-5 text-content-secondary">
                          {(['read-only', 'workspace-write', 'full-access', 'custom'] as const).map((mode) => (
                            <span key={mode}>
                              {modeLabel(copy, mode)} <span className="font-medium tabular-nums text-content">{taskSummary.modes?.[mode] ?? 0}</span>
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
                <section className={overviewCard}>
                  <SectionTitle icon={Link2} to="/security?tab=connections">{copy.overviewConnectionsTitle}</SectionTitle>
                  <div className="mt-5 mb-4 flex items-end gap-2">
                    <p className={metricValue}>
                      {typeof center.summary.connection_count === 'number'
                        ? center.summary.connection_count
                        : copy.overviewUnavailable}
                    </p>
                    <span className="pb-0.5 text-xs text-content-secondary">{copy.connectionsCount}</span>
                  </div>
                  <div className="divide-y divide-default border-t border-default text-sm">
                    {connectionPreview.map((item) => (
                      <div key={item.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2.5">
                        <span className="min-w-0 font-medium break-words">{(copy.connectionNames as Record<string, string>)[item.id] || item.name}</span>
                        <span className="inline-flex items-center gap-1.5 text-xs text-content-secondary">
                          <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${item.connected ? 'bg-accent' : 'bg-content-tertiary'}`} />
                          {item.connected ? copy.connected : copy.disconnected}
                          {item.connected && item.allowed === false && <> · {copy.accessRevoked}</>}
                        </span>
                      </div>
                    ))}
                    {center.connections.length === 0 && <p className={`${faded} py-3`}>{copy.noConnections}</p>}
                    {center.connections.length > 3 && (
                      <p className="pt-3 text-xs text-content-secondary">{copy.overviewMoreItems(center.connections.length - 3)}</p>
                    )}
                  </div>
                </section>
                <section className={overviewCard}>
                  <SectionTitle icon={KeyRound} to="/security?tab=secrets">{copy.overviewSecretsTitle}</SectionTitle>
                  <div className="mt-5 mb-4 flex items-end gap-2">
                    <p className={metricValue}>
                      {typeof center.summary.secret_count === 'number'
                        ? center.summary.secret_count
                        : copy.overviewUnavailable}
                    </p>
                    <span className="pb-0.5 text-xs text-content-secondary">{copy.overviewSecretCountLabel}</span>
                  </div>
                  <div className="divide-y divide-default border-t border-default text-sm">
                    {secretPreview.map((item) => (
                      <div key={item.name} className="flex items-center justify-between gap-3 py-2.5">
                        <span className="font-medium break-words min-w-0">{securitySecretName(copy, item.name, item.display_name)}</span>
                        <span className="inline-flex items-center gap-1.5 text-xs text-content-secondary shrink-0">
                          <span aria-hidden="true" className={`size-1.5 rounded-full ${item.configured ? 'bg-accent' : 'bg-content-tertiary'}`} />
                          {item.configured ? copy.configured : copy.notConfigured}
                        </span>
                      </div>
                    ))}
                    {center.secrets.length === 0 && <p className={`${faded} py-3`}>{copy.noSecrets}</p>}
                    {center.secrets.length > 4 && (
                      <p className="pt-3 text-xs text-content-secondary">{copy.overviewMoreItems(center.secrets.length - 4)}</p>
                    )}
                  </div>
                </section>
                <section className={overviewCard}>
                  <SectionTitle icon={Activity} to="/security?tab=activity">{copy.overviewActivityTitle}</SectionTitle>
                  <p className="text-xs text-content-secondary mt-3">{copy.activityStatsTitle}</p>
                  {!activityCounts ? (
                    <p className={`${faded} mt-4`}>{copy.overviewUnavailable}</p>
                  ) : (
                    <div className="mt-5">
                      <OverviewMetrics items={[
                        { label: copy.autoAllow, value: activityCounts.auto_allow },
                        { label: copy.userAuthorized, value: activityCounts.user_authorized },
                        { label: copy.deniedCount, value: activityCounts.denied },
                      ]} />
                      {activityCounts.uncertain && (
                        <p className="mt-5 border-t border-default pt-3 text-xs leading-5 text-content-secondary">{copy.activityStatsUncertain}</p>
                      )}
                    </div>
                  )}
                </section>
                <section className={`${overviewCard} lg:col-span-2`}>
                  <SectionTitle icon={Database} to="/security?tab=privacy">{copy.overviewPrivacyTitle}</SectionTitle>
                  <div className="mt-4 space-y-2 text-sm">
                    {dataResources.slice(0, 4).map(item => <p key={item.id}>{item.name} <span className="text-content-secondary">{item.provider}</span></p>)}
                    <Link className="text-accent" to="/data">{getLang() === 'zh' ? '管理数据' : 'Manage data'}</Link>
                  </div>
                </section>
              </div>
              )
            })()}
            {tab === 'permissions' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className={heading}>{copy.presetsTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.presetsHelp}</p>
                  {(center.global_policy.preset === 'custom' || center.global_policy.base_preset) && (
                    <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">{copy.presetsLegacyCustom}</p>
                  )}
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
                  <h2 className={heading}>{copy.projectsTitle}</h2>
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
                    <h2 className={heading}>{copy.conversationTitle}</h2>
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
                <h2 className={heading}>{copy.backgroundTitle}</h2>
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
                              <option value="inherit">
                                {task.unknown || !task.effective_mode
                                  ? copy.backgroundInheritUnknown
                                  : copy.backgroundInheritLabel(modeLabel(copy, task.effective_mode))}
                              </option>
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
                  <h2 className={heading}>{copy.connectionsTitle}</h2>
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
                {(center.data_access?.inherited_grants || []).length > 0 && <section className={card}>
                  <h2 className={heading}>{getLang() === 'en' ? 'Inherited MCP authorizations' : 'MCP 迁移授权'}</h2>
                  <p className={`${faded} mt-1`}>{getLang() === 'en' ? 'Existing scopes are preserved. Connection and permission policies still apply.' : '保留迁移前的授权范围；连接开关和统一权限策略仍然生效。'}</p>
                  {center.data_access?.inherited_grants?.map(grant => <McpGrantEditor key={grant.id + ':' + grant.revision} grant={grant} busy={busy} onSave={value => { void mutate(() => apiClient.updateMcpAccess(value), copy.saved) }} />)}
                </section>}
              </div>
            )}
            {tab === 'secrets' && (
              <div className="space-y-5">
                <section className={card}>
                  <SectionTitle icon={KeyRound}>{copy.secretsTitle}</SectionTitle>
                  <p className={`${faded} mt-3`}>{copy.secretsHelp}</p>
                  <div className="mt-5 divide-y divide-default border-y border-default">
                    {center.secrets.length === 0 && <p className={`${faded} py-3`}>{copy.noSecrets}</p>}
                    {center.secrets.map((item) => {
                      const custom = item.name.startsWith('CUSTOM:')
                      const title = securitySecretName(copy, item.name, item.display_name)
                      return (
                      <div key={item.name} className="flex justify-between items-center gap-3 py-4 text-sm">
                        <div className="flex items-center gap-3 min-w-0">
                          <span aria-hidden="true" className="hidden sm:flex size-10 shrink-0 items-center justify-center rounded-btn bg-surface-2 text-content-secondary font-semibold text-base">
                            {title.slice(0, 1).toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <p className="text-[15px] font-semibold break-words">{title}</p>
                            <p className="text-xs leading-relaxed text-content-secondary mt-1 break-words">
                              {(copy.secretSources as Record<string, string>)[item.source] ||
                                copy.secretSources['credential store']}
                            </p>
                          </div>
                        </div>
                        {custom ? (
                          <button type="button" aria-label={`${copy.manageSecret} ${title}`}
                            onClick={() => { setSecretName(item.name); setSecretValue('') }}
                            className={`${input} flex items-center gap-1.5 shrink-0`}>
                            {copy.manageSecret}<ArrowUpRight size={14} aria-hidden="true" />
                          </button>
                        ) : <button
                          type="button"
                          disabled={busy}
                          className="min-h-10 px-3 rounded-btn text-danger hover:bg-danger-soft shrink-0 focus-visible:outline-2 focus-visible:outline-accent"
                          aria-label={`${copy.deleteSecret} ${title}`}
                          onClick={() => void mutate(() => apiClient.deleteSecuritySecret(item.name))}
                        >
                          {copy.deleteSecret}
                        </button>}
                      </div>
                    )})}
                  </div>
                  <div className="grid lg:grid-cols-[1fr_1fr_auto] gap-3 mt-5">
                    <label className="min-w-0 text-sm font-medium">
                      {copy.selectService}
                    <select
                      className={`${input} block w-full mt-2 font-normal`}
                      aria-label={copy.selectService}
                      value={secretName}
                      onChange={(event) => { setSecretName(event.target.value); setSecretValue('') }}
                    >
                      <option value="">{copy.selectService}</option>
                      {credentialOptions.map((name) => (
                        <option key={name} value={name}>
                          {securitySecretName(copy, name, center.secrets.find(item => item.name === name)?.display_name)}
                        </option>
                      ))}
                      <option value="other">{copy.otherCredential}</option>
                    </select>
                    </label>
                    <>
                    <label className="min-w-0 text-sm font-medium">
                      {copy.secretValue}
                    <input
                      type="password"
                      autoComplete="new-password"
                      className={`${input} block w-full mt-2 font-normal`}
                      aria-label={copy.secretValue}
                      placeholder={copy.secretValue}
                      value={secretValue}
                      onChange={(event) => setSecretValue(event.target.value)}
                    />
                    </label>
                    <button
                      disabled={busy || !credentialName || !secretValue}
                      className={`${action} self-end`}
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
                    {credentialName && center.secrets.some(item => item.name === credentialName) && <button
                      disabled={busy} className="text-sm text-danger self-end min-h-10"
                      onClick={() => void mutate(() => apiClient.deleteSecuritySecret(credentialName))}>{copy.deleteSecret}</button>}
                    </>

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
                  <SectionTitle icon={LockKeyhole}>{copy.appPassword}</SectionTitle>
                  <p className={`${faded} mt-3`}>{copy.appPasswordHelp}</p>
                  <p className="text-xs text-content-secondary mt-3 flex items-center gap-2">
                    <span aria-hidden="true" className={`size-1.5 rounded-full ${center.summary.app_password_set ? 'bg-accent' : 'bg-content-tertiary'}`} />
                    {center.summary.app_password_set ? copy.configured : copy.notConfigured}
                  </p>
                  <div className="flex flex-col md:flex-row gap-3 mt-3">
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
                    {center.summary.app_password_set && <button type="button" disabled={busy} className={`${input} text-danger`} onClick={() => {
                      if (window.confirm(getLang() === 'zh' ? '清除访问密码？' : 'Clear the access password?')) void mutate(() => apiClient.updateConfig({ web_password: '' }))
                    }}>{getLang() === 'zh' ? '清除访问密码' : 'Clear access password'}</button>}
                  </div>
                </section>
              </div>
            )}
            {tab === 'plugins' && <PluginSettings baseUrl={baseUrl} authorizationOnly pluginId={new URLSearchParams(location.search).get('plugin')} onPluginChange={plugin => navigate(`/security?tab=plugins&plugin=${encodeURIComponent(plugin)}`, { replace: true })} />}
            {tab === 'activity' && (
              <section className={card}>
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 mb-3">
                  <div>
                    <h2 className={heading}>{copy.activityTitle}</h2>
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
                <div className="mb-3 flex justify-end"><button type="button" disabled={busy} className={`${input} text-danger`} onClick={() => {
                  if (window.confirm(copy.privacyConfirmClear)) void mutate(() => apiClient.cleanupPrivacy('clear_security_activity'), copy.saved)
                }}>{copy.privacyClearActivity}</button></div>
                {eventList(records)}
              </section>
            )}
            {tab === 'privacy' && (
              <div className="space-y-5">
                <section className={card}>
                  <h2 className={heading}>{copy.privacyTitle}</h2>
                  <p className={`${faded} mt-1`}>{copy.privacyHelp}</p>
                  <div className="mt-4 flex flex-wrap gap-4 text-sm text-accent">
                    <Link to="/data">{getLang() === 'zh' ? '管理数据' : 'Manage data'}</Link>
                    <Link to="/security?tab=connections">{getLang() === 'zh' ? '管理连接授权' : 'Manage connection access'}</Link>
                    <Link to="/security?tab=permissions">{getLang() === 'zh' ? '权限策略' : 'Permission policies'}</Link>
                  </div>
                  <div className="mt-4 divide-y divide-default">
                    {(center.data_access?.resources || []).map(item => {
                      const connection = center.connections.find(row => row.id === item.connection)
                      return <div key={item.id} className="py-3 space-y-1 text-sm">
                        <p className="font-medium">{item.name}</p>
                        <p className="text-content-secondary break-all">{item.provider} · {item.account_id}</p>
                        <p className="text-content-secondary">{getLang() === 'zh' ? '连接策略：' : 'Connection policy: '}{connection?.allowed === false ? (getLang() === 'zh' ? '已拒绝' : 'Denied') : (getLang() === 'zh' ? '依照当前权限检查' : 'Checked against current permissions')}</p>
                        <details className="text-xs text-content-secondary"><summary>{getLang() === 'zh' ? '资源标识' : 'Resource ID'}</summary><p className="mt-1 break-all">{item.id}</p></details>
                      </div>
                    })}
                  </div>
                </section>
                <section className={card}>
                  <h2 className={heading}>{copy.privacyExternalTitle}</h2>
                  <div className="mt-3 space-y-3 text-sm">
                    {(center.data_access?.external_transfers || center.privacy?.external_transfers || []).map(item => <div key={item.id}><p className="font-medium">{item.name}</p><p className="mt-1 text-content-secondary">{item.note[getLang() === 'en' ? 'en' : 'zh']}</p></div>)}
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
