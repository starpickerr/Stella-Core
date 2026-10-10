import React, { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { getLang, setLang, t, type Lang } from '../i18n'
import { product } from '@product'
import { useTheme } from '../hooks/useTheme'
import { useUpdateStore } from '../store/updateStore'
import BasicSettings from './settings/BasicSettings'
import ModelsTab from './settings/ModelsTab'
import AppleIntegrations from './settings/AppleIntegrations'
import { SettingsPanel } from './briefing/SettingsPanel'
import { docsUrl, FEEDBACK_URL, openExternal, websiteUrl } from './settings/links'
import type { SettingsOrigin } from './settings/origin'

interface SettingsPageProps {
  baseUrl: string
  onLangChange?: () => void
}

type Tab = 'basic' | 'models' | 'integrations' | 'briefing' | 'about'

const SettingsPage: React.FC<SettingsPageProps> = ({ baseUrl, onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const modelsTabHidden = product.models?.hideModelsTab === true
  const requested = new URLSearchParams(location.search).get('tab')
  const tab: Tab = requested === 'integrations' ? 'integrations'
    : requested === 'briefing' ? 'briefing'
    : requested === 'about' ? 'about'
    : requested === 'models' && !modelsTabHidden ? 'models' : 'basic'
  const incoming = location.state as SettingsOrigin | null
  if (incoming?.from) sessionStorage.setItem('stella_settings_origin', JSON.stringify(incoming))
  else if (!location.search.includes('tab=')) sessionStorage.removeItem('stella_settings_origin')
  const stored = sessionStorage.getItem('stella_settings_origin')
  const origin = stored ? JSON.parse(stored) as SettingsOrigin : null
  const chooseTab = (next: Tab) => navigate(`/settings?tab=${next}`, { state: origin })

  const tabs: { key: Tab; label: string }[] = [
    { key: 'basic', label: t('settings_tab_basic') },
    ...(modelsTabHidden ? [] : [{ key: 'models' as Tab, label: t('settings_tab_models') }]),
    { key: 'integrations', label: '集成与连接' },
    { key: 'briefing', label: t('settings_tab_briefing') },
    { key: 'about', label: t('settings_tab_about') },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-content">{t('menu_settings')}</h2>
            <p className="text-sm text-content-tertiary mt-1">{t('config_desc')}</p>
          </div>
          {origin?.from && (
            <button type="button" className="h-8 px-3 rounded-btn border border-default text-sm text-content-secondary hover:bg-surface-2"
              onClick={() => navigate(origin.from, { state: { restoreScroll: origin.scroll } })}>
              {t('settings_return')}
            </button>
          )}
        </div>

        <div className="flex items-center gap-1 mb-6 border-b border-default">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              type="button"
              onClick={() => chooseTab(tb.key)}
              className={`relative px-4 py-2.5 text-sm font-medium cursor-pointer transition-colors -mb-px border-b-2 ${
                tab === tb.key
                  ? 'text-accent border-accent'
                  : 'text-content-tertiary border-transparent hover:text-content-secondary'
              }`}
            >
              {tb.label}
            </button>
          ))}
        </div>

        <TabBoundary key={tab}>
        {tab === 'basic' ? (
          <BasicSettings
            baseUrl={baseUrl}
            onLangChange={onLangChange}
            onOpenModels={modelsTabHidden ? undefined : () => chooseTab('models')}
          />
        ) : tab === 'models' ? (
          <ModelsTab baseUrl={baseUrl} />
        ) : tab === 'briefing' ? (
          <SettingsPanel />
        ) : tab === 'about' ? (
          <AboutSection onLangChange={onLangChange} />
        ) : (
          <AppleIntegrations section={new URLSearchParams(location.search).get('section')} />
        )}
        </TabBoundary>
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

const AboutSection: React.FC<{ onLangChange?: () => void }> = ({ onLangChange }) => {
  const { theme, toggleTheme, themeId, themes, setThemeId } = useTheme()
  const updateState = useUpdateStore()
  const [checking, setChecking] = useState(false)
  const switchLanguage = () => {
    const next: Lang = getLang() === 'zh' ? 'en' : 'zh'
    setLang(next)
    onLangChange?.()
  }
  return (
    <section className="space-y-3" aria-label={t('settings_tab_about')}>
      <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" onClick={toggleTheme}>
        {t('menu_theme_picker')}
      </button>
      <label className="block text-sm text-content-secondary">
        {t('menu_theme_picker')}
        <select className="mt-1 block h-9 rounded-btn border border-default bg-surface px-2" value={themeId} onChange={(event) => setThemeId(event.target.value)}>
          {themes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" onClick={switchLanguage}>
        {t('menu_language')}
      </button>
      <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" disabled={checking}
        onClick={() => { setChecking(true); updateState.recheck(); setChecking(false) }}>
        {checking ? t('update_checking') : t('update_check')}
      </button>
      <p className="text-xs text-content-tertiary">{theme === 'dark' ? t('menu_theme_light') : t('menu_theme_dark')}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" onClick={() => openExternal(docsUrl())}>{t('menu_docs')}</button>
        <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" onClick={() => openExternal(websiteUrl())}>{t('menu_website')}</button>
        <button type="button" className="h-9 px-3 rounded-btn border border-default text-sm" onClick={() => openExternal(FEEDBACK_URL)}>{t('menu_feedback')}</button>
      </div>
    </section>
  )
}

export default SettingsPage
