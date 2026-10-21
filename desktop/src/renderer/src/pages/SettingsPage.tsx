import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'

/** Compatibility bookmarks only; each configuration has one product owner. */
export default function SettingsPage() {
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const tab = params.get('tab') || 'general'
  params.delete('tab')
  let path = '/general'
  if (tab === 'models') path = '/models'
  else if (tab === 'assistant') path = '/agent-settings'
  else if (tab === 'plugins' || tab === 'briefing') {
    path = '/skills'
    params.set('tab', 'plugins')
    params.set('view', 'settings')
    if (tab === 'briefing' || params.get('plugin') === 'briefing') params.set('plugin', 'stella.briefing')
  } else if (tab === 'connections' || tab === 'integrations') {
    path = params.get('section') === 'apple-reminders' ? '/todos/settings/apple' : '/calendar/settings/apple'
    params.delete('section')
  } else if (tab === 'data') path = '/data'
  else if (tab === 'about') params.set('section', 'about')
  return <Navigate to={`${path}${params.size ? `?${params}` : ''}`} replace state={location.state} />
}
