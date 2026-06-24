import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  BookOpen,
  Brain,
  Zap,
  Radio,
  Clock,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
  ScrollText,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { t, getLang, setLang, Lang } from '../i18n'
import { useUIStore } from '../store/uiStore'
import { useTheme } from '../hooks/useTheme'
import UpdateBanner from '../components/UpdateBanner'

interface NavItem {
  path: string
  labelKey: string
  icon: LucideIcon
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'menu_chat', icon: MessageSquare },
  { path: '/knowledge', labelKey: 'menu_knowledge', icon: BookOpen },
  { path: '/memory', labelKey: 'menu_memory', icon: Brain },
  { path: '/skills', labelKey: 'menu_skills', icon: Zap },
  { path: '/channels', labelKey: 'menu_channels', icon: Radio },
  { path: '/tasks', labelKey: 'menu_tasks', icon: Clock },
  { path: '/settings', labelKey: 'menu_settings', icon: Settings },
]

interface NavRailProps {
  onLangChange: () => void
}

const NavRail: React.FC<NavRailProps> = ({ onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const { navCollapsed, toggleNav } = useUIStore()
  const { theme, toggleTheme } = useTheme()

  const collapsed = navCollapsed
  const width = collapsed ? 'w-[56px]' : 'w-[208px]'

  const toggleLanguage = () => {
    const next: Lang = getLang() === 'zh' ? 'en' : 'zh'
    setLang(next)
    onLangChange()
  }

  return (
    <aside className={`${width} flex flex-col flex-shrink-0 h-full bg-base transition-[width] duration-200`}>
      {/* Top: full-width drag strip; reserve space for macOS traffic lights.
          No right border here so the divider doesn't cut across the traffic lights. */}
      <div className="titlebar-drag h-[44px] flex-shrink-0" />

      {/* Content area carries the right divider, starting below the titlebar */}
      <div className="flex-1 flex flex-col min-h-0 border-r border-default">
      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname === item.path
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              title={collapsed ? t(item.labelKey) : undefined}
              className={`group w-full flex items-center gap-3 rounded-btn cursor-pointer transition-colors h-9 ${
                collapsed ? 'justify-center px-0' : 'px-3'
              } ${
                isActive
                  ? 'bg-accent-soft text-accent'
                  : 'text-content-secondary hover:bg-surface-2 hover:text-content'
              }`}
            >
              <Icon size={18} strokeWidth={isActive ? 2.2 : 1.8} className="flex-shrink-0" />
              {!collapsed && <span className="text-[13px] truncate">{t(item.labelKey)}</span>}
            </button>
          )
        })}
      </nav>

      {/* Update banner floats above the footer when a new version is pending */}
      <div className="relative">
        {!collapsed && <UpdateBanner />}
      </div>

      {/* Footer actions */}
      <div className={`flex-shrink-0 px-2 py-2 border-t border-subtle ${collapsed ? 'space-y-0.5' : 'flex items-center gap-1'}`}>
        <FooterBtn
          collapsed={collapsed}
          onClick={() => navigate('/logs')}
          title={t('menu_logs')}
          active={location.pathname === '/logs'}
        >
          <ScrollText size={17} />
        </FooterBtn>
        <FooterBtn collapsed={collapsed} onClick={toggleTheme} title={theme === 'dark' ? 'Light' : 'Dark'}>
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </FooterBtn>
        <FooterBtn collapsed={collapsed} onClick={toggleLanguage} title="Language">
          <span className="text-[13px] font-medium w-[18px] text-center">{getLang() === 'zh' ? 'EN' : '中'}</span>
        </FooterBtn>
        <div className={collapsed ? '' : 'flex-1'} />
        <FooterBtn collapsed={collapsed} onClick={toggleNav} title={collapsed ? t('nav_expand') : t('nav_collapse')}>
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </FooterBtn>
      </div>
      </div>
    </aside>
  )
}

const FooterBtn: React.FC<{
  collapsed: boolean
  onClick: () => void
  title: string
  active?: boolean
  children: React.ReactNode
}> = ({ collapsed, onClick, title, active, children }) => (
  <button
    onClick={onClick}
    title={title}
    className={`inline-flex items-center gap-1.5 rounded-btn cursor-pointer transition-colors ${
      active
        ? 'bg-accent-soft text-accent'
        : 'text-content-tertiary hover:text-content hover:bg-surface-2'
    } ${collapsed ? 'w-full h-9 justify-center' : 'h-8 px-2'}`}
  >
    {children}
  </button>
)

export default NavRail
