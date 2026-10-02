import React, { useState, useCallback, useEffect } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { History, FolderTree } from 'lucide-react'
import NavRail from './layout/NavRail'
import SessionList from './layout/SessionList'
import WindowControls from './layout/WindowControls'
import StatusScreen from './components/StatusScreen'
import LoginGate from './components/LoginGate'
import { useBackend } from './hooks/useBackend'
import { usePlatform } from './hooks/usePlatform'
import { usePushPoll } from './hooks/usePushPoll'
import { useUIStore } from './store/uiStore'
import { useSessionStore } from './store/sessionStore'
import { useWorkspaceStore } from './store/workspaceStore'
import WorkspacePanel from './components/WorkspacePanel'
import Lightbox from './components/Lightbox'
import { initUpdateListener } from './store/updateStore'
import { useOnboardingStore } from './store/onboardingStore'
import OnboardingWizard from './components/OnboardingWizard'
import apiClient from './api/client'
import { t } from './i18n'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import KnowledgePage from './pages/KnowledgePage'
import SkillsPage from './pages/SkillsPage'
import MemoryPage from './pages/MemoryPage'
import ChannelsPage from './pages/ChannelsPage'
import TasksPage from './pages/TasksPage'
import HealthPage from './pages/HealthPage'
import LogsPage from './pages/LogsPage'
import PlaceholderPage from './pages/PlaceholderPage'
import BillsPage from './pages/BillsPage'
import BriefingPage from './pages/BriefingPage'
import CalendarPage from './pages/CalendarPage'
import TodosPage from './pages/TodosPage'
import SecurityPage from './pages/SecurityPage'
import { product } from '@product'

const App: React.FC = () => {
  const backend = useBackend()
  const location = useLocation()
  const navigate = useNavigate()
  const { isWin, isMac } = usePlatform()
  const { sessionsCollapsed, toggleSessions, navCollapsed } = useUIStore()
  const toggleWorkspace = useWorkspaceStore((s) => s.togglePanel)
  const workspaceOpen = useWorkspaceStore((s) => s.open)
  const onboardingOpen = useOnboardingStore((s) => s.open)
  const maybeOpenOnboarding = useOnboardingStore((s) => s.maybeOpen)
  const [, forceUpdate] = useState(0)
  // Backend authentication must settle before the main UI renders.
  const [authState, setAuthState] = useState<'checking' | 'need_login' | 'ok'>('checking')
  const [productAuthed, setProductAuthed] = useState(false)
  // product.auth is fixed for the lifetime of the build.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const productRequiresAuth = product.auth ? product.auth.useRequiresAuth() : false

  useEffect(() => {
    if (backend.status === 'ready') apiClient.setBaseUrl(backend.baseUrl)
  }, [backend.status, backend.baseUrl])

  // Prevent unhandled file drops from navigating away from the app.
  useEffect(() => {
    const swallow = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('Files')) e.preventDefault()
    }
    document.addEventListener('dragover', swallow)
    document.addEventListener('drop', swallow)
    return () => {
      document.removeEventListener('dragover', swallow)
      document.removeEventListener('drop', swallow)
    }
  }, [])

  useEffect(() => {
    if (backend.status !== 'ready') {
      setAuthState('checking')
      return
    }
    let cancelled = false
    apiClient
      .authCheck()
      .then((res) => {
        if (cancelled) return
        const needLogin = res.auth_required && !res.authenticated
        setAuthState(needLogin ? 'need_login' : 'ok')
      })
      .catch(() => {
        // Older backends may not expose the authentication check.
        if (!cancelled) setAuthState('ok')
      })
    return () => {
      cancelled = true
    }
  }, [backend.status, backend.baseUrl])

  // Prompt for model setup when no usable chat provider is configured.
  useEffect(() => {
    if (backend.status !== 'ready' || authState !== 'ok') return
    // An extension may opt out of the built-in setup wizard.
    if (product.onboarding?.enabled === false) return
    let cancelled = false
    apiClient
      .getModels()
      .then((data) => {
        if (cancelled) return
        const chat = data.capabilities?.chat
        const providerId = chat?.current_provider
        const provider = data.providers?.find((p) => p.id === providerId)
        const keyReady = !!provider && (provider.configured || (provider.is_custom && !!provider.custom_name))
        const configured = !!providerId && !!chat?.current_model && keyReady
        maybeOpenOnboarding(configured)
      })
      .catch(() => {
        // A failed model lookup leaves setup available.
        if (!cancelled) maybeOpenOnboarding(false)
      })
    return () => {
      cancelled = true
    }
  }, [backend.status, authState, maybeOpenOnboarding])

  // Poll for scheduler/push messages once the backend and auth are settled.
  usePushPoll(backend.status === 'ready' && authState === 'ok')

  // A clicked OS notification asks us to open its session.
  useEffect(() => {
    const off = window.electronAPI?.onOpenSession?.((sessionId) => {
      useSessionStore.getState().setActive(sessionId)
      navigate('/')
    })
    return off
  }, [navigate])

  // Subscribe to GitHub update-check status from the main process.
  useEffect(() => initUpdateListener(), [])

  // Handle app-menu / shortcut actions forwarded from the main process.
  useEffect(() => {
    const off = window.electronAPI?.onMenuAction?.((action) => {
      if (action === 'new-chat') {
        useSessionStore.getState().newSession()
        navigate('/')
      } else if (action === 'open-settings') {
        navigate('/settings')
      } else if (action === 'view-logs') {
        navigate('/logs')
      }
    })
    return off
  }, [navigate])

  const handleLangChange = useCallback(() => forceUpdate((n) => n + 1), [])

  if (backend.status !== 'ready') {
    return (
      <StatusScreen
        status={backend.status}
        error={backend.error}
        code={backend.code}
        path={backend.path}
        slow={backend.slow}
        reconnecting={backend.reconnecting}
        onRetry={backend.restart}
      />
    )
  }

  // Backend is up but we're still resolving auth — keep the loading screen.
  if (authState === 'checking') {
    return <StatusScreen status="connecting" onRetry={backend.restart} />
  }

  if (authState === 'need_login') {
    return <LoginGate onAuthenticated={() => setAuthState('ok')} />
  }

  // Optional gate from '@product', shown after the local auth check passes.
  // Rendered inside the layout (nav rail stays visible) so the app's features
  // are on display while the login card sits in the content area.
  const ProductGate = product.auth?.Gate
  const showProductGate = !!(ProductGate && productRequiresAuth && !productAuthed)

  const isChat = location.pathname === '/'
  const showSessions = isChat && !sessionsCollapsed && !showProductGate

  return (
    <div className="flex h-screen overflow-hidden bg-base text-content">
      {onboardingOpen && <OnboardingWizard onDone={handleLangChange} />}
      <Lightbox />
      <NavRail onLangChange={handleLangChange} />

      {showSessions && <SessionList />}

      <div className="flex-1 flex flex-col min-w-0 h-screen">
        {/* Top titlebar strip — drag region + Windows controls */}
        <header className="h-[44px] flex items-center gap-1 px-2 flex-shrink-0 titlebar-drag bg-base border-b border-default">
          {isChat && sessionsCollapsed && (
            <button
              onClick={toggleSessions}
              title={t('session_history')}
              // Keep aligned with the SessionList history button: only nudge
              // right of the macOS traffic lights when the nav rail is collapsed
              // (otherwise the lights stay within the rail and don't overlap).
              className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors ${isMac ? 'mt-1' : ''} ${isMac && navCollapsed ? 'ml-2' : ''}`}
            >
              <History size={16} />
            </button>
          )}
          <div className="flex-1 min-w-0" />
          {isChat && !showProductGate && (
            <button
              onClick={toggleWorkspace}
              title={t('ws_toggle')}
              className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn cursor-pointer transition-colors ${
                workspaceOpen
                  ? 'text-accent bg-accent-soft'
                  : 'text-content-tertiary hover:text-content hover:bg-surface-2'
              } ${isMac ? 'mt-1' : ''}`}
            >
              <FolderTree size={16} />
            </button>
          )}
          {product.slots?.HeaderRight && (
            <div className="titlebar-no-drag flex items-center">
              <product.slots.HeaderRight />
            </div>
          )}
          {isWin && <WindowControls />}
        </header>

        {/* Content */}
        <div className="flex-1 flex min-h-0 overflow-hidden bg-base">
          <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
          {showProductGate && ProductGate ? (
            <ProductGate onAuthenticated={() => setProductAuthed(true)} />
          ) : (
          <Routes>
            <Route path="/" element={<ChatPage baseUrl={backend.baseUrl} />} />
            <Route path="/todos" element={<TodosPage baseUrl={backend.baseUrl} />} />
            <Route path="/calendar" element={<CalendarPage baseUrl={backend.baseUrl} />} />
            <Route path="/briefing" element={<BriefingPage baseUrl={backend.baseUrl} />} />
            <Route path="/bills" element={<BillsPage baseUrl={backend.baseUrl} />} />
            <Route path="/tasks" element={<TasksPage baseUrl={backend.baseUrl} />} />
            <Route path="/health" element={<HealthPage baseUrl={backend.baseUrl} />} />
            <Route path="/knowledge" element={<KnowledgePage baseUrl={backend.baseUrl} />} />
            <Route path="/memory" element={<MemoryPage baseUrl={backend.baseUrl} />} />
            <Route path="/skills" element={<SkillsPage baseUrl={backend.baseUrl} />} />
            <Route path="/channels" element={<ChannelsPage baseUrl={backend.baseUrl} />} />
            <Route path="/security" element={<SecurityPage baseUrl={backend.baseUrl} />} />
            <Route path="/settings" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            {/* Legacy /models route now lives as a tab inside settings */}
            <Route path="/models" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            <Route path="/logs" element={<LogsPage baseUrl={backend.baseUrl} />} />
            {product.routes?.map((r) => (
              <Route key={r.path} path={r.path} element={r.element} />
            ))}
          </Routes>
          )}
          </div>
          {isChat && !showProductGate && <WorkspacePanel />}
        </div>
      </div>
    </div>
  )
}

export default App
