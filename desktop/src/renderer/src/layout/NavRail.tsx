import React, { useState, useEffect } from 'react'
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
  ScrollText,
  ChevronRight,
  ListChecks,
  CalendarDays,
  Receipt,
  Shield,
  Heart,
  Puzzle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import brandLogo from '../assets/logo.png'
import { t } from '../i18n'
import { useUIStore } from '../store/uiStore'
import { useTheme } from '../hooks/useTheme'
import { usePlatform } from '../hooks/usePlatform'
import { product } from '@product'

interface NavItem {
  path: string
  labelKey: string
  icon: LucideIcon
}

interface NavGroup {
  id: string
  labelKey: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    id: 'chat',
    labelKey: 'nav_chat',
    items: [{ path: '/', labelKey: 'menu_chat', icon: MessageSquare }],
  },
  {
    id: 'apps',
    labelKey: 'nav_work',
    items: [
      { path: '/todos', labelKey: 'menu_todos', icon: ListChecks },
      { path: '/calendar', labelKey: 'menu_calendar', icon: CalendarDays },
      { path: '/briefing', labelKey: 'menu_briefing', icon: Sun },
      { path: '/bills', labelKey: 'menu_bills', icon: Receipt },
      { path: '/health', labelKey: 'menu_health', icon: Heart },
      { path: '/tasks', labelKey: 'menu_tasks', icon: Clock },
    ],
  },
  {
    id: 'info',
    labelKey: 'nav_info',
    items: [
      { path: '/memory', labelKey: 'menu_memory', icon: Brain },
      { path: '/knowledge', labelKey: 'menu_knowledge', icon: BookOpen },
    ],
  },
  {
    id: 'channels',
    labelKey: 'nav_channels',
    items: [{ path: '/channels', labelKey: 'menu_channels', icon: Radio }],
  },
  {
    id: 'system',
    labelKey: 'nav_system',
    items: [
      { path: '/skills', labelKey: 'menu_evolution', icon: Zap },
      { path: '/security', labelKey: 'menu_security', icon: Shield },
      { path: '/plugins', labelKey: 'menu_plugins', icon: Puzzle },
      { path: '/settings', labelKey: 'menu_settings', icon: Settings },
      { path: '/logs', labelKey: 'menu_logs', icon: ScrollText },
    ],
  },
]

const GROUP_OPEN_DEFAULT: Record<string, boolean> = Object.fromEntries(
  NAV_GROUPS.map((g) => [g.id, true])
)

function pathActive(pathname: string, itemPath: string): boolean {
  if (itemPath === '/') return pathname === '/'
  if (itemPath === '/settings') return pathname === '/settings' || pathname === '/models'
  return pathname === itemPath
}

const NavRail: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const { navCollapsed, toggleNav } = useUIStore()
  const { appName } = useTheme()
  // On macOS the top-left is occupied by the native traffic lights, so the
  // brand mark is only shown on Windows/Linux where that corner is otherwise
  // empty (mirrors the web console's sidebar logo).
  const { isMac } = usePlatform()

  const collapsed = navCollapsed
  const width = collapsed ? 'w-[56px]' : 'w-[208px]'

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(GROUP_OPEN_DEFAULT)
  const [version, setVersion] = useState(__APP_VERSION__)

  useEffect(() => {
    window.electronAPI
      ?.getAppVersion?.()
      .then((v) => v && setVersion(v))
      .catch(() => {})
  }, [])

  return (
    <aside className={`${width} flex flex-col flex-shrink-0 h-full bg-base transition-[width] duration-200`}>
      {/* Top: full-width drag strip; bottom border continues the header divider
          across the whole window. No right border so it doesn't cut the lights.
          On Windows/Linux the top-left corner is empty (no traffic lights), so
          we surface the brand mark here like the web console's sidebar. */}
      <div
        className={`titlebar-drag h-[44px] flex-shrink-0 border-b border-default flex items-center ${
          collapsed ? 'justify-center px-0' : 'px-3'
        }`}
      >
        {!isMac &&
          (product.slots?.NavRailBrand ? (
            // A build may render its own wordmark in the brand area.
            <product.slots.NavRailBrand collapsed={collapsed} />
          ) : (
            <div className="flex items-center gap-2 min-w-0 select-none">
              <BrandLogo />
              {!collapsed && (
                <span className="text-[14px] font-semibold text-content truncate">{appName}</span>
              )}
            </div>
          ))}
      </div>

      {/* Content area carries the right divider, starting below the titlebar */}
      <div className="flex-1 flex flex-col min-h-0 border-r border-default">
      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {NAV_GROUPS.map((group, gi) => {
          const groupOpen = collapsed || openGroups[group.id] !== false
          return (
            <div key={group.id} className={gi > 0 ? (collapsed ? 'mt-2' : 'mt-1') : ''}>
              {!collapsed && (
                <button
                  onClick={() =>
                    setOpenGroups((prev) => ({ ...prev, [group.id]: prev[group.id] === false }))
                  }
                  className="w-full flex items-center gap-2 px-3 h-7 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary hover:text-content-secondary cursor-pointer transition-colors"
                >
                  <ChevronRight
                    size={10}
                    className={`flex-shrink-0 transition-transform ${groupOpen ? 'rotate-90' : ''}`}
                  />
                  <span className="truncate">{t(group.labelKey)}</span>
                </button>
              )}
              {groupOpen &&
                group.items.map((item) => {
                  const Icon = item.icon
                  const isActive = pathActive(location.pathname, item.path)
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
            </div>
          )
        })}
      </nav>

      <div className="flex-shrink-0 px-2 py-2 border-t border-subtle">
        {product.slots?.NavRailFooter && (
          <div className={collapsed ? 'mb-1' : 'mb-1 min-w-0'}>
            <product.slots.NavRailFooter />
          </div>
        )}
        <div className={collapsed ? 'space-y-0.5' : 'flex items-center gap-1'}>
          <p className={`min-w-0 text-[11px] text-content-tertiary truncate ${collapsed ? 'px-0.5 text-center' : 'flex-1 px-2'}`}>
            {version ? `v${version}` : ''}
          </p>
          <FooterBtn collapsed={collapsed} onClick={toggleNav} title={collapsed ? t('nav_expand') : t('nav_collapse')}>
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </FooterBtn>
        </div>
      </div>
      </div>
    </aside>
  )
}

// Brand mark for the top-left corner (Windows/Linux). Uses the desktop app's
// own icon (transparent PNG with its own rounded shape), so it sits cleanly on
// both light and dark backgrounds without extra styling.
const BrandLogo: React.FC = () => (
  <img
    src={brandLogo}
    alt="Stella"
    draggable={false}
    className="flex-shrink-0 w-7 h-7 object-contain"
  />
)

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
