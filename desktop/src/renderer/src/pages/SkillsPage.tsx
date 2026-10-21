import { Card, Grid } from '../components/CapabilityCards'
import React, { useCallback, useEffect, useState } from 'react'
import { ChevronDown, Loader2, Puzzle } from 'lucide-react'
import { getLang, t } from '../i18n'
import apiClient from '../api/client'
import type { LocalizedCopy, SkillInfo, ToolInfo, McpServerInfo } from '../types'
import { Toggle } from './settings/primitives'
import { SKILL_HUB_URL } from './settings/links'
import { useLocation, useNavigate } from 'react-router-dom'
import PluginCapabilities from './PluginCapabilities'
import PluginSettings from './settings/PluginSettings'
import { Link } from 'react-router-dom'
import type { SettingsOrigin } from './settings/origin'
import PageHeader from '../components/PageHeader'
import CapabilityRefreshButton from '../components/CapabilityRefreshButton'

interface SkillsPageProps {
  baseUrl: string
}

const copyOf = (value: LocalizedCopy | null | undefined) => value?.[getLang() === 'en' ? 'en' : 'zh'] || ''

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const tabs = [
    { id: 'plugins', label: t('menu_plugins') },
    { id: 'tools', label: t('tools_section_title') },
    { id: 'skills', label: t('skills_section_title') },
    { id: 'mcp', label: 'MCP' },
  ]
  const requestedTab = new URLSearchParams(location.search).get('tab') || location.hash.slice(1)
  const params = new URLSearchParams(location.search)
  const origin = location.state as SettingsOrigin | null
  const showPluginSettings = params.get('view') === 'settings'
  const activeTab = tabs.some(tab => tab.id === requestedTab) ? requestedTab : 'plugins'
  const selectTab = (id: string) => {
    navigate(`/skills?tab=${id}`, { replace: true })
    document.querySelector('[data-stella-scroll]')?.scrollTo(0, 0)
  }
  const [servers, setServers] = useState<McpServerInfo[]>([])
  const [mcpError, setMcpError] = useState('')
  const [openServer, setOpenServer] = useState('')
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [toolsError, setToolsError] = useState('')
  const [skillsError, setSkillsError] = useState('')
  const [skillBusy, setSkillBusy] = useState(false)
  const [toolBusy, setToolBusy] = useState<string | null>(null)
  const [mcpBusy, setMcpBusy] = useState<string | null>(null)
  const [toolSaveError, setToolSaveError] = useState('')
  const [skillSaveError, setSkillSaveError] = useState('')
  const [mcpSaveError, setMcpSaveError] = useState('')
  const [toolsLoading, setToolsLoading] = useState(true)
  const [skillsLoading, setSkillsLoading] = useState(true)
  const [mcpLoading, setMcpLoading] = useState(true)

  const loadTools = useCallback(async () => {
    setToolsLoading(true)
    try {
      setTools(await apiClient.getTools())
      setToolsError('')
    } catch (err) {
      setToolsError(err instanceof Error ? err.message : String(err))
    } finally { setToolsLoading(false) }
  }, [])

  const loadSkills = useCallback(async () => {
    setSkillsLoading(true)
    try {
      setSkills(await apiClient.getSkills())
      setSkillsError('')
    } catch (err) {
      setSkillsError(err instanceof Error ? err.message : String(err))
    } finally { setSkillsLoading(false) }
  }, [])

  const loadMcp = useCallback(async () => {
    setMcpLoading(true)
    try { setServers(await apiClient.getMcpServers()); setMcpError('') }
    catch (err) { setMcpError(err instanceof Error ? err.message : String(err)) }
    finally { setMcpLoading(false) }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadTools()
    void loadSkills()
    void loadMcp()
  }, [baseUrl, loadTools, loadSkills, loadMcp])

  const toggle = async (skill: SkillInfo, enabled: boolean) => {
    if (skillBusy) return
    setSkillBusy(true)
    setSkillSaveError('')
    setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled } : item)))
    try {
      const res = await apiClient.toggleSkill(skill.name, enabled ? 'open' : 'close')
      if (res.status !== 'success') throw new Error(res.message || t('capability_save_error'))
    } catch (err) {
      setSkillSaveError(err instanceof Error ? err.message : t('capability_save_error'))
      setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled: !enabled } : item)))
    } finally { setSkillBusy(false) }
  }

  const toggleTool = async (tool: ToolInfo, enabled: boolean) => {
    if (toolBusy || toolsLoading) return
    setToolBusy(tool.id); setToolSaveError('')
    setTools(prev => prev.map(item => item.id === tool.id ? { ...item, enabled } : item))
    try {
      const result = await apiClient.toggleTool(tool.id, enabled)
      if (result.status !== 'success') throw new Error(result.message || t('capability_save_error'))
    } catch (err) {
      setTools(prev => prev.map(item => item.id === tool.id ? { ...item, enabled: tool.enabled } : item))
      setToolSaveError(err instanceof Error ? err.message : t('capability_save_error'))
    } finally { setToolBusy(null) }
  }

  const toggleMcp = async (server: McpServerInfo, enabled: boolean) => {
    if (mcpBusy || mcpLoading) return
    setMcpBusy(server.name); setMcpSaveError('')
    setServers(prev => prev.map(item => item.name === server.name ? { ...item, enabled } : item))
    try {
      const result = await apiClient.toggleMcpServer(server.name, enabled)
      if (result.status !== 'success') throw new Error(result.message || t('capability_save_error'))
      setServers(prev => prev.map(item => item.name === server.name ? result.server : item))
    } catch (err) {
      setServers(prev => prev.map(item => item.name === server.name ? server : item))
      setMcpSaveError(err instanceof Error ? err.message : t('capability_save_error'))
    } finally { setMcpBusy(null) }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-content">{t('skills_title')}</h1>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
        <a href={SKILL_HUB_URL} target="_blank" rel="noopener noreferrer"
          className="inline-flex shrink-0 whitespace-nowrap items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft">
          <Puzzle size={12} />{t('skills_hub_btn')}
        </a>
      </PageHeader>
      <div className="border-b border-default px-4 sm:px-6">
        <div role="tablist" aria-label={t('skills_title')} className="max-w-5xl mx-auto flex gap-1 overflow-x-auto">
          {tabs.map((tab, index) => <button key={tab.id} id={`capability-tab-${tab.id}`} type="button" role="tab"
            aria-selected={activeTab === tab.id} aria-controls={`capability-panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => selectTab(tab.id)}
            onKeyDown={event => {
              let next = index
              if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
              else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
              else if (event.key === 'Home') next = 0
              else if (event.key === 'End') next = tabs.length - 1
              else return
              event.preventDefault()
              selectTab(tabs[next].id)
              document.getElementById(`capability-tab-${tabs[next].id}`)?.focus()
            }}
            className={`shrink-0 border-b-2 px-4 py-3 text-sm font-medium ${activeTab === tab.id ? 'border-accent text-accent' : 'border-transparent text-content-secondary hover:text-content'}`}>
            {tab.label}
          </button>)}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto" data-stella-scroll>
        <div role="tabpanel" id={`capability-panel-${activeTab}`} aria-labelledby={`capability-tab-${activeTab}`} tabIndex={0} className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
            <div className="space-y-10">
              {activeTab === 'tools' && <Section title={t('tools_section_title')} count={tools.length} loading={toolsLoading} refreshDisabled={!!toolBusy} onRefresh={() => void loadTools()}>
                {toolSaveError && <p role="alert" className="text-sm text-danger">{toolSaveError}</p>}
                {toolsError ? <LoadError text={toolsError || t('capability_tools_error')} onRetry={() => void loadTools()} /> : tools.length === 0 ? (
                  <Empty text={t('tools_empty')} />
                ) : (
                  <Grid>
                    {tools.map((item) => (
                      <ToolCard key={item.id} tool={item} disabled={!!toolBusy} onToggle={enabled => void toggleTool(item, enabled)} />
                    ))}
                  </Grid>
                )}
              </Section>}
              {activeTab === 'skills' && <Section title={t('skills_section_title')} count={skills.length} loading={skillsLoading} refreshDisabled={skillBusy} onRefresh={() => void loadSkills()}>
                {skillSaveError && <p role="alert" className="text-sm text-danger">{skillSaveError}</p>}
                {skillsError ? <LoadError text={skillsError || t('capability_skills_error')} onRetry={() => void loadSkills()} /> : skills.length === 0 ? (
                  <Empty text={t('skills_empty')} />
                ) : (
                  <Grid>
                    {skills.map((item) => {
                      const title = item.display_name || item.name
                      return (
                        <Card key={item.name} label={title}>
                          <div className="flex items-start justify-between gap-3">
                            <h3 className="text-sm font-semibold text-content break-words">{title}</h3>
                            <Toggle label={title} disabled={skillBusy} checked={item.enabled} onChange={(value) => void toggle(item, value)} />
                          </div>
                          <p className="text-[13px] leading-relaxed text-content-secondary whitespace-pre-wrap break-words">{item.description}</p>
                        </Card>
                      )
                    })}
                  </Grid>
                )}
              </Section>}
              {activeTab === 'plugins' && <section id="plugins" className="space-y-3 scroll-mt-4">
                {showPluginSettings ? <div className="space-y-5">
                  <Link className="inline-block text-sm text-accent" to={origin?.from || "/skills?tab=plugins"} state={origin ? { restoreScroll: origin.scroll } : undefined}>{origin ? t('settings_return') : getLang() === 'zh' ? '返回插件' : 'Back to plugins'}</Link>
                  <PluginSettings baseUrl={baseUrl} pluginId={params.get('plugin')} onPluginChange={plugin => navigate(`/skills?tab=plugins&view=settings&plugin=${encodeURIComponent(plugin)}`, { replace: true, state: location.state })} />
                </div> : <PluginCapabilities baseUrl={baseUrl} />}
              </section>}
              {activeTab === 'mcp' && <Section title="MCP" count={servers.length} loading={mcpLoading} refreshDisabled={!!mcpBusy} onRefresh={() => void loadMcp()}>
                {mcpSaveError && <p role="alert" className="text-sm text-danger">{mcpSaveError}</p>}
                {mcpError ? <LoadError text={mcpError} onRetry={() => void loadMcp()} /> : !servers.length ? (
                  <Empty text={t('capability_mcp_empty')} />
                ) : <Grid>{servers.map(server => <Card key={server.name} label={server.name}>
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="min-w-0 text-sm font-semibold text-content break-all">{server.name}</h3>
                    <Toggle label={server.name} checked={server.enabled} disabled={!!mcpBusy}
                      onChange={enabled => void toggleMcp(server, enabled)} />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-content-tertiary">{server.transport}</p>
                    <span className={`text-xs ${server.state === 'failed' ? 'text-danger' : 'text-content-secondary'}`}>
                      {t(`capability_mcp_${server.enabled ? server.state : 'disabled'}`)}
                    </span>
                  </div>
                  {server.settings_url && ['/email', '/elearning'].includes(server.settings_url) && (
                    <a href={`#${server.settings_url}`} className="text-sm text-accent hover:underline">{t('menu_settings')}</a>
                  )}
                  <button type="button" aria-expanded={openServer === server.name} aria-controls={`mcp-tools-${server.name}`}
                    onClick={() => setOpenServer(openServer === server.name ? '' : server.name)}
                    className="inline-flex items-center gap-1 self-start text-xs text-content-secondary">
                    {t('capability_mcp_tools')} ({server.tools.length})<ChevronDown size={13} />
                  </button>
                  {openServer === server.name && <div id={`mcp-tools-${server.name}`} className="border-t border-default pt-2 space-y-3">
                    {!server.tools.length && <Empty text={t('capability_mcp_no_tools')} />}
                    {server.tools.map(tool => <div key={tool.name}>
                      <h4 className="text-xs font-semibold text-content break-all">{tool.name}</h4>
                      <p className="text-[13px] text-content-secondary whitespace-pre-wrap break-words">{tool.description}</p>
                    </div>)}
                  </div>}
                </Card>)}</Grid>}
              </Section>}
            </div>
        </div>
      </div>
    </div>
  )
}

const ToolCard: React.FC<{ tool: ToolInfo; disabled: boolean; onToggle: (enabled: boolean) => void }> = ({ tool, disabled, onToggle }) => (
  <Card label={tool.id}>
    <div className="flex items-start justify-between gap-3">
      <h3 className="font-mono text-[13px] font-semibold text-content break-all">{tool.id}</h3>
      <Toggle label={tool.id} checked={tool.enabled} disabled={disabled} onChange={onToggle} />
    </div>
    <p className="text-[13px] leading-relaxed text-content-secondary whitespace-pre-wrap break-words">{copyOf(tool.intro)}</p>
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-content-tertiary">
      <span>{tool.source?.type === 'plugin' ? `${t('menu_plugins')} · ${tool.source.plugin_ids.join(' / ')}` : 'Core'}</span>
      <span>{t(!tool.enabled ? 'capability_disabled' : tool.available ? 'capability_tool_available' : 'capability_tool_unavailable')}</span>
    </div>
  </Card>
)

const Section: React.FC<{ title: string; count: number; loading: boolean; refreshDisabled?: boolean; onRefresh: () => void; children: React.ReactNode }> = ({ title, count, loading, refreshDisabled, onRefresh, children }) => (
  <section className="space-y-3">
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-content">{title}</h2>
        {count > 0 && <span className="text-xs text-content-tertiary tabular-nums">{count}</span>}
      </div>
      <CapabilityRefreshButton loading={loading} disabled={refreshDisabled} onRefresh={onRefresh} />
    </div>
    {loading ? <div role="status" className="flex items-center justify-center py-20 text-content-tertiary">
      <Loader2 size={18} className="animate-spin mr-2" />{t('skills_loading')}
    </div> : children}
  </section>
)

const LoadError: React.FC<{ text: string; onRetry: () => void }> = ({ text, onRetry }) => (
  <div role="alert" className="rounded-card border border-default p-4 space-y-2">
    <p className="text-sm text-danger">{text}</p>
    <button type="button" onClick={onRetry} className="text-sm text-accent">{t('capability_retry')}</button>
  </div>
)

const Empty: React.FC<{ text: string }> = ({ text }) => <p className="text-sm text-content-tertiary">{text}</p>

export default SkillsPage
