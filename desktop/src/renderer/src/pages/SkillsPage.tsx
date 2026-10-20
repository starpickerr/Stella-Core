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
    setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled } : item)))
    try {
      const res = await apiClient.toggleSkill(skill.name, enabled ? 'open' : 'close')
      if (res.status !== 'success') throw new Error()
    } catch {
      setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled: !enabled } : item)))
    } finally { setSkillBusy(false) }
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
              {activeTab === 'tools' && <Section title={t('tools_section_title')} count={tools.length} loading={toolsLoading} onRefresh={() => void loadTools()}>
                {toolsError ? <LoadError text={toolsError || t('capability_tools_error')} onRetry={() => void loadTools()} /> : tools.length === 0 ? (
                  <Empty text={t('tools_empty')} />
                ) : (
                  <Grid>
                    {tools.map((item) => (
                      <ToolCard key={item.id} tool={item} />
                    ))}
                  </Grid>
                )}
              </Section>}
              {activeTab === 'skills' && <Section title={t('skills_section_title')} count={skills.length} loading={skillsLoading} refreshDisabled={skillBusy} onRefresh={() => void loadSkills()}>
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
                <PluginCapabilities baseUrl={baseUrl} />
              </section>}
              {activeTab === 'mcp' && <Section title="MCP" count={servers.length} loading={mcpLoading} onRefresh={() => void loadMcp()}>
                {mcpError ? <LoadError text={mcpError} onRetry={() => void loadMcp()} /> : !servers.length ? (
                  <Empty text={t('capability_mcp_empty')} />
                ) : <Grid>{servers.map(server => <Card key={server.name} label={server.name}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-content break-all">{server.name}</h3>
                    <span className={`text-xs ${server.state === 'failed' ? 'text-danger' : 'text-content-secondary'}`}>
                      {t(`capability_mcp_${server.state}`)}
                    </span>
                  </div>
                  <p className="text-xs text-content-tertiary">{server.transport}</p>
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

const ToolCard: React.FC<{ tool: ToolInfo }> = ({ tool }) => (
  <Card label={tool.id}>
    <div className="flex items-start justify-between gap-3">
      <h3 className="font-mono text-[13px] font-semibold text-content break-all">{tool.id}</h3>
      <span className="text-xs text-content-tertiary shrink-0">{t(tool.available ? 'capability_tool_available' : 'capability_tool_unavailable')}</span>
    </div>
    <p className="text-[13px] leading-relaxed text-content-secondary whitespace-pre-wrap break-words">{copyOf(tool.intro)}</p>
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
