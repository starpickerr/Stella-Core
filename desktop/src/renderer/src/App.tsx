import React, { useState, useCallback } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import StatusScreen from './components/StatusScreen'
import { useTheme } from './hooks/useTheme'
import { useBackend } from './hooks/useBackend'
import { t, getLang, setLang, Lang } from './i18n'
import ChatPage from './pages/ChatPage'
import ConfigPage from './pages/ConfigPage'
import SkillsPage from './pages/SkillsPage'
import MemoryPage from './pages/MemoryPage'
import ChannelsPage from './pages/ChannelsPage'
import TasksPage from './pages/TasksPage'
import LogsPage from './pages/LogsPage'

const APP_VERSION = 'v2.0.3'

const VIEW_META: Record<string, { group: string; page: string }> = {
  '/': { group: 'nav_chat', page: 'menu_chat' },
  '/config': { group: 'nav_manage', page: 'menu_config' },
  '/skills': { group: 'nav_manage', page: 'menu_skills' },
  '/memory': { group: 'nav_manage', page: 'menu_memory' },
  '/channels': { group: 'nav_manage', page: 'menu_channels' },
  '/tasks': { group: 'nav_manage', page: 'menu_tasks' },
  '/logs': { group: 'nav_monitor', page: 'menu_logs' },
}

const App: React.FC = () => {
  const { theme, toggleTheme } = useTheme()
  const backend = useBackend()
  const location = useLocation()
  const [, forceUpdate] = useState(0)

  const toggleLanguage = useCallback(() => {
    const next: Lang = getLang() === 'zh' ? 'en' : 'zh'
    setLang(next)
    forceUpdate((n) => n + 1)
  }, [])

  if (backend.status !== 'ready') {
    return <StatusScreen status={backend.status} error={backend.error} onRetry={backend.restart} />
  }

  const meta = VIEW_META[location.pathname] || VIEW_META['/']

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar version={APP_VERSION} />
      <div className="flex-1 flex flex-col min-w-0 h-screen">
        {/* Top Header */}
        <header className="h-[52px] flex items-center gap-3 px-4 border-b border-slate-200 dark:border-white/10 bg-white dark:bg-[#1A1A1A] flex-shrink-0 z-10 titlebar-drag">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm min-w-0 titlebar-no-drag">
            <span className="text-slate-400 dark:text-slate-500 truncate">{t(meta.group)}</span>
            <i className="fas fa-chevron-right text-[10px] text-slate-300 dark:text-slate-600" />
            <span className="font-medium text-slate-700 dark:text-slate-200 truncate">{t(meta.page)}</span>
          </div>

          <div className="flex-1" />

          {/* Language Toggle */}
          <button
            onClick={toggleLanguage}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 cursor-pointer transition-colors duration-150 titlebar-no-drag"
          >
            <i className="fas fa-globe text-xs" />
            <span>{getLang() === 'zh' ? 'EN' : '中'}</span>
          </button>

          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 cursor-pointer transition-colors duration-150 titlebar-no-drag"
          >
            <i className={`fas ${theme === 'dark' ? 'fa-sun' : 'fa-moon'}`} />
          </button>

          {/* Docs */}
          <a
            href="https://docs.cowagent.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 cursor-pointer transition-colors duration-150 titlebar-no-drag"
          >
            <i className="fas fa-book text-base" />
          </a>

          {/* GitHub */}
          <a
            href="https://github.com/zhayujie/chatgpt-on-wechat"
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 cursor-pointer transition-colors duration-150 titlebar-no-drag"
          >
            <i className="fab fa-github text-lg" />
          </a>
        </header>

        {/* Content Area */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <Routes>
            <Route path="/" element={<ChatPage baseUrl={backend.baseUrl} />} />
            <Route path="/config" element={<ConfigPage baseUrl={backend.baseUrl} />} />
            <Route path="/skills" element={<SkillsPage baseUrl={backend.baseUrl} />} />
            <Route path="/memory" element={<MemoryPage baseUrl={backend.baseUrl} />} />
            <Route path="/channels" element={<ChannelsPage baseUrl={backend.baseUrl} />} />
            <Route path="/tasks" element={<TasksPage baseUrl={backend.baseUrl} />} />
            <Route path="/logs" element={<LogsPage baseUrl={backend.baseUrl} />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

export default App
