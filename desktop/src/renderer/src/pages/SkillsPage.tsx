import React, { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
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
  const { toolId, skillId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [toolsError, setToolsError] = useState('')
  const [skillsError, setSkillsError] = useState('')
  const [loading, setLoading] = useState(true)
  const restored = (location.state as { expanded?: string } | null)?.expanded || ''
  const [openTool, setOpenTool] = useState(restored.startsWith('tool:') ? restored.slice(5) : '')
  const [openSkill, setOpenSkill] = useState(restored.startsWith('skill:') ? restored.slice(6) : '')

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

  const tool = tools.find((item) => item.id === toolId)
  const skill = skills.find((item) => item.name === skillId)
  const detail = toolId ? 'tool' : skillId ? 'skill' : ''

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-content">{t('skills_title')}</h1>
          <p className="text-xs text-content-tertiary mt-1">{t('skills_desc')}</p>
        </div>
        {!detail && (
          <a href={SKILL_HUB_URL} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-xs font-medium text-accent bg-accent-soft">
            <Puzzle size={12} />{t('skills_hub_btn')}
          </a>
        )}
      </PageHeader>
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-5">
          {detail ? (
            <DetailView
              missing={!loading && (detail === 'tool' ? !toolsError && !tool : !skillsError && !skill)}
              error={detail === 'tool' ? toolsError : skillsError}
              title={tool ? copyOf(tool.title) : skill?.display_name || skill?.name || ''}
              body={tool ? copyOf(tool.detail) : skill?.description || ''}
              note={tool && !tool.available ? copyOf(tool.reason) : ''}
              identifier={tool?.id || skill?.name || ''}
              onBack={() => navigate('/skills', { state: { expanded: tool ? `tool:${tool.id}` : `skill:${skill?.name || ''}` } })}
              onRetry={() => void (detail === 'tool' ? loadTools() : loadSkills())}
            />
          ) : loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />{t('skills_loading')}
            </div>
          ) : (
            <div className="space-y-8">
              <Section title={t('tools_section_title')} count={tools.length}>
                {toolsError ? <LoadError text={toolsError || t('capability_tools_error')} onRetry={() => void loadTools()} /> : tools.length === 0 ? (
                  <Empty text={t('tools_empty')} />
                ) : tools.map((item) => (
                  <Entry key={item.id} title={copyOf(item.title)} open={openTool === item.id}
                    onToggle={() => setOpenTool(openTool === item.id ? '' : item.id)}>
                    <p className="text-sm text-content-secondary whitespace-pre-wrap break-words">{copyOf(item.intro)}</p>
                    {!item.available && <p className="text-xs text-content-tertiary">{t('capability_unavailable')}：{copyOf(item.reason)}</p>}
                    <p className="text-xs text-content-tertiary">{item.id}</p>
                    <Link className="text-sm text-accent" to={`/skills/tools/${item.id}`} state={{ expanded: `tool:${item.id}` }}>{t('capability_detail')}</Link>
                  </Entry>
                ))}
              </Section>
              <Section title={t('skills_section_title')} count={skills.length}>
                {skillsError ? <LoadError text={skillsError || t('capability_skills_error')} onRetry={() => void loadSkills()} /> : skills.length === 0 ? (
                  <Empty text={t('skills_empty')} />
                ) : skills.map((item) => (
                  <Entry key={item.name} title={item.display_name || item.name} open={openSkill === item.name}
                    onToggle={() => setOpenSkill(openSkill === item.name ? '' : item.name)}>
                    <p className="text-sm text-content-secondary whitespace-pre-wrap break-words">{item.description}</p>
                    <div className="flex items-center justify-between gap-3">
                      <Link className="text-sm text-accent" to={`/skills/skills/${item.name}`} state={{ expanded: `skill:${item.name}` }}>{t('capability_detail')}</Link>
                      <Toggle checked={item.enabled} onChange={(value) => void toggle(item, value)} />
                    </div>
                  </Entry>
                ))}
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const Entry: React.FC<{ title: string; open: boolean; onToggle: () => void; children: React.ReactNode }> = ({ title, open, onToggle, children }) => (
  <div className="rounded-card border border-default bg-surface">
    <button type="button" aria-expanded={open} onClick={onToggle} className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left">
      <span className="text-sm font-medium text-content">{title}</span>
      <span className="inline-flex items-center gap-1 text-xs text-content-tertiary">{t('capability_expand')}<ChevronDown size={14} className={open ? 'rotate-180' : ''} /></span>
    </button>
    {open && <div className="px-4 pb-4 space-y-2 border-t border-default pt-3">{children}</div>}
  </div>
)

const DetailView: React.FC<{ missing: boolean; error: string; title: string; body: string; note: string; identifier: string; onBack: () => void; onRetry: () => void }> = ({ missing, error, title, body, note, identifier, onBack, onRetry }) => (
  <div className="space-y-4">
    <button type="button" onClick={onBack} className="text-sm text-accent">{t('capability_back')}</button>
    {error ? <LoadError text={error} onRetry={onRetry} /> : missing ? <p>{t('capability_not_found')}</p> : (
      <>
        <h2 className="text-lg font-semibold text-content">{title}</h2>
        <p className="text-sm text-content-secondary whitespace-pre-wrap break-words">{body}</p>
        {note && <p className="text-sm text-content-tertiary">{note}</p>}
        <p className="text-xs text-content-tertiary">{identifier}</p>
      </>
    )}
  </div>
)

const Section: React.FC<{ title: string; count: number; children: React.ReactNode }> = ({ title, count, children }) => (
  <div className="space-y-3">
    <div className="flex items-center gap-2">
      <h2 className="text-sm font-semibold text-content">{title}</h2>
      {count > 0 && <span className="text-xs text-content-tertiary">{count}</span>}
    </div>
    {children}
  </div>
)

const LoadError: React.FC<{ text: string; onRetry: () => void }> = ({ text, onRetry }) => (
  <div role="alert" className="rounded-card border border-default p-4 space-y-2">
    <p className="text-sm text-danger">{text}</p>
    <button type="button" onClick={onRetry} className="text-sm text-accent">{t('capability_retry')}</button>
  </div>
)

const Empty: React.FC<{ text: string }> = ({ text }) => <p className="text-sm text-content-tertiary">{text}</p>

export default SkillsPage
