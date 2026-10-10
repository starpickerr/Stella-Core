import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Search, RotateCw, Home, ChevronRight, Loader2, AlertTriangle, FolderOpen, Share2 } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import { useWorkspaceStore } from '../store/workspaceStore'
import { iconFor, colorFor, formatSize } from '../lib/fileKind'
import type { SessionItem, WorkspaceEntry, WorkspaceShare } from '../types'

/** MIME type used to tell a workspace-file drag apart from an OS file drop. */
export const WORKSPACE_DRAG_TYPE = 'application/x-stella-workspace-file'

const FileTree: React.FC = () => {
  const preview = useWorkspaceStore((s) => s.preview)
  const current = useWorkspaceStore((s) => s.current)

  const sessionId = useWorkspaceStore((s) => s.sessionId)

  const [dir, setDir] = useState('')
  const [root, setRoot] = useState('')
  const [entries, setEntries] = useState<WorkspaceEntry[]>([])
  const [truncated, setTruncated] = useState(false)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [shares, setShares] = useState<WorkspaceShare[]>([])
  const [shareTarget, setShareTarget] = useState<WorkspaceEntry | null>(null)
  const [recipients, setRecipients] = useState<SessionItem[]>([])
  const [recipient, setRecipient] = useState('')
  const [shareAccess, setShareAccess] = useState<'read' | 'write'>('read')
  const [shareError, setShareError] = useState<string | null>(null)
  const [shareBusy, setShareBusy] = useState(false)

  const loadShares = useCallback(async () => {
    if (!sessionId) { setShares([]); return }
    try {
      const data = await apiClient.workspaceShares(sessionId)
      setShares(data.shares || [])
    } catch (e) {
      setShareError(e instanceof Error ? e.message : String(e))
    }
  }, [sessionId])

  useEffect(() => {
    setShareTarget(null)
    setShareError(null)
    void loadShares()
  }, [loadShares])

  const openShare = async (entry: WorkspaceEntry) => {
    setShareError(null)
    try {
      const page = await apiClient.getSessions(1, 200)
      const choices = page.sessions.filter((row) => row.session_id !== sessionId)
      setRecipients(choices)
      setRecipient(choices[0]?.session_id || '')
      setShareAccess('read')
      setShareTarget(entry)
    } catch (e) {
      setShareError(e instanceof Error ? e.message : String(e))
    }
  }

  const confirmShare = async () => {
    if (!sessionId || !shareTarget || !recipient) return
    setShareBusy(true)
    setShareError(null)
    try {
      await apiClient.createWorkspaceShare(sessionId, shareTarget.path, recipient, shareAccess)
      setShareTarget(null)
      await loadShares()
    } catch (e) {
      setShareError(e instanceof Error ? e.message : String(e))
    } finally {
      setShareBusy(false)
    }
  }

  const revokeShare = async (id: string) => {
    if (!sessionId) return
    setShareBusy(true)
    setShareError(null)
    try {
      await apiClient.revokeWorkspaceShare(sessionId, id)
      await loadShares()
    } catch (e) {
      setShareError(e instanceof Error ? e.message : String(e))
    } finally {
      setShareBusy(false)
    }
  }

  const loadDir = useCallback(async (path: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.workspaceTree(path, sessionId)
      setDir(data.path || '')
      setRoot(data.root || '')
      setEntries(data.entries || [])
      setTruncated(!!data.truncated)
      setSearching(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  // Initial load, plus jumps requested elsewhere (e.g. clicking a directory
  // reference in a message). The counter also covers the case where the panel
  // was closed, so this component mounts with the request already pending.
  const browseDir = useWorkspaceStore((s) => s.browseDir)
  const browseSeq = useWorkspaceStore((s) => s.browseSeq)
  useEffect(() => {
    setQuery('')
    loadDir(browseSeq > 0 ? browseDir || '' : '')
  }, [browseSeq, browseDir, loadDir])

  // Debounce search so typing doesn't hammer the backend walk.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!query.trim()) {
      if (searching) loadDir(dir)
      return
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await apiClient.workspaceSearch(query, 60, sessionId)
        setEntries(data.results || [])
        setTruncated(false)
        setSearching(true)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    }, 220)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // `dir`/`searching` are read only to restore the listing when the query
    // clears; re-running on their change would fight the user's typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const crumbs = dir.split('/').filter(Boolean)

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-1.5 px-2.5 py-2">
        <div className="flex-1 flex items-center gap-2 h-8 px-2.5 rounded-btn bg-inset">
          <Search size={12} className="text-content-tertiary shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            spellCheck={false}
            placeholder={t('ws_search_placeholder')}
            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[13px] text-content placeholder:text-content-tertiary"
          />
        </div>
        <button
          onClick={() => {
            setQuery('')
            loadDir(dir)
          }}
          title={t('ws_refresh')}
          className="w-7 h-7 flex items-center justify-center rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors"
        >
          <RotateCw size={13} />
        </button>
      </div>

      {!searching && (
        <div className="flex items-center flex-wrap gap-0.5 px-3 pb-2 text-[11px] text-content-tertiary">
          <button
            onClick={() => loadDir('')}
            title={root}
            className="inline-flex items-center gap-1 px-1 py-0.5 rounded hover:bg-surface-2 hover:text-content cursor-pointer min-w-0"
          >
            <Home size={11} className="shrink-0" />
            {/* At the root, show the absolute root path so the user knows which
                directory (project or ~/stella) the panel is anchored to. */}
            {crumbs.length === 0 && root && (
              <span className="truncate max-w-[240px]">{root}</span>
            )}
          </button>
          {crumbs.map((part, i) => (
            <React.Fragment key={i}>
              <ChevronRight size={10} className="opacity-50" />
              <button
                onClick={() => loadDir(crumbs.slice(0, i + 1).join('/'))}
                className="px-1 py-0.5 rounded hover:bg-surface-2 hover:text-content cursor-pointer"
              >
                {part}
              </button>
            </React.Fragment>
          ))}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto px-1.5 pb-3">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-2 py-8 text-content-tertiary text-[13px]">
            <AlertTriangle size={20} className="opacity-50" />
            <span>{error}</span>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-content-tertiary text-[13px]">
            <FolderOpen size={20} className="opacity-40" />
            <span>{searching ? t('ws_no_results') : t('ws_empty_dir')}</span>
          </div>
        ) : (
          <>
            {entries.map((entry) => {
              const Icon = iconFor(entry.kind)
              const active = !entry.is_dir && current?.path === entry.path
              return (
                <div
                  key={entry.path}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData(WORKSPACE_DRAG_TYPE, JSON.stringify(entry))
                  }}
                  onClick={() => (entry.is_dir ? loadDir(entry.path) : preview(entry))}
                  className={`flex items-center gap-2.5 px-2 py-[7px] rounded-lg cursor-pointer select-none transition-colors ${
                    active ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  }`}
                >
                  <Icon size={14} className={`shrink-0 ${colorFor(entry.kind)}`} />
                  <span className="flex-1 min-w-0 text-[13px] text-content truncate">{entry.name}</span>
                  <span className="shrink-0 text-[11px] text-content-tertiary max-w-[45%] truncate">
                    {searching ? entry.path : entry.is_dir ? '' : formatSize(entry.size)}
                  </span>
                  {!entry.is_dir && sessionId && (
                    <button
                      aria-label={`共享 ${entry.name}`}
                      title="共享文件"
                      onClick={(event) => { event.stopPropagation(); void openShare(entry) }}
                      className="p-1 rounded text-content-tertiary hover:text-content hover:bg-surface-3"
                    >
                      <Share2 size={13} />
                    </button>
                  )}
                </div>
              )
            })}
            {truncated && (
              <div className="px-2 py-3 text-center text-[11px] text-content-tertiary">
                {t('ws_truncated')}
              </div>
            )}
          </>
        )}
        {shareTarget && (
          <div className="mx-1 mt-3 rounded-lg border border-border p-3 space-y-2 text-xs text-content">
            <div className="font-medium truncate">共享 {shareTarget.name}</div>
            <label className="block space-y-1">
              <span>共享给会话</span>
              <select aria-label="共享给会话" value={recipient} onChange={(event) => setRecipient(event.target.value)}
                className="w-full rounded bg-inset p-1.5">
                {recipients.map((row) => <option key={row.session_id} value={row.session_id}>{row.title || row.session_id}</option>)}
              </select>
            </label>
            <label className="block space-y-1">
              <span>共享权限</span>
              <select aria-label="共享权限" value={shareAccess}
                onChange={(event) => setShareAccess(event.target.value as 'read' | 'write')}
                className="w-full rounded bg-inset p-1.5">
                <option value="read">只读</option><option value="write">可写</option>
              </select>
            </label>
            {recipients.length === 0 && <div className="text-content-tertiary">暂无其他会话</div>}
            <div className="flex gap-2">
              <button onClick={() => void confirmShare()} disabled={!recipient || shareBusy}
                className="rounded bg-accent px-2 py-1 text-white disabled:opacity-50">确认共享</button>
              <button onClick={() => setShareTarget(null)} className="rounded px-2 py-1 hover:bg-surface-2">取消</button>
            </div>
          </div>
        )}
        {shareError && <div role="alert" className="px-2 py-2 text-xs text-red-500">{shareError}</div>}
        {shares.length > 0 && (
          <div className="mx-1 mt-3 border-t border-border pt-2 space-y-1 text-xs text-content">
            <div className="px-1 font-medium">共享文件</div>
            {shares.map((share) => (
              <div key={share.id} className="flex items-center gap-2 rounded px-1 py-1 hover:bg-surface-2">
                <Share2 size={12} className="shrink-0 text-content-tertiary" />
                <button onClick={() => void preview(share.path)}
                  className="min-w-0 flex-1 truncate text-left hover:underline"
                  aria-label={`打开共享文件 ${share.name}`}>{share.name}</button>
                <span className="text-content-tertiary">
                  {share.owner_session === sessionId
                    ? `已共享给 ${share.recipient_session}${share.active ? '' : '（已撤销）'}`
                    : `来自 ${share.owner_session}`}
                </span>
                {share.owner_session === sessionId && share.active && (
                  <button aria-label="撤销共享" onClick={() => void revokeShare(share.id)} disabled={shareBusy}
                    className="rounded px-1 py-0.5 text-content-tertiary hover:text-content hover:bg-surface-3">撤销</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default FileTree
