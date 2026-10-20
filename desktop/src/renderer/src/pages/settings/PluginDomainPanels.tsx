import React from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { SettingsPanel } from '../briefing/SettingsPanel'
import { MailboxSettings } from '../briefing/MailboxSettings'
import { ElearningSettings } from '../briefing/ElearningSettings'
import AgentElearningFileSettings from './AgentElearningFileSettings'
import { t } from '../../i18n'

/** First-party product settings that used to live as top-level Core tabs. */
export function hasPluginDomainPanel(pluginId: string): boolean {
  return pluginId === 'stella.briefing'
    || pluginId === 'stella.email'
    || pluginId === 'stella.elearning'
    || pluginId === 'stella.automation'
    || pluginId === 'stella.tasks'
    || pluginId === 'stella.calendar'
    || pluginId === 'stella.bills'
}

function OpenAppLink({ to, label }: { to: string; label: string }) {
  return (
    <div className="px-1">
      <Link
        to={to}
        className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
      >
        {label}
        <ExternalLink size={12} />
      </Link>
    </div>
  )
}

export function PluginDomainPanel({ pluginId }: { pluginId: string }): React.ReactNode {
  if (pluginId === 'stella.briefing') {
    return (
      <div className="space-y-6">
        <OpenAppLink to="/briefing" label={t('settings_plugin_open_briefing')} />
        <SettingsPanel />
      </div>
    )
  }
  if (pluginId === 'stella.email') {
    return (
      <section className="space-y-4" aria-label="邮箱账号">
        <OpenAppLink to="/email" label={t('settings_plugin_open_email')} />
        <MailboxSettings />
      </section>
    )
  }
  if (pluginId === 'stella.elearning') {
    return (
      <section className="space-y-6" aria-label="课程来源">
        <OpenAppLink to="/elearning" label={t('settings_plugin_open_elearning')} />
        <ElearningSettings />
        <AgentElearningFileSettings />
      </section>
    )
  }
  if (pluginId === 'stella.automation') {
    return (
      <div className="space-y-3 px-1">
        <p className="text-sm text-content-secondary">{t('settings_plugin_automation_hint')}</p>
        <OpenAppLink to="/tasks" label={t('settings_plugin_open_automation')} />
      </div>
    )
  }
  if (pluginId === 'stella.tasks') {
    return (
      <div className="space-y-3 px-1">
        <p className="text-sm text-content-secondary">{t('settings_plugin_tasks_hint')}</p>
        <OpenAppLink to="/todos" label={t('settings_plugin_open_todos')} />
      </div>
    )
  }
  if (pluginId === 'stella.calendar') {
    return (
      <div className="space-y-3 px-1">
        <p className="text-sm text-content-secondary">{t('settings_plugin_calendar_hint')}</p>
        <OpenAppLink to="/calendar" label={t('settings_plugin_open_calendar')} />
      </div>
    )
  }
  if (pluginId === 'stella.bills') {
    return (
      <div className="space-y-3 px-1">
        <p className="text-sm text-content-secondary">{t('settings_plugin_bills_hint')}</p>
        <OpenAppLink to="/bills" label={t('settings_plugin_open_bills')} />
      </div>
    )
  }
  return null
}
