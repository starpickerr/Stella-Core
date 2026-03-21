import React, { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { t } from '../i18n'

interface SidebarProps {
  version: string
}

interface MenuGroup {
  key: string
  labelKey: string
  items: { path: string; labelKey: string; icon: string }[]
}

const menuGroups: MenuGroup[] = [
  {
    key: 'chat',
    labelKey: 'nav_chat',
    items: [{ path: '/', labelKey: 'menu_chat', icon: 'fas fa-message' }],
  },
  {
    key: 'manage',
    labelKey: 'nav_manage',
    items: [
      { path: '/config', labelKey: 'menu_config', icon: 'fas fa-sliders' },
      { path: '/skills', labelKey: 'menu_skills', icon: 'fas fa-bolt' },
      { path: '/memory', labelKey: 'menu_memory', icon: 'fas fa-brain' },
      { path: '/channels', labelKey: 'menu_channels', icon: 'fas fa-tower-broadcast' },
      { path: '/tasks', labelKey: 'menu_tasks', icon: 'fas fa-clock' },
    ],
  },
  {
    key: 'monitor',
    labelKey: 'nav_monitor',
    items: [{ path: '/logs', labelKey: 'menu_logs', icon: 'fas fa-terminal' }],
  },
]

const Sidebar: React.FC<SidebarProps> = ({ version }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    chat: true,
    manage: true,
    monitor: true,
  })

  const toggleGroup = (key: string) => {
    setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <aside className="w-64 bg-[#0A0A0A] text-neutral-400 flex flex-col flex-shrink-0 h-full">
      {/* Logo area with traffic light spacing on macOS */}
      <div className="flex items-center gap-3 pl-20 pr-5 h-[52px] border-b border-white/10 flex-shrink-0 titlebar-drag">
        <img src="./logo.jpg" alt="CowAgent" className="w-8 h-8 rounded-lg flex-shrink-0" />
        <div className="flex flex-col min-w-0">
          <span className="text-white font-semibold text-sm truncate">CowAgent</span>
          <span className="text-neutral-500 text-xs">{t('console')}</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-1">
        {menuGroups.map((group) => {
          const isOpen = openGroups[group.key] !== false
          return (
            <div key={group.key} className={`menu-group ${isOpen ? 'open' : ''}`}>
              <button
                onClick={() => toggleGroup(group.key)}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500 hover:text-neutral-300 cursor-pointer transition-colors duration-150"
              >
                <i className="fas fa-chevron-right text-[10px] chevron" />
                <span>{t(group.labelKey)}</span>
              </button>
              <div className="menu-group-items pl-2">
                {group.items.map((item) => {
                  const isActive = location.pathname === item.path
                  return (
                    <a
                      key={item.path}
                      onClick={() => navigate(item.path)}
                      className={`sidebar-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5 hover:text-neutral-200 text-[14px] ${
                        isActive ? 'active' : ''
                      }`}
                    >
                      <i className={`${item.icon} item-icon text-xs w-5 text-center`} />
                      <span>{t(item.labelKey)}</span>
                    </a>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-white/10 flex-shrink-0">
        <div className="flex items-center gap-2 text-xs text-neutral-600">
          <i className="fas fa-circle text-[6px] text-primary-400" />
          <a
            href="https://github.com/zhayujie/chatgpt-on-wechat/releases"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-primary-400 transition-colors duration-150 cursor-pointer"
          >
            {version}
          </a>
        </div>
      </div>
    </aside>
  )
}

export default Sidebar
