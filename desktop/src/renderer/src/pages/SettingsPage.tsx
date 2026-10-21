import React, { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bot, Cpu, Database, ShieldCheck, Info, Link2, Puzzle, SlidersHorizontal, type LucideIcon } from 'lucide-react'
import { getLang, t } from '../i18n'
import { product } from '@product'
import GeneralSettings from './settings/GeneralSettings'
import AssistantSettings from './settings/AssistantSettings'
import AboutSettings from './settings/AboutSettings'
import ModelsTab from './settings/ModelsTab'
import ManagedModelSettings from './settings/ManagedModelSettings'
import AppleIntegrations from './settings/AppleIntegrations'
import PluginSettings from './settings/PluginSettings'
import type { SettingsOrigin } from './settings/origin'
import PageHeader from '../components/PageHeader'
import DataManagement from './settings/DataManagement'

interface SettingsPageProps {
  baseUrl: string
  onLangChange?: () => void
}

/** Core shell tabs only. Domain/plugin product settings live under「插件」. */
type Tab = 'general' | 'models' | 'assistant' | 'connections' | 'data' | 'plugins' | 'about'

const TABS: { key: Tab; icon: LucideIcon }[] = [
  { key: 'general', icon: SlidersHorizontal },
  { key: 'models', icon: Cpu },
  { key: 'assistant', icon: Bot },
  { key: 'connections', icon: Link2 },
  { key: 'data', icon: Database },
  { key: 'plugins', icon: Puzzle },
  { key: 'about', icon: Info },
]

/** Old bookmarks: basic/integrations; briefing was a duplicate of the briefing plugin. */
const LEGACY_TABS: Record<string, Tab> = {
  basic: 'general',
  integrations: 'connections',
  briefing: 'plugins',
}

const PLUGIN_ALIASES: Record<string, string> = {
  briefing: 'stella.briefing',
}

const readTab = (requested: string | null): Tab => {
  const key = requested ? LEGACY_TABS[requested] ?? requested : 'general'
  return TABS.some((tab) => tab.key === key) ? (key as Tab) : 'general'
}

const SettingsPage: React.FC<SettingsPageProps> = ({ baseUrl, onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const modelsTabHidden = product.models?.hideModelsTab === true
  const params = new URLSearchParams(location.search)
  const rawTab = params.get('tab')
  const tab = readTab(rawTab)
  const pluginParam = params.get('plugin')
  const pluginId = pluginParam
    ? (PLUGIN_ALIASES[pluginParam] ?? pluginParam)
    : (rawTab === 'briefing' ? 'stella.briefing' : null)
  const incoming = location.state as SettingsOrigin | null
  if (incoming?.from) sessionStorage.setItem('stella_settings_origin', JSON.stringify(incoming))
  else if (!location.search.includes('tab=')) sessionStorage.removeItem('stella_settings_origin')
  const stored = sessionStorage.getItem('stella_settings_origin')
  const origin = stored ? JSON.parse(stored) as SettingsOrigin : null

  useEffect(() => {
    // Rewrite legacy ?tab=briefing into plugins + plugin id (keep other query keys).
    if (rawTab !== 'briefing') return
    const next = new URLSearchParams(location.search)
    next.set('tab', 'plugins')
    next.set('plugin', 'stella.briefing')
    navigate(`/settings?${next.toString()}`, { replace: true, state: origin })
  }, [rawTab, location.search, navigate, origin])

  const chooseTab = (next: Tab) => {
    const search = new URLSearchParams()
    search.set('tab', next)
    navigate(`/settings?${search.toString()}`, { state: origin })
  }

  const choosePlugin = (nextPluginId: string) => {
    const search = new URLSearchParams()
    search.set('tab', 'plugins')
    search.set('plugin', nextPluginId)
    navigate(`/settings?${search.toString()}`, { state: origin })
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-bold text-content">{t('menu_settings')}</h2>
        {origin?.from && (
          <button type="button" className="h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2"
            onClick={() => navigate(origin.from, { state: { restoreScroll: origin.scroll } })}>
            {t('settings_return')}
          </button>
        )}
      </PageHeader>
      <div className="flex-1 min-h-0 flex">
        <nav aria-label={t('settings_nav_label')} className="w-44 flex-shrink-0 border-r border-default px-2 py-4 space-y-0.5 overflow-y-auto max-[960px]:w-14">
          {TABS.map(({ key, icon: Icon }) => {
            const active = tab === key
            const label = t(`settings_tab_${key}`)
            return (
              <button
                key={key}
                type="button"
                aria-current={active ? 'page' : undefined}
                title={label}
                onClick={() => chooseTab(key)}
                className={`relative w-full flex items-center gap-2.5 h-9 px-3 rounded-btn text-sm cursor-pointer transition-colors max-[960px]:justify-center max-[960px]:px-0 ${
                  active ? 'bg-surface-2 text-content font-medium' : 'text-content-secondary hover:bg-surface-2 hover:text-content'
                }`}
              >
                {active && <span aria-hidden className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-accent" />}
                <Icon size={16} className={active ? 'text-accent' : 'text-content-tertiary'} />
                <span className="max-[960px]:sr-only">{label}</span>
              </button>
            )
          })}
          <button type="button" title={getLang() === 'zh' ? '安全中心' : 'Security Center'} onClick={() => navigate('/security')}
            className="w-full flex items-center gap-2.5 h-9 px-3 rounded-btn text-sm text-content-secondary hover:bg-surface-2 max-[960px]:justify-center max-[960px]:px-0">
            <ShieldCheck size={16} className="text-content-tertiary" />
            <span className="max-[960px]:sr-only">{getLang() === 'zh' ? '安全中心' : 'Security Center'}</span>
          </button>
        </nav>
        <main data-stella-scroll className="flex-1 min-w-0 overflow-y-auto">
          <div data-settings-content className={`${tab === 'data' ? 'max-w-4xl' : 'max-w-2xl'} mx-auto px-6 py-6`}>
            <div className="mb-6 px-1">
              <h3 className="text-lg font-semibold text-content">{t(`settings_tab_${tab}`)}</h3>
              <p className="text-sm text-content-tertiary mt-0.5">{t(`settings_desc_${tab}`)}</p>
            </div>
            <TabBoundary key={tab}>
              {tab === 'general' ? (
                <GeneralSettings baseUrl={baseUrl} onLangChange={onLangChange} />
              ) : tab === 'models' ? (
                modelsTabHidden ? <ManagedModelSettings baseUrl={baseUrl} /> : <ModelsTab baseUrl={baseUrl} />
              ) : tab === 'assistant' ? (
                <AssistantSettings baseUrl={baseUrl} />
              ) : tab === 'connections' ? (
                <AppleIntegrations section={params.get('section')} />
              ) : tab === 'data' ? (
                <DataManagement />
              ) : tab === 'plugins' ? (
                <PluginSettings
                  baseUrl={baseUrl}
                  pluginId={pluginId}
                  onPluginChange={choosePlugin}
                />
              ) : (
                <AboutSettings baseUrl={baseUrl} />
              )}
            </TabBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}

class TabBoundary extends React.Component<{ children: React.ReactNode }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) {
    return { error: error.message || '设置内容无法显示' }
  }
  render() {
    return this.state.error ? <p role="alert">{this.state.error}</p> : this.props.children
  }
}

export default SettingsPage
