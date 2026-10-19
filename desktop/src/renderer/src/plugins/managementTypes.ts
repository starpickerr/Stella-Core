export type PluginRow = {
  pluginId: string; userId: string; name: string; version: string | null
  intent: 'enabled' | 'disabled' | 'removed'; state: string; error?: string
  sourceLabel: string; generation: number; services: string[]
}
export type ResourceRef = { kind: string; id: string }
export type Grant = {
  grantId: string; consumerPluginId: string; capability: string; methods: string[]
  resources: ResourceRef[]; purpose: 'interactive' | 'background'; revoked: boolean; validUntil: string | null
}
export type Method = { name: string; permissions: string[] }
export type SettingsField = {
  key: string; title: string; category: string; type: string; default?: unknown; secret?: boolean
  validation?: { enum?: unknown[]; min?: number; max?: number; minLength?: number; maxLength?: number }
}
export type SettingsDescriptor = {
  id: string; categories: { id: string; title: string }[]; fields: SettingsField[]
}
export type SettingsSnapshot = { revision: number; values: Record<string, unknown>; secretFields: string[] }
export const pluginStateLabel: Record<string, string> = {
  active: '运行中', stopped: '已停止', disabled: '已停用', removed: '已卸载', maintenance: '维护中', failed: '故障',
  enabled: '已启用', blocked: '不可用', degraded: '部分可用'
}
