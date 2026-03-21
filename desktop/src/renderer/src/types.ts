export interface ElectronAPI {
  getBackendPort: () => Promise<number | null>
  getBackendStatus: () => Promise<string>
  restartBackend: () => Promise<boolean>
  selectDirectory: () => Promise<string | null>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  onBackendStatus: (callback: (data: BackendStatusEvent) => void) => void
  onBackendLog: (callback: (line: string) => void) => void
  platform: string
}

export interface BackendStatusEvent {
  status: 'ready' | 'error' | 'starting'
  port?: number
  error?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  attachments?: Attachment[]
  toolCalls?: ToolCall[]
  isStreaming?: boolean
}

export interface Attachment {
  file_path: string
  file_name: string
  file_type: 'image' | 'video' | 'file'
  preview_url?: string
}

export interface ToolCall {
  type: 'tool_start' | 'tool_end'
  tool: string
  arguments?: Record<string, unknown>
  result?: string
  status?: string
  execution_time?: number
}

export interface ConfigData {
  use_agent: boolean
  title: string
  model: string
  bot_type: string
  use_linkai: boolean
  channel_type: string
  agent_max_context_tokens: number
  agent_max_context_turns: number
  agent_max_steps: number
  api_bases: Record<string, string>
  api_keys: Record<string, string>
  providers: Record<string, unknown>
}

export interface ChannelInfo {
  name: string
  label: Record<string, string>
  icon: string
  color: string
  active: boolean
  fields: ChannelField[]
}

export interface ChannelField {
  key: string
  label: Record<string, string>
  type: string
  required?: boolean
  placeholder?: Record<string, string>
}

export interface SkillInfo {
  name: string
  display_name: string
  description: string
  enabled: boolean
}

export interface ToolInfo {
  name: string
  display_name: string
  description: string
}

export interface MemoryItem {
  filename: string
  modified: number
  size: number
}

export interface SchedulerTask {
  id: string
  name: string
  cron: string
  enabled: boolean
  last_run?: string
  next_run?: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
