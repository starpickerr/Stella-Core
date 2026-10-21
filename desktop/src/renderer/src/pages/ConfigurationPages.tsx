import React, { useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { product } from '@product'
import { getLang, t } from '../i18n'
import PageHeader from '../components/PageHeader'
import GeneralSettings from './settings/GeneralSettings'
import AboutSettings from './settings/AboutSettings'
import ModelsTab from './settings/ModelsTab'
import ManagedModelSettings from './settings/ManagedModelSettings'
import AssistantSettings from './settings/AssistantSettings'
import AppleIntegrations from './settings/AppleIntegrations'
import type { SettingsOrigin } from './settings/origin'

const copy = (zh: string, en: string) => getLang() === 'zh' ? zh : en

function ConfigurationFrame({ title, children, wide = false }: { title: string; children: React.ReactNode; wide?: boolean }) {
  const location = useLocation()
  const navigate = useNavigate()
  const origin = location.state as SettingsOrigin | null
  return <div className="flex-1 flex flex-col min-h-0">
    <PageHeader className="flex items-center justify-between gap-3">
      <h1 className="text-xl font-bold text-content">{title}</h1>
      {origin?.from && <button type="button" className="rounded-btn border border-default px-3 py-1.5 text-sm" onClick={() => navigate(origin.from, { state: { restoreScroll: origin.scroll } })}>{t('settings_return')}</button>}
    </PageHeader>
    <main data-stella-scroll className="flex-1 min-w-0 overflow-y-auto">
      <div data-settings-content className={`${wide ? 'max-w-5xl' : 'max-w-2xl'} mx-auto px-4 sm:px-6 py-6 space-y-8`}>{children}</div>
    </main>
  </div>
}

export function GeneralPage({ baseUrl, onLangChange }: { baseUrl: string; onLangChange?: () => void }) {
  const location = useLocation()
  useEffect(() => {
    if (new URLSearchParams(location.search).get('section') === 'about') document.getElementById('general-about')?.scrollIntoView({ block: 'start' })
  }, [location.search])
  return <ConfigurationFrame title={copy('通用', 'General')}>
    <GeneralSettings baseUrl={baseUrl} onLangChange={onLangChange} />
    <section id="general-about" className="space-y-4 border-t border-default pt-8">
      <h2 className="text-lg font-semibold">{t('settings_tab_about')}</h2><AboutSettings baseUrl={baseUrl} />
    </section>
  </ConfigurationFrame>
}

export function ModelsPage({ baseUrl }: { baseUrl: string }) {
  return <ConfigurationFrame title={t('settings_tab_models')} wide>
    {product.models?.hideModelsTab ? <ManagedModelSettings baseUrl={baseUrl} /> : <ModelsTab baseUrl={baseUrl} />}
  </ConfigurationFrame>
}

export function AgentSettingsPage({ baseUrl }: { baseUrl: string }) {
  return <ConfigurationFrame title={copy('Agent 配置', 'Agent configuration')}><AssistantSettings baseUrl={baseUrl} /></ConfigurationFrame>
}

export function AppleSettingsPage({ kind }: { kind: 'calendar' | 'todos' }) {
  return <ConfigurationFrame title={kind === 'calendar' ? 'Apple 日历' : 'Apple 提醒事项'}>
    <Link className="text-sm text-accent" to={kind === 'calendar' ? '/calendar' : '/todos'}>{copy('返回', 'Back')}</Link>
    <AppleIntegrations section={kind === 'calendar' ? 'apple-calendar' : 'apple-reminders'} kind={kind} />
  </ConfigurationFrame>
}
