import React, { useState, useCallback, useEffect } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { PanelLeftOpen } from 'lucide-react'
import NavRail from './layout/NavRail'
import SessionList from './layout/SessionList'
import WindowControls from './layout/WindowControls'
import StatusScreen from './components/StatusScreen'
import { useBackend } from './hooks/useBackend'
import { usePlatform } from './hooks/usePlatform'
import { useUIStore } from './store/uiStore'
import apiClient from './api/client'
import { t } from './i18n'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import SkillsPage from './pages/SkillsPage'
import MemoryPage from './pages/MemoryPage'
import ChannelsPage from './pages/ChannelsPage'
import TasksPage from './pages/TasksPage'
import LogsPage from './pages/LogsPage'
import PlaceholderPage from './pages/PlaceholderPage'

const App: React.FC = () => {
  const backend = useBackend()
  const location = useLocation()
  const { isWin } = usePlatform()
  const { sessionsCollapsed, toggleSessions } = useUIStore()
  const [, forceUpdate] = useState(0)

  useEffect(() => {
    if (backend.status === 'ready') apiClient.setBaseUrl(backend.baseUrl)
  }, [backend.status, backend.baseUrl])

  const handleLangChange = useCallback(() => forceUpdate((n) => n + 1), [])

  if (backend.status !== 'ready') {
    return <StatusScreen status={backend.status} error={backend.error} onRetry={backend.restart} />
  }

  const isChat = location.pathname === '/'
  const showSessions = isChat && !sessionsCollapsed

  return (
    <div className="flex h-screen overflow-hidden bg-base text-content">
      <NavRail onLangChange={handleLangChange} />

      {showSessions && <SessionList />}

      <div className="flex-1 flex flex-col min-w-0 h-screen">
        {/* Top titlebar strip — drag region + Windows controls */}
        <header className="h-[44px] flex items-center gap-1 px-2 flex-shrink-0 titlebar-drag bg-base border-b border-default">
          {isChat && sessionsCollapsed && (
            <button
              onClick={toggleSessions}
              title={t('nav_expand')}
              className="titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors"
            >
              <PanelLeftOpen size={16} />
            </button>
          )}
          <div className="flex-1 min-w-0" />
          {isWin && <WindowControls />}
        </header>

        {/* Content */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-base">
          <Routes>
            <Route path="/" element={<ChatPage baseUrl={backend.baseUrl} />} />
            <Route path="/knowledge" element={<PlaceholderPage title={t('menu_knowledge')} />} />
            <Route path="/memory" element={<MemoryPage baseUrl={backend.baseUrl} />} />
            <Route path="/skills" element={<SkillsPage baseUrl={backend.baseUrl} />} />
            <Route path="/channels" element={<ChannelsPage baseUrl={backend.baseUrl} />} />
            <Route path="/tasks" element={<TasksPage baseUrl={backend.baseUrl} />} />
            <Route path="/settings" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            {/* Legacy /models route now lives as a tab inside settings */}
            <Route path="/models" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            <Route path="/logs" element={<LogsPage baseUrl={backend.baseUrl} />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

export default App
