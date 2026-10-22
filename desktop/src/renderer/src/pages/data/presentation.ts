import { getLang } from '../../i18n'
import type { DataSourceInfo } from '../../api/dataTypes'

export const c = (zh: string, en: string) => getLang() === 'zh' ? zh : en
export const button = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-default px-3 py-2 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed'
export const input = 'min-w-0 rounded-btn border border-default bg-surface px-3 py-2 text-sm text-content'
export const panel = 'rounded-card border border-default bg-surface'
export const bytes = (value: number) => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`
export const sourceDescription = (source: DataSourceInfo) => ({
  email: c('邮箱中的邮件', 'Messages from your mailbox'),
  elearning: c('课程、公告、作业和文件', 'Courses, announcements, assignments and files'),
  workspace: c('当前对话或项目中的授权文件', 'Authorized conversation or project files'),
  tasks: c('事务与待办事项', 'Tasks and to-dos'),
  calendar: c('日程与事件', 'Calendars and events'),
  bills: c('账单与收支记录', 'Bills and transactions'),
  briefing: c('已生成的简报', 'Generated briefings'),
  knowledge: c('整理后的知识文档', 'Organized knowledge documents'),
  memory: c('长期记忆与维护记录', 'Long-term memory and maintenance records'),
}[source.provider] || source.kind)
export const sourceOrigin = (source: DataSourceInfo) => source.connection?.startsWith('mcp:')
  ? `MCP · ${source.connection.slice(4)}`
  : source.connection?.startsWith('plugin:') ? c('插件', 'Plugin') : source.provider === 'workspace' ? c('本地文件', 'Local files') : source.provider
export function settingsPath(source: DataSourceInfo): string | undefined {
  if (['/email', '/elearning'].includes(source.settings_url || '')) return `/data/sources${source.settings_url}`
  if (['/todos', '/calendar', '/bills', '/briefing', '/knowledge', '/memory'].includes(source.settings_url || '')) return source.settings_url
  return undefined
}

export const sourceName = (source: DataSourceInfo) => source.name.toLowerCase() === source.provider
  ? ({ tasks: c('事务', 'Tasks'), calendar: c('日程', 'Calendar'), bills: c('账单', 'Bills'), briefing: c('简报', 'Briefing'), knowledge: c('知识', 'Knowledge'), memory: c('记忆', 'Memory') }[source.provider] || source.name)
  : source.name

export function groupSources(sources: DataSourceInfo[]) {
  const groups = new Map<string, DataSourceInfo[]>()
  for (const source of sources) {
    const group = groups.get(source.provider) || []
    group.push(source)
    groups.set(source.provider, group)
  }
  return [...groups].map(([id, items]) => {
    const source = items[0]
    const available = items.filter(item => item.enabled && item.available).length
    const status = items.every(item => !item.enabled) ? 'disabled'
      : !available ? 'unavailable' : available === items.length ? 'available' : 'partial'
    return { id, source, items, available, status,
      name: id === 'email' ? 'Email' : sourceName(source),
      accounts: new Set(items.map(item => item.account_id || item.id)).size }
  })
}
export type SourceGroup = ReturnType<typeof groupSources>[number]
export const sourceStatus = (group: SourceGroup) => ({
  available: c('可用', 'Available'), partial: c('部分可用', 'Partly available'),
  unavailable: c('暂不可用', 'Unavailable'), disabled: c('已停用', 'Disabled'),
}[group.status])

export function groupSettingsPath(group: SourceGroup, scope: { agent: string; session: string }) {
  const path = settingsPath(group.source)
    || (group.id === 'workspace' ? '/security?tab=privacy'
      : group.source.connection?.startsWith('mcp:') ? '/skills?tab=mcp' : '/skills?tab=plugins')
  return path.startsWith('/data/') ? `${path}?${new URLSearchParams(scope)}` : path
}
