// ============================================================
// Electron bridge
// ============================================================

export interface ElectronAPI {
  getBackendPort: () => Promise<number | null>
  getBackendStatus: () => Promise<string>
  /** The last backend failure, queryable so it can't be missed by timing. */
  getBackendError: () => Promise<BackendFailure | null>
  /** Data dir holding config.json and run.log (~/.stella in packaged builds). */
  getDataDir: () => Promise<string>
  restartBackend: () => Promise<boolean>
  selectDirectory: () => Promise<string | null>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  /** Open a local file with the OS default app. Resolves to '' on success. */
  openPath: (targetPath: string) => Promise<string>
  // Listener registrars return an unsubscribe fn for cleanup.
  onBackendStatus: (callback: (data: BackendStatusEvent) => void) => () => void
  onBackendLog: (callback: (line: string) => void) => () => void
  windowMinimize: () => Promise<void>
  windowMaximize: () => Promise<boolean>
  windowClose: () => Promise<void>
  windowIsMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (maximized: boolean) => void) => () => void
  onMenuAction?: (callback: (action: string) => void) => () => void
  // Current app version string (e.g. "0.0.5").
  getAppVersion?: () => Promise<string>
  // Launch-at-login toggle (macOS + Windows). get returns the effective state;
  // set returns the real outcome so the UI can surface refusals/errors.
  getLoginItemEnabled?: () => Promise<boolean>
  setLoginItemEnabled?: (
    enabled: boolean
  ) => Promise<{ ok: boolean; enabled: boolean; error: string }>
  // Themes (bundled + user themes from ~/.stella/themes), images inlined.
  listThemes?: () => Promise<Record<string, unknown>[]>
  getThemesDir?: () => Promise<string>
  // Optional app config: first-run default theme + display name. Null when
  // the build ships no app config (standard build).
  getAppConfig?: () => Promise<{ defaultTheme?: string; appName?: string } | null>
  // Generic HTTPS relay via the main process (bypasses renderer CORS).
  httpRelay?: (req: {
    url: string
    method?: string
    headers?: Record<string, string>
    body?: string
  }) => Promise<{ ok: boolean; status: number; headers: Record<string, string>; body: string }>
  // Update checks against GitHub Releases. downloadUpdate opens the given URL
  // (or the releases page) in the system browser.
  checkForUpdate?: () => Promise<void>
  downloadUpdate?: (url?: string) => Promise<void>
  onUpdateStatus?: (callback: (status: UpdateStatus) => void) => () => void
  // Override the window/Dock/taskbar icon and title at runtime (cached across
  // launches). Used by product extensions; unused by the standard build.
  setAppIcon?: (iconUrl: string, icoUrl?: string) => Promise<boolean>
  setAppTitle?: (title: string) => Promise<boolean>
  // Show a native OS notification; clicking it focuses the window and fires
  // onOpenSession with the session id.
  notify?: (payload: { title?: string; body?: string; sessionId?: string; silent?: boolean; showWhenFocused?: boolean }) => Promise<boolean>
  onOpenSession?: (callback: (sessionId: string) => void) => () => void
  platform: string
  // OS UI language (e.g. "zh-CN"); used to default the language on first run.
  systemLocale?: string
}

// Mirrors UpdateStatus in src/main/updater.ts.
export type UpdateStatus =
  | { state: 'checking' }
  // userInitiated: true when the check came from an explicit "check for update"
  // click; drives whether a dismissed version re-opens the panel (see store).
  | {
      state: 'available'
      version: string
      notes?: string
      pageUrl: string
      assetUrl?: string
      userInitiated?: boolean
    }
  | { state: 'not-available' }
  | { state: 'error'; message: string; pageUrl: string; userInitiated?: boolean }

/** Why the backend failed. Mirrors BackendErrorCode in main/python-manager.ts. */
export type BackendErrorCode =
  | 'backend_removed'
  | 'backend_missing'
  | 'backend_blocked'
  | 'backend_crashed'
  | 'backend_timeout'
  | 'backend_unresponsive'

export interface BackendFailure {
  code: BackendErrorCode
  message: string
  path?: string
}

export interface BackendStatusEvent {
  // 'lost' means a previously-ready backend stopped answering and the main
  // process is restarting it.
  status: 'ready' | 'error' | 'starting' | 'lost'
  port?: number
  error?: string
  // Present on 'error': lets the UI explain the specific failure and what to
  // do about it, rather than falling back to one generic sentence.
  code?: BackendErrorCode
  path?: string
}

// ============================================================
// Chat / messages / streaming
// ============================================================

export type Role = 'user' | 'assistant' | 'system'

/** One tool call made inside a sub agent, shown under that sub agent's step. */
export interface SubStep {
  id: string
  name: string
  args?: string
  status?: string
  execution_time?: number
  error?: string
}

/** A single ordered step inside an assistant turn (matches backend history). */
export interface MessageStep {
  type: 'thinking' | 'content' | 'tool'
  content?: string
  // tool step fields
  id?: string
  name?: string
  arguments?: Record<string, unknown>
  result?: string
  is_error?: boolean
  status?: string
  execution_time?: number
  /** The outcome written for a person. Rendered instead of `result`, which is
   * the form the model was handed. */
  display?: string
  /** Work done inside this step, for a tool that drives sub agents. */
  substeps?: SubStep[]
  /** Set when the tool was refused by the session's permission mode, so the UI
   * can render an actionable "adjust permissions" hint rather than a plain error. */
  permission_denied?: boolean
  /** The mode that refused the call (read-only / workspace-write / full-access). */
  permission_mode?: string
}

/** Local UI message model (superset of backend history message). */
export interface ChatMessage {
  id: string
  role: Role
  content: string
  /** Unix seconds. Backend history uses `created_at`; we normalize to `timestamp`. */
  timestamp: number
  attachments?: Attachment[]
  /** User-facing files the agent wrote during this turn, shown as file cards. */
  artifacts?: Artifact[]
  /** Ordered steps (thinking / content / tool). Preferred over legacy toolCalls. */
  steps?: MessageStep[]
  /** Legacy live-stream tool events (kept for backward compat during streaming). */
  toolCalls?: ToolCall[]
  /** Reasoning text streamed via `reasoning` SSE events. */
  reasoning?: string
  /** Sequence numbers from backend (for delete/regenerate). */
  userSeq?: number
  botSeq?: number
  /** Self-evolution bubble flag; 'divider' renders a context-cleared separator. */
  kind?: 'evolution' | 'divider'
  extras?: Record<string, unknown>
  isStreaming?: boolean
  isCancelled?: boolean
  error?: string
  /** request_id of a server-pushed (scheduler) message, used to dedupe polls. */
  pushRequestId?: string
}

export interface Attachment {
  file_path: string
  file_name: string
  /** `workspace_ref` points at an existing workspace file (dragged from the
   *  file panel or picked with `@`) and is referenced in place, not uploaded. */
  file_type: 'image' | 'video' | 'file' | 'directory' | 'workspace_ref'
  /** For `workspace_ref`: whether the reference points at a folder. */
  is_dir?: boolean
  preview_url?: string
  /** Local absolute path (set for files sent via the `send` tool) so the
   *  desktop client can open them directly with the OS default app. */
  abs_path?: string
}

// ============================================================
// Workspace files / artifacts
// ============================================================

/** Coarse file classes the preview panel knows how to render. */
export type FileKind =
  | 'directory'
  | 'html'
  | 'markdown'
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'csv'
  | 'code'
  | 'office'
  | 'text'
  | 'file'

export interface WorkspaceEntry {
  name: string
  /** Workspace-relative path. */
  path: string
  is_dir: boolean
  kind: FileKind
  previewable: boolean
  size: number
  mtime: number
  abs_path?: string
  raw_url?: string
  preview_url?: string
}

export interface WorkspaceTree {
  path: string
  root: string
  entries: WorkspaceEntry[]
  truncated: boolean
}

// ============================================================
// Project workspace (per-session working directory)
// ============================================================

/** A project directory the user can point a session at. */
export interface ProjectRef {
  path: string
  name: string
  /** Unix seconds of last use; present on recents. */
  ts?: number
  conversation_count?: number
}

/** Project picker state for a session (from /api/projects). */
export interface ProjectState {
  /** null when the session uses the default workspace. */
  current: ProjectRef | null
  default_workspace: string
  projects_root?: string
  recents: ProjectRef[]
}

/** A user-facing file the agent wrote during a turn. */
export interface Artifact {
  abs_path: string
  rel_path: string
  file_name: string
  kind: FileKind
  previewable: boolean
  size: number
  raw_url: string
  preview_url: string
}

/** Live tool event during SSE streaming. */
export interface ToolCall {
  type: 'tool_start' | 'tool_end' | 'tool_progress'
  tool: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  result?: string
  status?: string
  execution_time?: number
}

/** All SSE event types emitted on /stream. */
export type StreamEventType =
  | 'delta'
  | 'reasoning'
  | 'tool_start'
  | 'tool_progress'
  | 'tool_end'
  | 'subagent_step'
  | 'message_end'
  | 'phase'
  | 'file_to_send'
  | 'artifact'
  | 'image'
  | 'video'
  | 'file'
  | 'text'
  | 'done'
  | 'cancelled'
  | 'voice_attach'
  | 'error'

export interface StreamEvent {
  type: StreamEventType
  content?: string
  tool?: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  status?: string
  result?: string
  /** `tool_end`: the outcome written for a person, when the tool wrote one. */
  display?: string
  execution_time?: number
  has_tool_calls?: boolean
  /** `tool_end`: true when the call was refused by the session permission mode. */
  permission_denied?: boolean
  /** `tool_end`: the mode that refused the call. */
  permission_mode?: string
  /** `subagent_step` event fields: which step of which card, and how it went. */
  card_id?: string
  step_id?: string
  phase?: 'start' | 'end'
  error?: string
  path?: string
  abs_path?: string
  file_name?: string
  file_type?: string
  web_url?: string
  audio_url?: string
  /** `artifact` event fields. */
  rel_path?: string
  kind?: FileKind
  previewable?: boolean
  size?: number
  raw_url?: string
  preview_url?: string
  request_id?: string
  timestamp?: number
  user_seq?: number
  bot_seq?: number
  message?: string
}

// ============================================================
// Sessions / history
// ============================================================

export interface SessionItem {
  session_id: string
  title: string
  created_at: number
  last_active: number
  msg_count: number
  /** User-pinned to the top of its group. */
  pinned?: boolean
  /** Bound project workspace, or null/absent for the default workspace. */
  project?: { path: string; name: string } | null
}

export interface SessionsPage {
  sessions: SessionItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  /** Durable project entries, including projects without conversations. */
  projects: ProjectRef[]
  /** User-defined order of project entries. */
  project_order?: string[]
}

export interface WorkspaceShare {
  id: string
  path: string
  name: string
  owner_agent: string
  owner_session: string
  recipient_session: string
  access: 'read' | 'write'
  active: boolean
}

/** Per-session model + permission overrides (from /api/sessions/{id}/settings). */
export interface SessionModelProvider {
  id: string
  label: string | { zh: string; en: string }
  models: string[]
}

export interface SessionSettingsState {
  model: {
    model: string
    provider: string
    source: 'session' | 'global'
    global: { model: string; provider: string }
    providers: SessionModelProvider[]
  }
  permission: {
    source: 'session' | 'project' | 'global' | 'mixed'
    preset: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
    global_preset: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
    mode: 'read-only' | 'workspace-write' | 'full-access' | 'custom'
    base_preset: 'read-only' | 'workspace-write' | 'full-access'
    rules: Record<string, 'allow' | 'confirm' | 'deny'>
    policy: import('./api/client').SecurityPolicy
    mode_definitions: import('./api/client').SecurityModeDefinition[]
    authorized_roots: string[]
    project: string | null
    error?: string | null
    process_isolation: { status: 'enabled' | 'unavailable' | 'full-access'; reason: string }
    presets: string[]
  }
}

/** Backend history message (as returned by /api/history). */
export interface HistoryMessage {
  role: Role
  content: string
  created_at: number
  steps?: MessageStep[]
  tool_calls?: Array<{ id?: string; name: string; arguments?: Record<string, unknown>; result?: string }>
  reasoning?: string
  kind?: 'evolution'
  extras?: Record<string, unknown>
  /** Files written this turn, rebuilt server-side from the write/edit steps. */
  artifacts?: Artifact[]
  /** Per-message sequence number used by delete/regenerate APIs. */
  _seq?: number
}

export interface PendingAdmission {
  run_id: string
  user_content: {type: string; text?: string}[]
  status: string
  clear_history: boolean
}

export interface HistoryPage {
  pending_admissions?: PendingAdmission[]
  messages: HistoryMessage[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  context_start_seq?: number
}

// ============================================================
// Config
// ============================================================

/** A label that may be localized (some providers/channels return {zh,en}). */
export type LocalizedLabel = string | { zh: string; en: string }

export interface ReasoningOption {
  value: string
  label: string
}

export interface ReasoningCapability {
  supported: boolean
  param?: string
  default?: string
  thinking_only?: boolean
  options: ReasoningOption[]
}

export interface ProviderMeta {
  label: LocalizedLabel
  models: string[]
  reasoning?: ReasoningCapability
  reasoning_by_model?: Record<string, ReasoningCapability>
  api_base_key?: string | null
  api_base_default?: string | null
  api_base_placeholder?: string
  api_key_field?: string | null
  [k: string]: unknown
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
  enable_thinking?: boolean
  reasoning_effort?: string
  reasoning_effort_by_model?: Record<string, string>
  subagent_enabled?: boolean
  self_evolution_enabled?: boolean
  api_bases: Record<string, string>
  api_keys: Record<string, string>
  providers: Record<string, ProviderMeta>
  web_password_masked?: string
}

// ============================================================
// Models console (/api/models)
// ============================================================

// A model/voice entry can be a bare id or an annotated {value, hint} object.
export interface ModelOption {
  value: string
  hint?: string
}
export type ModelEntry = string | ModelOption

export interface ModelProvider {
  id: string
  label: LocalizedLabel
  configured: boolean
  is_custom: boolean
  custom_id?: string
  custom_name?: string
  model?: string
  active?: boolean
  api_key_field?: string | null
  api_base_field?: string | null
  api_key_masked?: string
  api_base?: string
  protocol_id?: string
  api_base_default?: string
  api_base_placeholder?: string
  models: ModelEntry[]
}

export type CapabilityKey = 'chat' | 'vision' | 'asr' | 'tts' | 'embedding' | 'image' | 'search'

// Search providers are described as objects (unlike other capabilities which
// list provider ids only).
export interface SearchProviderMeta {
  id: string
  label: LocalizedLabel
  configured: boolean
  needs_dedicated_key: boolean
  api_key_masked?: string
}

export interface CapabilityState {
  editable?: boolean
  current_provider?: string
  current_model?: string
  protocol_id?: string
  current_voice?: string
  current_dim?: number | null
  suggested_provider?: string
  providers?: string[]
  // provider_models entries are string | {value,hint}
  provider_models?: Record<string, ModelEntry[]>
  // tts only: voices keyed by provider; linkai keyed further by model id
  provider_voices?: Record<string, ModelEntry[] | Record<string, ModelEntry[]>>
  // vision/image
  strategy?: string
  user_specified_model?: string
  fallback_provider?: string
  fallback_model?: string
  // tts
  reply_mode?: 'off' | 'voice_if_voice' | 'always'
  use_linkai?: boolean
  // image
  runtime_active?: boolean
  note?: string
  // search
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
  [k: string]: unknown
}

export interface SearchCapabilityState {
  editable?: boolean
  providers: SearchProviderMeta[]
  strategy?: 'auto' | 'fixed' | string
  current_provider?: string
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
}

export interface ModelsData {
  status?: string
  providers: ModelProvider[]
  capabilities: {
    chat: CapabilityState
    vision: CapabilityState
    asr: CapabilityState
    tts: CapabilityState
    embedding: CapabilityState
    image: CapabilityState
    // search has a richer providers[] shape
    search: SearchCapabilityState
  }
}

export type ModelsAction =
  | { action: 'set_provider'; provider_id: string; api_key?: string; api_base?: string; protocol_id?: string }
  | { action: 'delete_provider'; provider_id: string }
  | { action: 'set_custom_provider'; name: string; id?: string; api_base: string; api_key?: string; model?: string; models?: string[]; protocol_id?: string; make_active?: boolean }
  | { action: 'delete_custom_provider'; id: string }
  | { action: 'set_active_custom_provider'; id: string }
  | { action: 'set_capability'; capability: CapabilityKey; provider_id?: string; model?: string; protocol_id?: string; voice?: string; strategy?: string; provider?: string }
  | { action: 'set_voice_reply_mode'; mode: 'off' | 'voice_if_voice' | 'always' }
  | { action: 'set_search_credential'; api_key: string }

// ============================================================
// Channels
// ============================================================

export interface ChannelField {
  key: string
  label: string
  type: 'text' | 'secret' | 'number' | 'bool'
  value?: string | number | boolean
  default?: string | number | boolean
}

export interface ChannelInfo {
  name: string
  label: { zh: string; en: string }
  icon: string
  color: string
  active: boolean
  fields: ChannelField[]
  login_status?: string
}

export type ChannelAction = 'save' | 'connect' | 'disconnect'

// ============================================================
// Tools / skills
// ============================================================

export interface LocalizedCopy {
  zh: string
  en: string
}

export interface ToolInfo {
  id: string
  title: LocalizedCopy
  intro: LocalizedCopy
  detail: LocalizedCopy
  available: boolean
  reason?: LocalizedCopy | null
}

export interface SkillInfo {
  name: string
  display_name?: string
  description: string
  source?: string
  enabled: boolean
  category?: string
}

// ============================================================
// Memory
// ============================================================

export type MemoryCategory = 'memory' | 'dream' | 'evolution'

export interface MemoryItem {
  filename: string
  type: string // global | daily | dream | evolution
  size: number
  updated_at: string
}

export interface MemoryPage {
  list: MemoryItem[]
  total: number
  page: number
  page_size: number
}

// ============================================================
// Knowledge
// ============================================================

export interface KnowledgeFile {
  name: string
  title: string
  size: number
}

// A directory node in the knowledge tree (recursive).
export interface KnowledgeDir {
  dir: string
  files: KnowledgeFile[]
  children: KnowledgeDir[]
}

export interface KnowledgeList {
  root_files?: KnowledgeFile[]
  tree: KnowledgeDir[]
  stats: { pages: number; size: number }
  enabled: boolean
}

export interface KnowledgeGraph {
  nodes: Array<{ id: string; label: string; category?: string }>
  links: Array<{ source: string; target: string }>
}

export type KnowledgeAction =
  | { action: 'create_category'; payload: { path: string } }
  | { action: 'create_document'; payload: { path: string; content: string; overwrite?: boolean } }
  | { action: 'rename_category'; payload: { path: string; new_path: string } }
  | { action: 'delete_category'; payload: { path: string; confirm?: boolean } }
  | { action: 'delete_documents'; payload: { paths: string[] } }
  | { action: 'move_documents'; payload: { paths: string[]; target_category: string } }

// Result row from a bulk import (one per uploaded file).
export interface KnowledgeImportResult {
  status: 'imported' | 'skipped' | 'failed'
  path?: string
  name?: string
  message?: string
}

export interface KnowledgeImportPayload {
  imported: number
  skipped: number
  failed: number
  results: KnowledgeImportResult[]
}

// ============================================================
// Scheduler
// ============================================================

export interface TaskSchedule {
  type: 'cron' | 'interval' | 'once'
  expression?: string
  seconds?: number
  run_at?: string
}

export interface TaskAction {
  type: 'send_message' | 'agent_task' | 'tool_call' | 'skill_call' | 'application_command'
  content?: string
  task_description?: string
  receiver?: string
  receiver_name?: string
  is_group?: boolean
  channel_type?: string
  silent?: boolean
  call_name?: string
  call_params?: Record<string, unknown>
  tool_name?: string
  tool_params?: Record<string, unknown>
  skill_name?: string
  skill_params?: Record<string, unknown>
  domain?: string
  command?: string
  params?: Record<string, unknown> | unknown[]
  execution_session_id?: string
  notify_session_id?: string
  conversation_mode?: 'source' | 'reuse' | 'new'
  source_session_id?: string
  conversation_space?: 'personal' | 'project'
  execution_project_dir?: string
  receive_id_type?: string
}

export interface SchedulerTask {
  id: string
  linked_todo_id?: string
  name: string
  enabled: boolean
  created_at: string
  updated_at: string
  schedule: TaskSchedule
  action: TaskAction
  notification_route?: NotificationRoute | null
  run_permission_mode?: 'read-only' | 'workspace-write' | 'full-access'
  notification_delivery_status?: NotificationDeliveryStatus | null
  next_run_at?: string
  last_run_status?: string
  last_error?: string
}

export interface NotificationDestination {
  channel_type: 'desktop' | 'telegram' | 'wecom_bot' | 'web' | 'feishu' | 'weixin'
  receiver: string
  receive_id_type?: string
  is_group?: boolean
  receiver_name?: string
}

export interface NotificationRoute {
  primary: NotificationDestination | null
  needs_reselect?: boolean
}

export interface NotificationDeliveryStatus {
  status: string
  error?: string
  channel_type?: string
  receiver?: string
}

// ============================================================
// Bills (mirrors agent/bills/schema.sql period_statements)
// ============================================================

export type PeriodType = 'monthly' | 'yearly'

export interface PeriodStatement {
  id: string
  period_type: PeriodType
  year: number
  month: number | null
  start_at: string
  end_at: string
  currency: string
  income_minor: number
  expense_minor: number
  net_minor: number
  status: 'open' | 'closed'
  note: string
  generated_at: string
  created_at: string
  updated_at: string
}

export type LedgerEntryType = 'income' | 'expense'

export type LedgerStatus = 'pending' | 'posted' | 'reversed'

export interface PeriodStatementItem {
  id: string
  statement_id: string
  category: string
  name: string
  entry_type: LedgerEntryType
  amount_minor: number
  entry_count: number
}

/** Mirrors financial_events + ledger_entries. */
export interface LedgerEntry {
  id: string
  amount_minor: number
  currency: string
  category: string
  name: string
  note: string
  entry_type: LedgerEntryType
  txn_type: string
  counterparty: string
  occurred_at: string
  status: LedgerStatus
  created_at: string
  updated_at: string
}

// ============================================================
// Logs
// ============================================================

export interface LogEvent {
  type: 'init' | 'line' | 'error'
  content?: string
  message?: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

// Briefings share the backend snapshot and rule shapes.
export interface CalendarCategory { id: string; name: string; color: string; created_at: string }
export interface CalendarEvent {
  id: string; title: string; description: string; start_at: string; end_at: string
  all_day: number; location: string; category_id: string | null
  series_id?: string; repeat_frequency: 'none' | 'daily' | 'weekly' | 'monthly' | 'yearly'
  repeat_days: string; repeat_until: string | null; repeat_timezone: string | null
  source_type: string | null; source_key: string | null; source_url: string
  user_modified: number; created_at: string; updated_at: string
}
export type CalendarEventInput = Pick<CalendarEvent, 'title' | 'description' | 'start_at' | 'end_at' | 'location'> &
  { all_day: boolean; category_id: string | null; repeat_frequency: CalendarEvent['repeat_frequency']; repeat_days: number[]; repeat_until: string | null; repeat_timezone: string }

export interface AppleCategoryLink {
  apple_id: string
  stella_id: string
  direction: 'import' | 'export' | 'bidirectional'
  enabled: boolean
  apple_name: string
  stella_name: string
  name_conflict: string
}

export interface AppleCalendarConnection {
  supported: boolean
  authorization: 'unsupported' | 'helper_missing' | 'not_determined' | 'denied' | 'restricted' | 'write_only' | 'full_access' | 'unknown'
  connected: boolean
  auto_enabled: boolean
  calendar_ids: string[]
  direction: 'import' | 'export' | 'bidirectional'
  calendars: { id: string; title: string; source: string; writable: boolean }[]
  links?: AppleCategoryLink[]
  last_success: string | null
  error: string
  conflicts: { stella_id: string; reason: string }[]
  pending_deletions: number
  pending_local_deletions: number
}

export interface AppleCalendarSyncResult {
  status: string
  imported: number
  updated: number
  exported: number
  deleted_local: number
  deleted_remote: number
  conflicts: number
  pending_deletions: number
  pending_local_deletions: number
  failed_calendar_ids: string[]
}

export interface AppleReminderConnection extends Omit<AppleCalendarConnection, 'calendar_ids' | 'calendars' | 'conflicts'> {
  list_ids: string[]
  lists: { id: string; title: string; source: string; writable: boolean }[]
  conflicts: { todo_id: string; reason: string }[]
}

export interface Todo {
  id: string; series_id?: string; title: string; notes: string
  status: 'todo' | 'in_progress' | 'waiting' | 'blocked' | 'completed' | 'cancelled'
  parent_id: string | null; sort_order: number; remind_at: string | null
  scheduler_task_id: string | null; reminder_sync_pending: boolean; reminder_sync_error: string
  reminder_delivery?: NotificationRoute | null; reminder_delivery_status?: NotificationDeliveryStatus | null
  subtask_count: number; progress_completed: number; progress_total: number; progress_percent: number
  dependency_ids: string[]; blocked_by: string[]
  due_on: string | null; due_time: string | null; timezone: string; priority: number
  completed_at: string | null; repeat_frequency: 'none' | 'daily' | 'weekly' | 'monthly' | 'yearly'
  repeat_days: string; repeat_until: string | null
  planned_on: string | null; list_name: string; tags: string; flagged: number; checklist: string
  source_type: string | null; source_key: string | null; source_url: string
  user_modified: number; briefing_id: string | null; created_at: string; updated_at: string
}
export interface TodoChecklistItem { id: string; title: string; completed: boolean }
export type TodoInput = Pick<Todo, 'title'> & Partial<Pick<Todo, 'notes' | 'due_on' | 'due_time' | 'timezone' | 'priority' | 'repeat_frequency' | 'repeat_until' | 'status' | 'parent_id' | 'remind_at' | 'reminder_delivery'>> &
  { repeat_days?: number[]; planned_on?: string | null; list_name?: string; tags?: string[];
    flagged?: boolean | number; checklist?: TodoChecklistItem[] }

export interface UncertainReminder {
  delivery_id: string
  todo_id: string
  occurrence_on: string
  title: string
}

export type BriefingStatus = 'running' | 'completed' | 'failed' | 'partial'
export type BriefingItemStatus = 'undo' | 'done' | 'ignored' | 'follow_up'

export interface Briefing {
  source_windows: Record<string, { source: string; account_id: string; name: string; start: string; end: string }>
  updated_sources: string[]
  rule_text: string
  mail_snapshot_available: boolean
  window_start: string | null
  window_end: string | null
  id: string
  status: BriefingStatus
  title: string
  body: string
  fetched_count: number
  kept_count: number
  filtered_count: number
  error_message: string
  generated_at: string | null
  created_at: string
  updated_at: string
}

export interface BriefingItem {
  id: string
  briefing_id: string
  source_item_id: string | null
  source: string
  account_id: string
  source_id: string
  thread_id: string
  section: 'action' | 'fyi'
  status: BriefingItemStatus
  score: number
  sender: string
  title: string
  snippet: string
  occurred_at: string
  url: string
  sort_order: number
  created_at: string
  updated_at: string
  payload: Record<string, unknown>
}

export interface BriefingMail {
  id: string
  source: string
  account_id: string
  source_id: string
  thread_id: string
  sender: string
  sender_email: string
  title: string
  snippet: string
  occurred_at: string
  url: string
  body: string
  body_available: boolean
  category: 'selected' | 'filtered'
  filter_reason: string
}

export interface BriefingDetail {
  briefing: Briefing
  items: BriefingItem[]
  mail: BriefingMail[]
  revisions: { number: number; trigger: string; created_at: string; status: BriefingStatus }[]
  actions?: Record<string, BriefingActionView>
  preferences?: BriefingPreferences
}

export type BriefingActionKind = 'todo' | 'calendar' | 'reminder'
export interface BriefingDecision {
  operation: 'create' | 'link' | 'unlink' | 'ignore' | 'defer' | 'keep' | 'retry' | 'confirm_update' | 'keep_current' | 'remind'
  kind: BriefingActionKind
  target_id?: string
  title?: string
  due_at?: string | null
  planned_on?: string | null
  parent_id?: string | null
  remind_at?: string | null
  start_at?: string
  end_at?: string
  remember?: boolean
}
export interface BriefingActionReceipt {
  kind: BriefingActionKind
  state: 'pending' | 'succeeded' | 'failed' | 'conflict' | 'deleted' | 'detached' | 'ignored' | 'deferred' | 'briefing_only'
  target_id: string | null
  business: Todo | CalendarEvent | null
  error: string
  result: { operation?: string; changes?: Record<string, { current: unknown; source: unknown }>; remind_at?: string }
}
export interface BriefingActionView {
  entity_key: string
  category: 'needs_action' | 'attention' | 'status_update' | 'other'
  information_type: string
  change_type: 'new' | 'changed' | 'unchanged'
  facts: Record<string, unknown>
  todo: BriefingActionReceipt | null
  calendar: BriefingActionReceipt | null
  reminder: BriefingActionReceipt | null
}
export interface BriefingAuthorization {
  id: string
  source: string
  account_id: string
  information_type: string
  course_id: string
  kind: BriefingActionKind | 'sync'
  mode: 'auto' | 'suggest' | 'briefing_only'
  reminder_minutes?: number
}
export interface BriefingPreferences {
  show_low_priority: boolean
  show_ongoing: boolean
  important_types: string[]
  reminder_frequency: 'daily' | 'changes' | 'deadline'
  summary_detail: 'brief' | 'full'
}

export interface BriefingRunProgress {
  briefing_id: string
  body: string
  stage: 'fetching' | 'finalizing'
  completed_sources: number
  total_sources: number
  candidate_count: number
  updated_at: string | null
}

export interface BriefingRule {
  id: string
  enabled: boolean
  source: string
  text: string
  created_at: string
  updated_at: string
}

export type BriefingRuleInput = Pick<BriefingRule, 'text'> & Partial<Pick<BriefingRule, 'enabled' | 'source'>>

export interface BriefingMailbox {
  id: string
  enabled: boolean
  host: string
  user: string
  port: number | string
  password_set: boolean
  password_masked: string
  configured: boolean
  missing: string[]
  folder: string
}

export interface BriefingSettings {
  mailboxes: BriefingMailbox[]
  configured: boolean
  missing: string[]
}

export interface BriefingMailboxInput {
  id?: string
  enabled?: boolean
  action?: 'add' | 'save'
  host: string
  user: string
  port: number
  folder: string
  password?: string
}

export interface BriefingMailboxCheck {
  connected: boolean
  folder_accessible: boolean
  folders: { name: string; label: string }[]
  message?: string
}

export interface BriefingSource {
  id: string
  source: string
  account_id: string
  name: string
}

export interface ElearningSettings {
  enabled: boolean
  file_sync_enabled: boolean
  file_sync_root: string
  configured: boolean
  base_url: string
  username: string
  courses: string[]
  course_options: { id: string; name: string }[]
  account_id: string
  password_set: boolean
  password_masked: string
}

export type ElearningSettingsInput = Pick<ElearningSettings, 'enabled' | 'base_url' | 'username' | 'courses'> & { password?: string }
