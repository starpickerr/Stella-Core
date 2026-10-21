export interface DataSourceInfo {
  id: string
  name: string
  kind: string
  account_id?: string | null
  operations?: string[]
  representation?: 'collection' | 'reference'
  resource_kinds?: string[]
  provider: string
  enabled: boolean
  available: boolean
  connection?: string
  settings_url?: string
  storage: 'reference' | 'cache' | 'persistent'
  retention_days: number
  running: boolean
  last_run: number | null
  error: string
}
export interface DataRecord {
  id: string
  source_id: string
  version: string
  item: { source: string; account_id: string; source_id: string; title: string; snippet: string; occurred_at: string; url?: string; payload: Record<string, unknown> }
}
export interface DataSubscription { id: string; source_id: string; consumer: string; filter: { q?: string }; enabled: boolean }
export interface DataDelivery { subscription_id: string; event_id: string; state: string; attempts: number; error: string; type: string; record_id: string; seq: number }
export interface StorageCategory { id: string; name: { zh: string; en: string }; path: string; bytes: number; retention: { zh: string; en: string }; actions: string[] }
export interface DataSnapshot {
  status: string
  sources: DataSourceInfo[]
  record_count: number
  subscriptions: DataSubscription[]
  deliveries: DataDelivery[]
  consumers: { id: string; name: string }[]
  storage: { available: boolean; categories: StorageCategory[] }
  errors: { provider: string; message: string }[]
  scope?: { agent: string; session: string; kind: string; root: string }
  agents?: { id: string; name: string }[]
  workspaces?: { session: string; name: string }[]
}
export interface DataBrowseScope { agent?: string; session?: string }
export interface DataRecords { status: string; records: DataRecord[]; total: number; offset: number; limit: number }
export interface DataCommandResult {
  status: string
  message?: string
  sync?: { processed: number; errors: string[] }
  delivery?: { delivered: number; failed: number }
  export?: { format: string; source_id: string; records: DataRecord[] }
  removed?: number
}

export interface DataResource { id: string; source_id: string; provider: string; reference: string; kind: string; name: string; operations: string[] }
export interface DataResources { status: string; resources: DataResource[]; total: number; offset: number; limit: number }
export interface DataResourceContent { status: string; resource: DataResource; content: unknown }
