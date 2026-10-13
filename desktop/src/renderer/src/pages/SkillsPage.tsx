import React, { useCallback, useEffect, useState } from 'react'
import { ChevronDown, Loader2, Puzzle } from 'lucide-react'
import { getLang, t } from '../i18n'
import apiClient from '../api/client'
import type { LocalizedCopy, SkillInfo, ToolInfo } from '../types'
import { Toggle } from './settings/primitives'
import { SKILL_HUB_URL } from './settings/links'
import PageHeader from '../components/PageHeader'

interface SkillsPageProps {
  baseUrl: string
}

const copyOf = (value: LocalizedCopy | null | undefined) => value?.[getLang() === 'en' ? 'en' : 'zh'] || ''

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [toolsError, setToolsError] = useState('')
  const [skillsError, setSkillsError] = useState('')
  const [loading, setLoading] = useState(true)
  const [openTool, setOpenTool] = useState('')

  const loadTools = useCallback(async () => {
    try {
      setTools(await apiClient.getTools())
      setToolsError('')
    } catch (err) {
      setToolsError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  const loadSkills = useCallback(async () => {
    try {
      setSkills(await apiClient.getSkills())
      setSkillsError('')
    } catch (err) {
      setSkillsError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    await Promise.all([loadTools(), loadSkills()])
    setLoading(false)
  }, [loadTools, loadSkills])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadData()
  }, [baseUrl, loadData])

  const toggle = async (skill: SkillInfo, enabled: boolean) => {
    setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled } : item)))
    try {
      const res = await apiClient.toggleSkill(skill.name, enabled ? 'open' : 'close')
      if (res.status !== 'success') throw new Error()
    } catch {
      setSkills((prev) => prev.map((item) => (item.name === skill.name ? { ...item, enabled: !enabled } : item)))
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-content">{t('skills_title')}</h1>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
        <a href={SKILL_HUB_URL} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft">
          <Puzzle size={12} />{t('skills_hub_btn')}
        </a>
      </PageHeader>
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />{t('skills_loading')}
            </div>
          ) : (
            <div className="space-y-10">
              <Section title={t('tools_section_title')} count={tools.length}>
                {toolsError ? <LoadError text={toolsError || t('capability_tools_error')} onRetry={() => void loadTools()} /> : tools.length === 0 ? (
                  <Empty text={t('tools_empty')} />
                ) : (
                  <Grid>
                    {tools.map((item) => (
                      <ToolCard key={item.id} tool={item} open={openTool === item.id}
                        onToggle={() => setOpenTool(openTool === item.id ? '' : item.id)} />
                    ))}
                  </Grid>
                )}
              </Section>
              <Section title={t('skills_section_title')} count={skills.length}>
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
                            <Toggle label={title} checked={item.enabled} onChange={(value) => void toggle(item, value)} />
                          </div>
                          <p className="text-[13px] leading-relaxed text-content-secondary whitespace-pre-wrap break-words">{item.description}</p>
                        </Card>
                      )
                    })}
                  </Grid>
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const ToolCard: React.FC<{ tool: ToolInfo; open: boolean; onToggle: () => void }> = ({ tool, open, onToggle }) => {
  const panelId = `tool-boundary-${tool.id}`
  return (
    <Card label={tool.id}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-mono text-[13px] font-semibold text-content break-all">{tool.id}</h3>
        {/* Catalog availability is whether the tool loaded, not a preference the switch can change. */}
        <Toggle label={tool.id} checked={tool.available} onChange={() => undefined} />
      </div>
      <p className="text-[13px] leading-relaxed text-content-secondary whitespace-pre-wrap break-words">{copyOf(tool.intro)}</p>
      <div className="pt-1">
        <button type="button" aria-expanded={open} aria-controls={panelId} onClick={onToggle}
          className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-content-secondary cursor-pointer">
          {t('capability_boundary')}
          <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>
        {open && (
          <div id={panelId} className="mt-2 space-y-1.5 border-t border-default pt-2.5 text-xs leading-relaxed text-content-secondary">
            <p className="whitespace-pre-wrap break-words">{copyOf(tool.detail)}</p>
            {!tool.available && copyOf(tool.reason) && <p className="text-content-tertiary">{copyOf(tool.reason)}</p>}
          </div>
        )}
      </div>
    </Card>
  )
}

/** Two independent columns so a short card does not stretch to its neighbor. */
const Grid: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const items = React.Children.toArray(children)
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 768px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(min-width: 768px)')
    const apply = () => setWide(query.matches)
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [])
  if (!wide) return <div className="flex flex-col gap-3">{items}</div>
  return (
    <div className="grid grid-cols-2 items-start gap-3">
      <div className="flex flex-col gap-3">{items.filter((_, index) => index % 2 === 0)}</div>
      <div className="flex flex-col gap-3">{items.filter((_, index) => index % 2 === 1)}</div>
    </div>
  )
}

const Card: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <article aria-label={label} className="flex flex-col gap-2 rounded-card border border-default bg-surface p-4">
    {children}
  </article>
)

const Section: React.FC<{ title: string; count: number; children: React.ReactNode }> = ({ title, count, children }) => (
  <section className="space-y-3">
    <div className="flex items-baseline gap-2">
      <h2 className="text-sm font-semibold text-content">{title}</h2>
      {count > 0 && <span className="text-xs text-content-tertiary tabular-nums">{count}</span>}
    </div>
    {children}
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
