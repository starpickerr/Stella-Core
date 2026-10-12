import type {
  ConfigData,
  ChannelInfo,
  ChannelAction,
  SkillInfo,
  ToolInfo,
  MemoryItem,
  MemoryCategory,
  MemoryPage,
  SchedulerTask,
  TaskSchedule,
  TaskAction,
  Attachment,
  SessionsPage,
  WorkspaceShare,
  SessionSettingsState,
  HistoryPage,
  ModelsData,
  ModelsAction,
  KnowledgeList,
  KnowledgeGraph,
  KnowledgeAction,
  KnowledgeImportPayload,
  WorkspaceEntry,
  WorkspaceTree,
  ProjectState,
  LedgerEntry,
  PeriodStatement,
  PeriodStatementItem,
  PeriodType,
  Briefing, BriefingDetail, BriefingItem, BriefingItemStatus, BriefingRunProgress,
  BriefingDecision, BriefingActionReceipt, BriefingAuthorization, BriefingPreferences,
  BriefingRule, BriefingRuleInput, BriefingSettings, BriefingMailboxInput, BriefingMailbox, BriefingMailboxCheck,
  BriefingSource, ElearningSettings, ElearningSettingsInput,
  CalendarCategory, CalendarEvent, CalendarEventInput, AppleCalendarConnection, AppleCalendarSyncResult, AppleReminderConnection,
  Todo, TodoInput, UncertainReminder,
} from '../types'
import { getLang } from '../i18n'

interface ApiResult {
  status: string
  message?: string
}

export interface SecurityPolicy {
  preset?: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
  base_preset?: 'read-only' | 'workspace-write' | 'full-access'
  rules?: Record<string, 'allow' | 'confirm' | 'deny'>
  connections?: Record<string, { allowed: boolean; scopes: string[] }>
  extra_roots?: string[]
}

export interface SecurityRecord {
  at: number
  agent: string
  conversation: string | null
  project: string | null
  tool: string
  operation: string
  event: string
  resource: string
  risk: string
  decision: string
  reason: string
  trace: string[]
}

export interface SecurityCenterState extends ApiResult {
  global_policy: SecurityPolicy
  effective_policy: SecurityPolicy
  effective_mode: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
  effective_rules: Record<string, 'allow' | 'confirm' | 'deny'>
  policy_source: 'global' | 'project' | 'session' | 'mixed'
  mode_definitions: SecurityModeDefinition[]
  authorized_roots: string[]
  policy_error?: string | null
  process_isolation: { status: 'enabled' | 'unavailable' | 'full-access'; reason: string }
  project: string | null
  project_policy: SecurityPolicy
  projects: { path: string; name: string; policy: SecurityPolicy }[]
  conversation_policy: SecurityPolicy
  connections: { id: string; name: string; connected: boolean; allowed: boolean; available?: boolean; scopes: string[]; last_access: number | null }[]
  secrets: { name: string; display_name?: string; source: string; configured: boolean }[]
  background_tasks?: SecurityBackgroundTask[]
  privacy?: SecurityPrivacyInventory
  summary: { status: string; app_password_set: boolean; connection_count: number; secret_count: number;
    recent_high_risk: SecurityRecord[]; recent_denials: SecurityRecord[];
    activity_counts?: SecurityActivityCounts
    background_tasks?: SecurityBackgroundTaskSummary }
}

export interface SecurityBackgroundTask {
  id: string
  name: string
  enabled: boolean
  conversation_mode?: string | null
  execution_session_id?: string | null
  execution_project_dir?: string | null
  run_permission_mode?: 'read-only' | 'workspace-write' | 'full-access' | null
  effective_mode?: string | null
  permission_source?: string
  unknown?: boolean
  policy_error?: string | null
}

export interface SecurityBackgroundTaskSummary {
  total: number | null
  enabled: number | null
  paused: number | null
  modes: Record<string, number> | null
  unknown: number | null
  available: boolean
}

export interface SecurityPrivacyCategory {
  id: string
  name: { zh: string; en: string }
  path: string
  bytes: number
  exists: boolean
  retention: { zh: string; en: string }
  actions: string[]
  detail?: Record<string, unknown>
}

export interface SecurityPrivacyInventory {
  available: boolean
  categories: SecurityPrivacyCategory[]
  external_transfers?: { id: string; name: string; available: boolean; note: { zh: string; en: string } }[]
}

export interface SecurityActivityCounts {
  auto_allow: number
  user_authorized: number
  denied: number
  uncertain: boolean
  since: number
  until: number
}

export interface SecurityModeDefinition {
  id: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
  name: { zh: string; en: string }
  description: { zh: string; en: string }
  rules: Record<string, 'allow' | 'confirm' | 'deny'>
}

const AUTH_TOKEN_KEY = 'cow_auth_token'

class ApiClient {
  private baseUrl = 'http://127.0.0.1:9876'
  // Bearer token for web_password-protected backends. The desktop renderer
  // runs from a file:// origin, where cross-origin cookies to http://127.0.0.1
  // aren't sent reliably, so we authenticate via an Authorization header
  // instead. Persisted in localStorage so it survives reloads.
  private authToken: string | null =
    typeof localStorage !== 'undefined' ? localStorage.getItem(AUTH_TOKEN_KEY) : null

  setBaseUrl(url: string) {
    this.baseUrl = url
  }

  getBaseUrl() {
    return this.baseUrl
  }

  setAuthToken(token: string | null) {
    this.authToken = token
    try {
      if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
      else localStorage.removeItem(AUTH_TOKEN_KEY)
    } catch {
      // localStorage may be unavailable; in-memory token still works this session
    }
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      // Cookies still work for browser access; the desktop app relies on the
      // Authorization header below.
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {}),
        ...options?.headers,
      },
    })
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }
    return res.json()
  }

  /** POST multipart form data.
   *
   * `request()` can't be reused: it forces a JSON content type, while FormData
   * must set its own multipart boundary. The auth header still has to be wired
   * up by hand — the desktop app renders from file://, so it authenticates via
   * the header, never the cookie.
   */
  private async postFormData<T>(path: string, formData: FormData): Promise<T> {
    const url = `${this.baseUrl}${path}`
    // A plain `fetch` that never reaches the backend throws a bare
    // `TypeError: Failed to fetch`, which is useless in a bug report. The most
    // common cause here is a transient connection refusal (the local backend
    // still booting, or briefly restarting), so retry once after a short delay
    // and, on a persistent network failure, raise an actionable message that
    // names the target URL instead of the opaque browser error.
    let lastErr: unknown
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 600))
      try {
        const res = await fetch(url, {
          method: 'POST',
          body: formData,
          credentials: 'include',
          headers: this.authToken ? { Authorization: `Bearer ${this.authToken}` } : undefined,
        })
        if (!res.ok) {
          // The backend returns JSON errors even on failure; surface its message
          // when present so the user sees the real reason (e.g. file too large).
          let detail = res.statusText
          try {
            const body = await res.clone().json()
            if (body?.message) detail = body.message
          } catch {
            /* non-JSON error body */
          }
          throw new Error(`HTTP ${res.status}: ${detail}`)
        }
        return res.json()
      } catch (e) {
        lastErr = e
        // Only retry the network-level failure; a real HTTP error is final.
        const isNetwork = e instanceof TypeError
        if (!isNetwork) throw e
      }
    }
    console.error(`[api] upload network failure to ${url}:`, lastErr)
    throw new Error(
      `无法连接到本地服务 (${url})，请确认客户端后台正在运行后重试`,
    )
  }

  // ---------------------------------------------------------
  // Chat / messages
  // ---------------------------------------------------------

  async sendMessage(
    sessionId: string,
    message: string,
    opts?: { stream?: boolean; attachments?: Attachment[]; isVoice?: boolean; lang?: string }
  ): Promise<{ status: string; request_id: string; stream: boolean; inline_reply?: string }> {
    return this.request('/message', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        message,
        stream: opts?.stream ?? true,
        attachments: opts?.attachments,
        is_voice: opts?.isVoice ?? false,
        lang: opts?.lang,
      }),
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

  async cancel(opts: { requestId?: string; sessionId?: string; lang?: string }): Promise<{ status: string; cancelled: number }> {
    return this.request('/cancel', {
      method: 'POST',
      body: JSON.stringify({ request_id: opts.requestId, session_id: opts.sessionId, lang: opts.lang }),
    })
  }

  // EventSource can't set an Authorization header, so append the auth token as
  // a query param for SSE endpoints (the backend accepts it there).
  private withToken(url: string): string {
    if (!this.authToken) return url
    const sep = url.includes('?') ? '&' : '?'
    return `${url}${sep}token=${encodeURIComponent(this.authToken)}`
  }

  createSSEStream(requestId: string): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/stream?request_id=${requestId}`))
  }

  async deleteMessage(opts: {
    sessionId: string
    userSeq: number
    deleteUser?: boolean
    cascade?: boolean
  }): Promise<{ status: string; deleted: number }> {
    return this.request('/api/messages/delete', {
      method: 'POST',
      body: JSON.stringify({
        session_id: opts.sessionId,
        user_seq: opts.userSeq,
        delete_user: opts.deleteUser ?? true,
        cascade: opts.cascade ?? false,
      }),
    })
  }

  // ---------------------------------------------------------
  // Upload / files
  // ---------------------------------------------------------

  async uploadFile(file: File, sessionId?: string): Promise<{
    status: string
    file_path: string
    file_name: string
    file_type: string
    preview_url: string
    message?: string
  }> {
    const formData = new FormData()
    // Read the file into memory (a Blob) instead of appending the File directly.
    // In Electron, `fetch` streaming a File straight from disk intermittently
    // rejects with a bare "Failed to fetch" (net::ERR while reading the backing
    // file — moved/locked path, sandbox, special chars in the name), even for
    // small files. Materializing the bytes first sidesteps that disk-streaming
    // path; the original name is preserved so the backend keeps the extension.
    try {
      const buf = await file.arrayBuffer()
      formData.append('file', new Blob([buf], { type: file.type }), file.name)
    } catch {
      // Reading failed (rare): fall back to the raw File so behavior degrades
      // gracefully rather than blocking the upload entirely.
      formData.append('file', file)
    }
    if (sessionId) formData.append('session_id', sessionId)
    return this.postFormData('/upload', formData)
  }

  getFileUrl(previewUrl: string): string {
    if (/^https?:\/\//.test(previewUrl)) return previewUrl
    // Served via <img src>, which can't set headers — carry the token in the
    // query so protected file endpoints load under web_password.
    return this.withToken(`${this.baseUrl}${previewUrl}`)
  }

  getServeFileUrl(absPath: string): string {
    return this.withToken(`${this.baseUrl}/api/file?path=${encodeURIComponent(absPath)}`)
  }

  // ---------------------------------------------------------
  // Workspace browsing / preview
  // ---------------------------------------------------------

  // Workspace endpoints accept an optional session so they resolve against the
  // session's project dir (when one is open) instead of always ~/stella.
  private sessionQuery(session?: string): string {
    return session ? `&session=${encodeURIComponent(session)}` : ''
  }

  async workspaceTree(path = '', session?: string): Promise<WorkspaceTree & ApiResult> {
    return this.request(`/api/workspace/tree?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  async workspaceSearch(query: string, limit = 30, session?: string): Promise<{ results: WorkspaceEntry[] } & ApiResult> {
    return this.request(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=${limit}${this.sessionQuery(session)}`)
  }

  async workspaceResolve(path: string, session?: string): Promise<{ file: WorkspaceEntry } & ApiResult> {
    return this.request(`/api/workspace/resolve?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  async workspaceShares(session: string): Promise<{ shares: WorkspaceShare[] } & ApiResult> {
    return this.request(`/api/workspace/shares?session=${encodeURIComponent(session)}`)
  }

  async createWorkspaceShare(session: string, path: string, recipient: string, access: 'read' | 'write'):
    Promise<{ share: WorkspaceShare } & ApiResult> {
    return this.request('/api/workspace/shares', { method: 'POST',
      body: JSON.stringify({ session, path, recipient, access }) })
  }

  async revokeWorkspaceShare(session: string, id: string): Promise<{ share: WorkspaceShare } & ApiResult> {
    return this.request('/api/workspace/shares/revoke', { method: 'POST', body: JSON.stringify({ session, id }) })
  }

  // ---------------------------------------------------------
  // Project workspace (per-session working directory)
  // ---------------------------------------------------------

  async getProjects(session: string): Promise<ProjectState & ApiResult> {
    return this.request(`/api/projects?session=${encodeURIComponent(session)}`)
  }

  /** Bind the session to a project dir, or clear it (projectDir=null → ~/stella). */
  async selectProject(session: string, projectDir: string | null): Promise<ProjectState & ApiResult> {
    return this.request('/api/projects/select', {
      method: 'POST',
      body: JSON.stringify({ session, project_dir: projectDir }),
    })
  }

  /** Create a new project folder under the projects root and select it. */
  async createProject(session: string, name: string): Promise<ProjectState & ApiResult & { path?: string }> {
    return this.request('/api/projects/create', {
      method: 'POST',
      body: JSON.stringify({ session, name }),
    })
  }

  /** Persist the user-defined order of project spaces in the sidebar. */
  async setProjectsOrder(order: string[]): Promise<ApiResult> {
    return this.request('/api/projects/order', {
      method: 'POST',
      body: JSON.stringify({ order }),
    })
  }

  /** Rename a project's display label (record only; files on disk untouched). */
  async renameProject(path: string, name: string): Promise<ApiResult & { name?: string }> {
    return this.request('/api/projects/manage', {
      method: 'PUT',
      body: JSON.stringify({ path, name }),
    })
  }

  /** Forget a project record and unbind its sessions (files on disk kept). */
  async deleteProject(path: string): Promise<ApiResult & { unbound?: number }> {
    return this.request('/api/projects/manage', {
      method: 'DELETE',
      body: JSON.stringify({ path }),
    })
  }

  /** Absolute URL for a `/preview/...` path. The signed token in the path is
   *  what authorizes it, so no auth token is appended. */
  getPreviewUrl(previewPath: string): string {
    if (/^https?:\/\//.test(previewPath)) return previewPath
    return `${this.baseUrl}${previewPath}`
  }

  // ---------------------------------------------------------
  // Sessions
  // ---------------------------------------------------------

  async getSessions(page = 1, pageSize = 50): Promise<SessionsPage> {
    return this.request<{ status: string } & SessionsPage>(`/api/sessions?page=${page}&page_size=${pageSize}`)
  }

  async deleteSession(sessionId: string): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  }

  async renameSession(sessionId: string, title: string): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PUT',
      body: JSON.stringify({ title }),
    })
  }

  /** Pin or unpin a session; pinned sessions sort to the top of their group. */
  async setSessionPinned(sessionId: string, pinned: boolean): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PUT',
      body: JSON.stringify({ pinned }),
    })
  }

  /** This session's effective model + permission, with the catalog to switch. */
  async getSessionSettings(sessionId: string): Promise<{ status: string; message?: string } & SessionSettingsState> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/settings`)
  }

  /** Set or clear this session's model / permission override. Pass null to a
   *  field to drop the override and follow the global default. */
  async updateSessionSettings(
    sessionId: string,
    body: { provider?: string | null; model?: string | null; security_policy?: SecurityPolicy | null }
  ): Promise<{ status: string } & Partial<SessionSettingsState> & { message?: string }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateSessionTitle(sessionId: string, userMessage: string, assistantReply?: string): Promise<{ status: string; title: string }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/generate_title`, {
      method: 'POST',
      body: JSON.stringify({ user_message: userMessage, assistant_reply: assistantReply }),
    })
  }

  async clearContext(sessionId: string): Promise<{ status: string; context_start_seq: number }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, { method: 'POST' })
  }

  async getHistory(sessionId: string, page = 1, pageSize = 20): Promise<HistoryPage> {
    return this.request<{ status: string } & HistoryPage>(
      `/api/history?session_id=${encodeURIComponent(sessionId)}&page=${page}&page_size=${pageSize}`
    )
  }

  // ---------------------------------------------------------
  // Config
  // ---------------------------------------------------------

  async getConfig(): Promise<ConfigData> {
    return this.request<{ status: string } & ConfigData>('/config')
  }

  async getSecurityCenter(session?: string): Promise<SecurityCenterState> {
    return this.request<SecurityCenterState>(`/api/security/center${session ? `?session=${encodeURIComponent(session)}` : ''}`)
  }

  async getSecurityRecords(filters: Record<string, string> = {}): Promise<{
    records: SecurityRecord[]
    counts?: SecurityActivityCounts
  }> {
    const query = new URLSearchParams(filters).toString()
    const result = await this.request<{ status: string; records: SecurityRecord[]; counts?: SecurityActivityCounts }>(
      `/api/security/activity${query ? `?${query}` : ''}`,
    )
    if (result.status !== 'success') throw new Error('Unable to load security activity')
    return { records: result.records || [], counts: result.counts }
  }

  async saveSecurityPolicy(target: 'global' | 'project' | 'conversation', policy: SecurityPolicy,
    options: { project?: string; session?: string } = {}): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/policy', { method: 'POST', body: JSON.stringify({ target, policy, ...options }) })
  }

  async updateSecurityConnection(id: string, allowed: boolean, scopes: string[]): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/connections', { method: 'POST', body: JSON.stringify({ id, allowed, scopes }) })
  }

  async saveSecuritySecret(name: string, value: string): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/secrets', { method: 'POST', body: JSON.stringify({ name, value }) })
  }

  async deleteSecuritySecret(name: string): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/secrets', { method: 'DELETE', body: JSON.stringify({ name }) })
  }

  async cleanupPrivacy(action: string): Promise<{ status: string; message?: string } & Partial<SecurityPrivacyInventory>> {
    return this.request('/api/security/privacy', { method: 'POST', body: JSON.stringify({ action }) })
  }

  async getSecurityConfirmations(): Promise<{ id: string; tool: string; session: string | null; summary: string; resource: string; risk: string; reason: string; expanded_scope: string; effect: string }[]> {
    const result = await this.request<{ status: string; pending: { id: string; tool: string; session: string | null; summary: string; resource: string; risk: string; reason: string; expanded_scope: string; effect: string }[] }>('/api/security/confirmations')
    return result.pending || []
  }

  async approveSecurityConfirmation(id: string, session: string | null): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/confirmations', { method: 'POST', body: JSON.stringify({ id, session, action: 'approve' }) })
  }

  async rejectSecurityConfirmation(id: string, session: string | null): Promise<{ status: string; message?: string }> {
    return this.request('/api/security/confirmations', { method: 'POST', body: JSON.stringify({ id, session, action: 'reject' }) })
  }

  async updateConfig(updates: Record<string, unknown>): Promise<{ status: string; applied: Record<string, unknown> }> {
    const result = await this.request<{ status: string; applied: Record<string, unknown> }>('/config', {
      method: 'POST',
      body: JSON.stringify({ updates }),
    })
    if (result.status === 'success' && typeof result.applied?.web_password === 'string') {
      const password = String(updates.web_password || '')
      if (password) {
        const login = await this.authLogin(password)
        if (login.status !== 'success') throw new Error(login.message || 'Password saved; sign in again to continue')
      } else this.setAuthToken(null)
    }
    return result
  }

  // ---------------------------------------------------------
  // Models console
  // ---------------------------------------------------------

  async getModels(): Promise<ModelsData> {
    return this.request<{ status: string } & ModelsData>('/api/models')
  }

  async modelsAction(action: ModelsAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/models', {
      method: 'POST',
      body: JSON.stringify(action),
    })
  }

  // ---------------------------------------------------------
  // Channels
  // ---------------------------------------------------------

  async getChannels(): Promise<ChannelInfo[]> {
    // The list is ordered per language, and this window's language is kept
    // locally, so it may differ from the backend's global setting.
    const data = await this.request<{ status: string; channels: ChannelInfo[] }>(
      `/api/channels?lang=${getLang()}`
    )
    return data.channels
  }

  async channelAction(
    action: ChannelAction,
    channel: string,
    config?: Record<string, unknown>
  ): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify({ action, channel, config }),
    })
  }

  // Weixin QR login
  async getWeixinQr(): Promise<{ status: string; qrcode_url?: string; qr_image?: string; source?: string; message?: string }> {
    return this.request('/api/weixin/qrlogin')
  }

  async weixinQrAction(action: 'poll' | 'refresh'): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/weixin/qrlogin', {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
  }

  // Feishu one-click register
  async getFeishuRegister(): Promise<{ status: string; register_status?: string; qrcode_url?: string; qr_image?: string; expire_in?: number; message?: string }> {
    return this.request('/api/feishu/register')
  }

  async feishuRegisterPoll(): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/feishu/register', {
      method: 'POST',
      body: JSON.stringify({ action: 'poll' }),
    })
  }

  // ---------------------------------------------------------
  // Tools & skills
  // ---------------------------------------------------------

  async getTools(): Promise<ToolInfo[]> {
    const data = await this.request<{ status: string; tools?: ToolInfo[]; message?: string }>('/api/tools')
    if (data.status !== 'success' || !Array.isArray(data.tools)) throw new Error(data.message || 'Could not load tools')
    return data.tools
  }

  async getSkills(): Promise<SkillInfo[]> {
    const data = await this.request<{ status: string; skills?: SkillInfo[]; message?: string }>('/api/skills')
    if (data.status !== 'success' || !Array.isArray(data.skills)) throw new Error(data.message || 'Could not load skills')
    return data.skills
  }

  async toggleSkill(name: string, action: 'open' | 'close'): Promise<ApiResult> {
    return this.request('/api/skills', {
      method: 'POST',
      body: JSON.stringify({ action, name }),
    })
  }

  // ---------------------------------------------------------
  // Memory
  // ---------------------------------------------------------

  async getMemoryList(page = 1, pageSize = 20, category: MemoryCategory = 'memory'): Promise<MemoryPage> {
    return this.request<{ status: string } & MemoryPage>(
      `/api/memory?page=${page}&page_size=${pageSize}&category=${category}`
    )
  }

  async getMemoryContent(filename: string, category: MemoryCategory = 'memory'): Promise<string> {
    const data = await this.request<{ status: string; content: string }>(
      `/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}`
    )
    return data.content
  }

  // ---------------------------------------------------------
  // Knowledge
  // ---------------------------------------------------------

  async getKnowledgeList(): Promise<KnowledgeList> {
    return this.request<{ status: string } & KnowledgeList>('/api/knowledge/list')
  }

  async readKnowledge(path: string): Promise<{ status: string; content: string; path: string; dir?: string }> {
    return this.request(`/api/knowledge/read?path=${encodeURIComponent(path)}`)
  }

  async getKnowledgeGraph(): Promise<KnowledgeGraph> {
    return this.request<KnowledgeGraph>('/api/knowledge/graph')
  }

  async knowledgeAction(req: KnowledgeAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/knowledge/action', {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  // Bulk import: upload .md/.txt files into a target category (multipart).
  async importKnowledge(
    files: File[],
    targetCategory: string
  ): Promise<{ status: string; message?: string; payload?: KnowledgeImportPayload }> {
    const formData = new FormData()
    formData.append('target_category', targetCategory)
    formData.append('conflict_strategy', 'rename')
    files.forEach((file) => formData.append('files', file, file.name))
    return this.postFormData('/api/knowledge/import', formData)
  }

  // ---------------------------------------------------------
  // Scheduler
  // ---------------------------------------------------------

  async getTaskDestinations(): Promise<{channel_type: string; configured: boolean; ready: boolean; status: string; recipients: {receiver: string; name: string}[]}[]> {
    const result = await this.request<{destinations: {channel_type: string; configured: boolean; ready: boolean; status: string; recipients: {receiver: string; name: string}[]}[]}>('/api/scheduler/destinations')
    return result.destinations
  }

  async getSchedulerTasks(): Promise<SchedulerTask[]> {
    const data = await this.request<{ status: string; tasks: SchedulerTask[] }>('/api/scheduler')
    return data.tasks
  }

  async createTask(payload: {
    name: string
    enabled?: boolean
    schedule: TaskSchedule
    action: TaskAction
    session_id: string
    notification_route?: SchedulerTask['notification_route']
    run_permission_mode?: SchedulerTask['run_permission_mode'] | 'inherit'
  }): Promise<{ status: string; task?: SchedulerTask; message?: string }> {
    return this.request('/api/scheduler', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  async runTask(taskId: string): Promise<ApiResult> {
    return this.request('/api/scheduler/run', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    })
  }

  async toggleTask(taskId: string, enabled: boolean): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/toggle', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, enabled }),
    })
  }

  async updateTask(taskId: string, updates: Partial<Pick<SchedulerTask, 'name' | 'enabled' | 'schedule' | 'action' | 'notification_route'>> & { run_permission_mode?: NonNullable<SchedulerTask['run_permission_mode']> | 'inherit' }): Promise<{ status: string; task?: SchedulerTask; message?: string }> {
    return this.request('/api/scheduler/update', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, ...updates }),
    })
  }

  async testNotificationRoute(notification_route: SchedulerTask['notification_route']): Promise<{status: string; delivery_status?: string; message?: string; error?: string}> {
    return this.request('/api/scheduler/test-delivery', {
      method: 'POST', body: JSON.stringify({ notification_route }),
    })
  }

  async deleteTask(taskId: string): Promise<ApiResult> {
    return this.request('/api/scheduler/delete', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    })
  }

  // ---------------------------------------------------------
  // Briefings
  // ---------------------------------------------------------

  private async briefingRequest<T>(path: string, body?: unknown): Promise<T> {
    const data = await this.request<T & ApiResult>(path, body === undefined ? undefined : {
      method: 'POST', body: JSON.stringify(body),
    })
    if (data.status !== 'success') throw new Error(data.message || 'Briefing request failed')
    return data
  }

  async getCalendarEvents(start?: string, end?: string, categoryId?: string): Promise<CalendarEvent[]> {
    const query = new URLSearchParams()
    if (start) query.set('start', start)
    if (end) query.set('end', end)
    if (categoryId) query.set('category_id', categoryId)
    return (await this.briefingRequest<{ events: CalendarEvent[] }>(`/api/calendar/events?${query}`)).events
  }

  async createCalendarEvent(payload: CalendarEventInput): Promise<CalendarEvent> {
    return (await this.briefingRequest<{ event: CalendarEvent }>('/api/calendar/events', payload)).event
  }

  async updateCalendarEvent(id: string, payload: CalendarEventInput): Promise<CalendarEvent> {
    return (await this.briefingRequest<{ event: CalendarEvent }>('/api/calendar/events/update', { id, ...payload })).event
  }

  async deleteCalendarEvent(id: string): Promise<void> {
    await this.briefingRequest('/api/calendar/events/delete', { id })
  }

  async getAppleCalendar(): Promise<AppleCalendarConnection> {
    return (await this.briefingRequest<{ connection: AppleCalendarConnection }>('/api/calendar/apple/status')).connection
  }

  async requestAppleCalendarAccess(): Promise<AppleCalendarConnection> {
    return (await this.briefingRequest<{ connection: AppleCalendarConnection }>('/api/calendar/apple/access', {})).connection
  }

  async setAppleCalendarAuto(enabled: boolean): Promise<AppleCalendarConnection> {
    return (await this.briefingRequest<{ connection: AppleCalendarConnection }>('/api/calendar/apple/auto', { enabled })).connection
  }

  async getAppleReminders(): Promise<AppleReminderConnection> {
    return (await this.briefingRequest<{ connection: AppleReminderConnection }>('/api/todos/apple/status')).connection
  }

  async setAppleRemindersAuto(enabled: boolean): Promise<AppleReminderConnection> {
    return (await this.briefingRequest<{ connection: AppleReminderConnection }>('/api/todos/apple/auto', { enabled })).connection
  }

  async requestAppleRemindersAccess(): Promise<AppleReminderConnection> {
    return (await this.briefingRequest<{ connection: AppleReminderConnection }>('/api/todos/apple/access', {})).connection
  }

  async previewAppleRemindersScope(listIds: string[], direction: AppleReminderConnection['direction']): Promise<{
    preview: { new: number; updated: number; skipped: number; conflicts: number }
    preview_token: string
  }> {
    return this.briefingRequest('/api/todos/apple/scope-preview', { list_ids: listIds, direction })
  }

  async configureAppleReminders(listIds: string[], direction: AppleReminderConnection['direction'], previewToken: string): Promise<{ connection: AppleReminderConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/todos/apple/configure', { list_ids: listIds, direction,
      preview_token: previewToken, confirm: true })
  }

  async syncAppleReminders(confirmDeletions = false, confirmLocalDeletions = false): Promise<{ connection: AppleReminderConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/todos/apple/sync', {
      confirm_deletions: confirmDeletions, confirm_local_deletions: confirmLocalDeletions,
    })
  }

  async disconnectAppleReminders(): Promise<AppleReminderConnection> {
    return (await this.briefingRequest<{ connection: AppleReminderConnection }>('/api/todos/apple/disconnect', {})).connection
  }

  async resolveAppleRemindersConflict(todoId: string, choice: 'keep_stella' | 'keep_apple'): Promise<AppleReminderConnection> {
    return (await this.briefingRequest<{ connection: AppleReminderConnection }>('/api/todos/apple/resolve', { todo_id: todoId, choice })).connection
  }

  async getAppleCalendarItems(calendarId: string, start: string, end: string): Promise<{ event_id: string; title: string }[]> {
    return (await this.briefingRequest<{ items: { event_id: string; title: string }[] }>('/api/calendar/apple/items', {
      calendar_id: calendarId, start, end,
    })).items
  }

  async getAppleRemindersItems(listId: string): Promise<{ reminder_id: string; title: string }[]> {
    return (await this.briefingRequest<{ items: { reminder_id: string; title: string }[] }>('/api/todos/apple/items', {
      list_id: listId,
    })).items
  }

  async previewAppleCalendarItems(direction: 'import' | 'export', calendarId: string, itemIds: string[]): Promise<{
    preview: { new: number; updated: number; skipped: number; conflicts: number }; preview_token: string
  }> {
    return this.briefingRequest('/api/calendar/apple/preview', {
      direction, calendar_id: calendarId, item_ids: itemIds,
    })
  }

  async previewAppleRemindersItems(direction: 'import' | 'export', listId: string, itemIds: string[]): Promise<{
    preview: { new: number; updated: number; skipped: number; conflicts: number }; preview_token: string
  }> {
    return this.briefingRequest('/api/todos/apple/preview', {
      direction, list_id: listId, item_ids: itemIds,
    })
  }

  async transferAppleCalendarItems(direction: 'import' | 'export', calendarId: string, itemIds: string[], previewToken: string): Promise<{ connection: AppleCalendarConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/calendar/apple/one-time', {
      direction, calendar_id: calendarId, item_ids: itemIds, preview_token: previewToken, confirm: true,
    })
  }

  async transferAppleRemindersItems(direction: 'import' | 'export', listId: string, itemIds: string[], previewToken: string): Promise<{ connection: AppleReminderConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/todos/apple/one-time', {
      direction, list_id: listId, item_ids: itemIds, preview_token: previewToken, confirm: true,
    })
  }

  async previewAppleCalendarScope(calendarIds: string[], direction: AppleCalendarConnection['direction']): Promise<{
    preview: { new: number; updated: number; skipped: number; conflicts: number; failed_calendar_ids: string[] }
    preview_token: string
  }> {
    return this.briefingRequest('/api/calendar/apple/scope-preview', { calendar_ids: calendarIds, direction })
  }

  async configureAppleCalendar(calendarIds: string[], direction: AppleCalendarConnection['direction'], previewToken: string): Promise<{ connection: AppleCalendarConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/calendar/apple/configure', { calendar_ids: calendarIds, direction,
      preview_token: previewToken, confirm: true })
  }

  async syncAppleCalendar(confirmDeletions = false, confirmLocalDeletions = false): Promise<{ connection: AppleCalendarConnection; result: AppleCalendarSyncResult }> {
    return this.briefingRequest('/api/calendar/apple/sync', {
      confirm_deletions: confirmDeletions, confirm_local_deletions: confirmLocalDeletions,
    })
  }

  async disconnectAppleCalendar(): Promise<AppleCalendarConnection> {
    return (await this.briefingRequest<{ connection: AppleCalendarConnection }>('/api/calendar/apple/disconnect', {})).connection
  }

  async resolveAppleCalendarConflict(stellaId: string, choice: 'keep_stella' | 'keep_apple'): Promise<AppleCalendarConnection> {
    return (await this.briefingRequest<{ connection: AppleCalendarConnection }>('/api/calendar/apple/resolve', { stella_id: stellaId, choice })).connection
  }

  async getTodos(start?: string, end?: string, includeCompleted = true): Promise<Todo[]> {
    const query = new URLSearchParams()
    if (start) query.set('start', start)
    if (end) query.set('end', end)
    if (!includeCompleted) query.set('include_completed', 'false')
    return (await this.briefingRequest<{ todos: Todo[] }>(`/api/todos?${query}`)).todos
  }

  async createTodo(payload: TodoInput): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos', payload)).todo
  }

  async getTodoFocus(today: string): Promise<Todo[]> {
    return (await this.briefingRequest<{ todos: Todo[] }>(`/api/todos?mode=focus&today=${encodeURIComponent(today)}`)).todos
  }

  async completeTodoChecklist(id: string, itemId: string, completed: boolean): Promise<void> {
    await this.briefingRequest('/api/todos/checklist/complete', { id, item_id: itemId, completed })
  }

  async updateTodo(id: string, payload: TodoInput): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/update', { id, ...payload })).todo
  }

  async changeTodoStatus(id: string, status: Todo['status'], force = false): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/status', { id, status, force })).todo
  }

  async addSubtask(parentId: string, payload: TodoInput): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/subtasks', { parent_id: parentId, ...payload })).todo
  }

  async moveTodo(id: string, parentId: string | null, position?: number): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/move', { id, parent_id: parentId, position })).todo
  }

  async addTodoDependency(id: string, prerequisiteId: string): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/dependencies/add',
      { id, prerequisite_id: prerequisiteId })).todo
  }

  async removeTodoDependency(id: string, prerequisiteId: string): Promise<Todo> {
    return (await this.briefingRequest<{ todo: Todo }>('/api/todos/dependencies/remove',
      { id, prerequisite_id: prerequisiteId })).todo
  }

  async completeTodo(id: string, completed: boolean, force = false): Promise<void> {
    await this.briefingRequest('/api/todos/complete', { id, completed, force })
  }

  async deleteTodo(id: string): Promise<void> {
    await this.briefingRequest('/api/todos/delete', { id })
  }

  async getUncertainReminders(): Promise<UncertainReminder[]> {
    return (await this.briefingRequest<{ reminders: UncertainReminder[] }>(
      '/api/todos/reminders/uncertain')).reminders
  }

  async retryUncertainReminder(deliveryId: string): Promise<boolean> {
    return (await this.briefingRequest<{ queued: boolean }>(
      '/api/todos/reminders/retry', { delivery_id: deliveryId })).queued
  }


  async importChinaHolidays(year: number): Promise<{ year: number; added: number; total: number }> {
    return this.briefingRequest('/api/calendar/import/holidays', { year })
  }

  async createSpecialDate(payload: { title: string; date: string; annual: boolean; description: string; timezone: string }): Promise<CalendarEvent> {
    return (await this.briefingRequest<{ event: CalendarEvent }>('/api/calendar/special-dates', payload)).event
  }

  async importSpecialDates(content: string, format: 'ics' | 'csv', timezone: string): Promise<{ added: number; total: number }> {
    return this.briefingRequest('/api/calendar/import/special-dates', { content, format, timezone })
  }

  async getCalendarCategories(): Promise<CalendarCategory[]> {
    return (await this.briefingRequest<{ categories: CalendarCategory[] }>('/api/calendar/categories')).categories
  }

  async createCalendarCategory(name: string, color: string): Promise<CalendarCategory> {
    return (await this.briefingRequest<{ category: CalendarCategory }>('/api/calendar/categories', { name, color })).category
  }

  async updateCalendarCategory(id: string, name: string, color: string): Promise<CalendarCategory> {
    return (await this.briefingRequest<{ category: CalendarCategory }>('/api/calendar/categories/update', { id, name, color })).category
  }

  async deleteCalendarCategory(id: string): Promise<void> {
    await this.briefingRequest('/api/calendar/categories/delete', { id })
  }

  async getBriefings(): Promise<Briefing[]> {
    return (await this.briefingRequest<{ briefings: Briefing[] }>('/api/briefings?kind=morning')).briefings
  }

  async getBriefing(id: string): Promise<BriefingDetail> {
    return this.briefingRequest(`/api/briefings/${encodeURIComponent(id)}`)
  }

  async getBriefingOverview(): Promise<Pick<BriefingDetail, 'items' | 'actions' | 'preferences'>> {
    return this.briefingRequest('/api/briefings/overview')
  }

  async decideBriefing(id: string, decision: BriefingDecision): Promise<BriefingActionReceipt> {
    return (await this.briefingRequest<{ receipt: BriefingActionReceipt }>('/api/briefings/actions', { id, decision })).receipt
  }

  async getBriefingTargets(kind: 'todo' | 'calendar', query = ''): Promise<(Todo | CalendarEvent)[]> {
    return (await this.briefingRequest<{ targets: (Todo | CalendarEvent)[] }>(`/api/briefings/actions/targets?${new URLSearchParams({ kind, query })}`)).targets
  }

  async getBriefingAuthorizations(): Promise<BriefingAuthorization[]> {
    return (await this.briefingRequest<{ rules: BriefingAuthorization[] }>('/api/briefings/authorizations')).rules
  }

  async saveBriefingAuthorization(rule: Omit<BriefingAuthorization, 'id'>): Promise<BriefingAuthorization> {
    return (await this.briefingRequest<{ rule: BriefingAuthorization }>('/api/briefings/authorizations', rule)).rule
  }

  async deleteBriefingAuthorization(id: string): Promise<void> {
    await this.briefingRequest('/api/briefings/authorizations/delete', { id })
  }

  async getBriefingPreferences(): Promise<BriefingPreferences> {
    return (await this.briefingRequest<{ preferences: BriefingPreferences }>('/api/briefings/preferences')).preferences
  }

  async saveBriefingPreferences(preferences: BriefingPreferences): Promise<BriefingPreferences> {
    return (await this.briefingRequest<{ preferences: BriefingPreferences }>('/api/briefings/preferences', preferences)).preferences
  }

  async getBriefingRevision(id: string, number: number): Promise<BriefingDetail> {
    return this.briefingRequest(`/api/briefings/${encodeURIComponent(id)}/revisions/${number}`)
  }

  async runBriefing(operation: 'create' | 'update', briefingDate?: string, sources?: string[]): Promise<BriefingDetail> {
    return this.briefingRequest('/api/briefings/run', { kind: 'morning', operation, briefing_date: briefingDate, sources })
  }

  async getBriefingRunProgress(): Promise<BriefingRunProgress | null> {
    return (await this.briefingRequest<{ progress: BriefingRunProgress | null }>(
      '/api/briefings/run/progress')).progress
  }

  async getBriefingSources(): Promise<BriefingSource[]> {
    return (await this.briefingRequest<{ sources: BriefingSource[] }>('/api/briefings/sources')).sources
  }

  async getElearningSettings(): Promise<ElearningSettings> {
    return (await this.briefingRequest<{ settings: ElearningSettings }>('/api/briefings/elearning')).settings
  }

  async saveElearningSettings(payload: ElearningSettingsInput): Promise<ElearningSettings> {
    return (await this.briefingRequest<{ settings: ElearningSettings }>('/api/briefings/elearning', payload)).settings
  }

  async getElearningFileSyncSettings(): Promise<ElearningSettings> {
    return (await this.briefingRequest<{ settings: ElearningSettings }>('/api/elearning/file-sync')).settings
  }

  async saveElearningFileSyncSettings(enabled: boolean, root: string): Promise<ElearningSettings> {
    return (await this.briefingRequest<{ settings: ElearningSettings }>(
      '/api/elearning/file-sync', { file_sync_enabled: enabled, file_sync_root: root })).settings
  }

  async deleteElearningSource(): Promise<void> {
    await this.briefingRequest('/api/briefings/elearning', { action: 'delete' })
  }

  async testElearningSettings(payload: ElearningSettingsInput): Promise<{ id: string; name: string }[]> {
    return (await this.briefingRequest<{ courses: { id: string; name: string }[] }>('/api/briefings/elearning/test', payload)).courses
  }

  async updateBriefingItem(id: string, status: BriefingItemStatus): Promise<BriefingItem> {
    return (await this.briefingRequest<{ item: BriefingItem }>('/api/briefings/items/status', { id, status })).item
  }

  async getBriefingRules(): Promise<BriefingRule[]> {
    return (await this.getBriefingRuleDocuments()).rules
  }

  async getBriefingRuleDocuments(): Promise<{ rules: BriefingRule[]; default_text: string }> {
    return this.briefingRequest('/api/briefings/rules')
  }

  async createBriefingRule(payload: BriefingRuleInput): Promise<BriefingRule> {
    return (await this.briefingRequest<{ rule: BriefingRule }>('/api/briefings/rules', payload)).rule
  }

  async updateBriefingRule(id: string, payload: Partial<BriefingRuleInput>): Promise<BriefingRule> {
    return (await this.briefingRequest<{ rule: BriefingRule }>('/api/briefings/rules/update', { ...payload, id })).rule
  }

  async deleteBriefingRule(id: string): Promise<void> {
    await this.briefingRequest('/api/briefings/rules/delete', { id })
  }

  async saveBriefingSettings(payload: BriefingMailboxInput): Promise<{ settings: BriefingSettings; mailbox: BriefingMailbox }> {
    return this.briefingRequest('/api/briefings/settings', payload)
  }

  async testBriefingSettings(payload: BriefingMailboxInput): Promise<BriefingMailboxCheck> {
    return this.briefingRequest('/api/briefings/settings/test', payload)
  }

  async getBriefingSettings(): Promise<BriefingSettings> {
    return (await this.briefingRequest<{ settings: BriefingSettings }>('/api/briefings/settings')).settings
  }

  async deleteBriefingMailbox(id: string): Promise<BriefingSettings> {
    return (await this.briefingRequest<{ settings: BriefingSettings }>('/api/briefings/settings', { action: 'delete', id })).settings
  }

  // ---------------------------------------------------------
  // Bills
  // ---------------------------------------------------------

  async getLedgerEntries(year: number, month: number): Promise<LedgerEntry[]> {
    const data = await this.request<{ status: string; entries?: LedgerEntry[]; message?: string }>(
      `/api/bills/ledger?year=${year}&month=${month}`,
    )
    if (data.status !== 'success') throw new Error(data.message || 'Failed to load ledger')
    return data.entries || []
  }

  async createLedgerEntry(payload: Omit<LedgerEntry, 'id' | 'created_at' | 'updated_at'> & { id?: string }): Promise<LedgerEntry> {
    const data = await this.request<{ status: string; entry?: LedgerEntry; message?: string }>(
      '/api/bills/ledger',
      { method: 'POST', body: JSON.stringify(payload) },
    )
    if (data.status !== 'success' || !data.entry) throw new Error(data.message || 'Failed to create entry')
    return data.entry
  }

  async updateLedgerEntry(entryId: string, payload: Partial<LedgerEntry> & { id?: string }): Promise<LedgerEntry> {
    const data = await this.request<{ status: string; entry?: LedgerEntry; message?: string }>(
      '/api/bills/ledger/update',
      { method: 'POST', body: JSON.stringify({ ...payload, id: entryId }) },
    )
    if (data.status !== 'success' || !data.entry) throw new Error(data.message || 'Failed to update entry')
    return data.entry
  }

  async deleteLedgerEntry(entryId: string): Promise<void> {
    const data = await this.request<ApiResult>('/api/bills/ledger/delete', {
      method: 'POST',
      body: JSON.stringify({ id: entryId }),
    })
    if (data.status !== 'success') throw new Error(data.message || 'Failed to delete entry')
  }

  async exportLedgerXlsx(start: string, end: string): Promise<Blob> {
    const params = new URLSearchParams({ start, end, lang: getLang() })
    const res = await fetch(`${this.baseUrl}/api/bills/ledger/export?${params.toString()}`, {
      credentials: 'include',
      headers: this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {},
    })
    const ct = res.headers.get('content-type') || ''
    if (!res.ok || ct.includes('json')) {
      let message = `HTTP ${res.status}`
      try {
        const data = await res.json()
        if (data?.message) message = data.message
      } catch {
        /* ignore */
      }
      throw new Error(message)
    }
    return res.blob()
  }

  async getPeriodStatements(periodType: PeriodType, year?: number): Promise<PeriodStatement[]> {
    const params = new URLSearchParams({ period_type: periodType })
    if (year != null) params.set('year', String(year))
    const data = await this.request<{ status: string; statements?: PeriodStatement[]; message?: string }>(
      `/api/bills/statements?${params.toString()}`,
    )
    if (data.status !== 'success') throw new Error(data.message || 'Failed to load statements')
    return data.statements || []
  }

  async getPeriodStatement(statementId: string): Promise<PeriodStatement & { items: PeriodStatementItem[] }> {
    const data = await this.request<{
      status: string
      statement?: PeriodStatement & { items: PeriodStatementItem[] }
      message?: string
    }>(`/api/bills/statements/${encodeURIComponent(statementId)}`)
    if (data.status !== 'success' || !data.statement) {
      throw new Error(data.message || 'Failed to load statement')
    }
    return { ...data.statement, items: data.statement.items || [] }
  }

  // ---------------------------------------------------------
  // Voice
  // ---------------------------------------------------------

  async voiceAsr(audio: File | Blob): Promise<{ status: string; text?: string; audio_url?: string; message?: string }> {
    const formData = new FormData()
    // Match the file suffix to the actual container so the backend picks the
    // right extension (mirrors the web console's mic upload).
    const extByMime: Record<string, string> = {
      'audio/webm': 'webm',
      'audio/ogg': 'ogg',
      'audio/mp4': 'm4a',
      'audio/mpeg': 'mp3',
    }
    const mime = (audio.type || '').split(';')[0]
    const name =
      audio instanceof File && audio.name ? audio.name : `recording.${extByMime[mime] || 'webm'}`
    formData.append('file', audio, name)
    return this.postFormData('/api/voice/asr', formData)
  }

  async voiceTts(text: string, sessionId?: string): Promise<{ status: string; audio_url?: string; message?: string }> {
    return this.request('/api/voice/tts', {
      method: 'POST',
      body: JSON.stringify({ text, session_id: sessionId }),
    })
  }

  // ---------------------------------------------------------
  // Logs / version
  // ---------------------------------------------------------

  createLogStream(): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/api/logs`))
  }

  // Full run.log as a downloadable attachment. Carries the token in the query
  // string like the other file endpoints so it works under web_password.
  getLogDownloadUrl(): string {
    return this.withToken(`${this.baseUrl}/api/logs/download`)
  }

  async getVersion(): Promise<string> {
    const data = await this.request<{ version: string }>('/api/version')
    return data.version
  }

  // ---------------------------------------------------------
  // Auth (web_password) — placeholder for future use
  // ---------------------------------------------------------

  async authCheck(): Promise<{ status: string; auth_required: boolean; authenticated?: boolean }> {
    return this.request('/auth/check')
  }

  async authLogin(password: string): Promise<ApiResult & { token?: string }> {
    const res = await this.request<ApiResult & { token?: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    })
    if (res.status === 'success' && res.token) {
      this.setAuthToken(res.token)
    }
    return res
  }

  async authLogout(): Promise<ApiResult> {
    this.setAuthToken(null)
    return this.request('/auth/logout', { method: 'POST' })
  }
}

export const apiClient = new ApiClient()
export default apiClient
