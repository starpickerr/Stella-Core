import React, { useState, useEffect } from 'react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ToolInfo, SkillInfo } from '../types'

interface SkillsPageProps {
  baseUrl: string
}

const SkillsPage: React.FC<SkillsPageProps> = ({ baseUrl }) => {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<string | null>(null)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadData()
  }, [baseUrl])

  const loadData = async () => {
    try {
      setLoading(true)
      const [toolsData, skillsData] = await Promise.all([apiClient.getTools(), apiClient.getSkills()])
      setTools(toolsData || [])
      setSkills(skillsData || [])
    } catch (err) {
      console.error('Failed to load skills:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (skill: SkillInfo) => {
    setToggling(skill.name)
    try {
      await apiClient.toggleSkill(skill.name, skill.enabled ? 'close' : 'open')
      setSkills((prev) => prev.map((s) => (s.name === skill.name ? { ...s, enabled: !s.enabled } : s)))
    } catch (err) {
      console.error('Toggle failed:', err)
    } finally {
      setToggling(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('skills_title')}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('skills_desc')}</p>
          </div>
        </div>

        {/* Built-in Tools */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{t('tools_section_title')}</span>
            {tools.length > 0 && (
              <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-white/10 text-slate-500 dark:text-slate-400">{tools.length}</span>
            )}
          </div>
          {loading ? (
            <div className="flex items-center gap-2 py-4 text-slate-400 dark:text-slate-500 text-sm">
              <i className="fas fa-spinner fa-spin text-xs" />
              <span>{t('tools_loading')}</span>
            </div>
          ) : tools.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {tools.map((tool) => (
                <div key={tool.name} className="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-1.5">
                    <i className="fas fa-cog text-xs text-primary-400" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{tool.name}</span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{tool.description}</p>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        {/* Skills */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{t('skills_section_title')}</span>
            {skills.length > 0 && (
              <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-white/10 text-slate-500 dark:text-slate-400">{skills.length}</span>
            )}
          </div>
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center mb-3">
                <i className="fas fa-bolt text-amber-400 text-lg" />
              </div>
              <p className="text-slate-500 dark:text-slate-400 font-medium">{t('skills_loading')}</p>
              <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">{t('skills_loading_desc')}</p>
            </div>
          ) : skills.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {skills.map((skill) => (
                <div key={skill.name} className="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <i className="fas fa-bolt text-xs text-amber-400" />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{skill.name}</span>
                    </div>
                    <button
                      onClick={() => handleToggle(skill)}
                      disabled={toggling === skill.name}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer ${
                        skill.enabled ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        skill.enabled ? 'translate-x-6' : 'translate-x-1'
                      }`} />
                    </button>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{skill.description}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center mb-3">
                <i className="fas fa-bolt text-amber-400 text-lg" />
              </div>
              <p className="text-slate-500 dark:text-slate-400 font-medium">{t('skills_loading')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default SkillsPage
