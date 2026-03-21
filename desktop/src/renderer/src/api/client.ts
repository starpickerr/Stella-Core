import type { ConfigData, ChannelInfo, SkillInfo, ToolInfo, MemoryItem, SchedulerTask, Attachment } from '../types'

class ApiClient {
  private baseUrl: string = 'http://127.0.0.1:9899'

  setBaseUrl(url: string) {
    this.baseUrl = url
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    })

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }

    return res.json()
  }

  // Chat
  async sendMessage(
    sessionId: string,
    message: string,
    stream: boolean = true,
    attachments?: Attachment[]
  ): Promise<{ status: string; request_id: string; stream: boolean }> {
    return this.request('/message', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message, stream, attachments }),
    })
  }

  async poll(sessionId: string): Promise<{
    status: string
    has_content: boolean
    content?: string
    request_id?: string
    timestamp?: number
  }> {
    return this.request('/poll', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    })
  }

  createSSEStream(requestId: string): EventSource {
    return new EventSource(`${this.baseUrl}/stream?request_id=${requestId}`)
  }

  async uploadFile(file: File, sessionId?: string): Promise<{
    status: string
    file_path: string
    file_name: string
    file_type: string
    preview_url: string
  }> {
    const formData = new FormData()
    formData.append('file', file)
    if (sessionId) {
      formData.append('session_id', sessionId)
    }

    const res = await fetch(`${this.baseUrl}/upload`, {
      method: 'POST',
      body: formData,
    })

    return res.json()
  }

  // Config
  async getConfig(): Promise<ConfigData> {
    const data = await this.request<{ status: string } & ConfigData>('/config')
    return data
  }

  async updateConfig(updates: Partial<ConfigData>): Promise<{ status: string; applied: Record<string, unknown> }> {
    return this.request('/config', {
      method: 'POST',
      body: JSON.stringify({ updates }),
    })
  }

  // Channels
  async getChannels(): Promise<ChannelInfo[]> {
    const data = await this.request<{ status: string; channels: ChannelInfo[] }>('/api/channels')
    return data.channels
  }

  async channelAction(
    action: 'save' | 'connect' | 'disconnect',
    channel: string,
    config?: Record<string, unknown>
  ): Promise<{ status: string }> {
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify({ action, channel, config }),
    })
  }

  // Tools & Skills
  async getTools(): Promise<ToolInfo[]> {
    const data = await this.request<{ status: string; tools: ToolInfo[] }>('/api/tools')
    return data.tools
  }

  async getSkills(): Promise<SkillInfo[]> {
    const data = await this.request<{ status: string; skills: SkillInfo[] }>('/api/skills')
    return data.skills
  }

  async toggleSkill(name: string, action: 'open' | 'close'): Promise<{ status: string }> {
    return this.request('/api/skills', {
      method: 'POST',
      body: JSON.stringify({ action, name }),
    })
  }

  // Memory
  async getMemoryList(page: number = 1, pageSize: number = 20): Promise<{ list: MemoryItem[]; total: number }> {
    const data = await this.request<{ status: string; list: MemoryItem[]; total: number }>(
      `/api/memory?page=${page}&page_size=${pageSize}`
    )
    return { list: data.list, total: data.total }
  }

  async getMemoryContent(filename: string): Promise<string> {
    const data = await this.request<{ status: string; content: string }>(
      `/api/memory/content?filename=${encodeURIComponent(filename)}`
    )
    return data.content
  }

  // Scheduler
  async getSchedulerTasks(): Promise<SchedulerTask[]> {
    const data = await this.request<{ status: string; tasks: SchedulerTask[] }>('/api/scheduler')
    return data.tasks
  }

  // History
  async getHistory(
    sessionId: string,
    page: number = 1,
    pageSize: number = 20
  ): Promise<{ messages: ChatMessage[]; has_more: boolean }> {
    const data = await this.request<{ status: string; messages: ChatMessage[]; has_more: boolean }>(
      `/api/history?session_id=${sessionId}&page=${page}&page_size=${pageSize}`
    )
    return { messages: data.messages, has_more: data.has_more }
  }

  // Logs SSE
  createLogStream(): EventSource {
    return new EventSource(`${this.baseUrl}/api/logs`)
  }

  getFileUrl(previewUrl: string): string {
    return `${this.baseUrl}${previewUrl}`
  }
}

interface ChatMessage {
  role: string
  content: string
  timestamp: number
}

export const apiClient = new ApiClient()
export default apiClient
