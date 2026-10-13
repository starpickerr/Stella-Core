import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  History,
  Pin,
  ChevronDown,
  Folder,
  FolderOpen,
  GripVertical,
} from 'lucide-react'
import { t } from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { usePlatform } from '../hooks/usePlatform'
import type { ProjectRef, SessionItem } from '../types'
import apiClient from '../api/client'
import Tooltip from '../components/Tooltip'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'

const COLLAPSED_KEY = 'cow_collapsed_projects'

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY)
    const arr = raw ? (JSON.parse(raw) as string[]) : []
    return new Set(Array.isArray(arr) ? arr : [])
  } catch {
    return new Set()
  }
}

function saveCollapsed(set: Set<string>) {
  localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set]))
}

type SpaceGroup = {
  key: string
  label: string
  conversationCount: number
  isProject: boolean
  items: SessionItem[]
}

function buildGroups(
  sessions: SessionItem[],
  projects: ProjectRef[],
  projectOrder: string[]
): SpaceGroup[] {
  const buckets = new Map<string, SpaceGroup>()
  for (const project of projects) {
    buckets.set(project.path, {
      key: project.path,
      label: project.name,
      conversationCount: project.conversation_count || 0,
      isProject: true,
      items: [],
    })
  }
  for (const session of sessions) {
    const project = session.project
    if (!project) continue
    if (!buckets.has(project.path)) {
      buckets.set(project.path, {
        key: project.path,
        label: project.name,
        conversationCount: 0,
        isProject: true,
        items: [],
      })
    }
    if (!session.pinned) buckets.get(project.path)!.items.push(session)
  }
  const groups = [...buckets.values()]
  const rank = new Map(projectOrder.map((path, index) => [path, index]))
  const known = new Map(projects.map((project, index) => [project.path, index]))
  groups.sort((a, b) => {
    const rankDifference = (rank.get(a.key) ?? Number.MAX_SAFE_INTEGER) -
      (rank.get(b.key) ?? Number.MAX_SAFE_INTEGER)
    return rankDifference ||
      (known.get(a.key) ?? Number.MAX_SAFE_INTEGER) -
      (known.get(b.key) ?? Number.MAX_SAFE_INTEGER)
  })
  return groups
}

const SessionList: React.FC = () => {
  const {
    sessions,
    activeId,
    loading,
    loadSessions,
    loadMore,
    hasMore,
    setActive,
    newSession,
    addOptimistic,
    rename,
    remove,
    togglePin,
    projects,
    projectOrder,
    reorderSpaces,
  } = useSessionStore()
  const toggleSessions = useUIStore((s) => s.toggleSessions)
  const setSessionsCollapsed = useUIStore((s) => s.setSessionsCollapsed)
  const navCollapsed = useUIStore((s) => s.navCollapsed)
  const reloadRoot = useWorkspaceStore((s) => s.reloadRoot)
  const openPanel = useWorkspaceStore((s) => s.openPanel)
  const { isMac } = usePlatform()
  const trafficOffset = isMac && navCollapsed ? 'ml-2' : ''
  const trafficDrop = isMac ? 'mt-1' : ''
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed)
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [dropKey, setDropKey] = useState<string | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ path: string; name: string } | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<{ path: string; name: string } | null>(null)
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionItem | null>(null)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [projectError, setProjectError] = useState('')
  const [sidebarError, setSidebarError] = useState('')
  const [busy, setBusy] = useState(false)
  const activeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadSessions(1)
  }, [loadSessions])

  const groups = useMemo(
    () => buildGroups(sessions, projects, projectOrder),
    [sessions, projects, projectOrder]
  )
  const pinnedSessions = sessions.filter((session) => session.pinned)
  const recentSessions = sessions.filter((session) => !session.pinned && !session.project?.path)
  const displayGroups: SpaceGroup[] = [
    ...(pinnedSessions.length
      ? [{
          key: '__pinned__',
          label: t('session_pinned_group'),
          conversationCount: pinnedSessions.length,
          isProject: false,
          items: pinnedSessions,
        }]
      : []),
    ...groups,
    {
      key: '__recent__',
      label: '',
      conversationCount: recentSessions.length,
      isProject: false,
      items: recentSessions,
    },
  ]

  const startEdit = (s: SessionItem) => {
    setEditingId(s.session_id)
    setEditValue(s.title || '')
  }

  const commitEdit = async () => {
    if (editingId && editValue.trim()) {
      await rename(editingId, editValue.trim())
    }
    setEditingId(null)
  }

  const toggleCollapse = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      saveCollapsed(next)
      return next
    })
  }

  const expandSpace = (key: string) => {
    setCollapsed((prev) => {
      if (!prev.has(key)) return prev
      const next = new Set(prev)
      next.delete(key)
      saveCollapsed(next)
      return next
    })
  }

  // Start a fresh conversation inside a project from its sidebar entry.
  // Auto-expands the sidebar + group so the new session is immediately visible.
  const newChatInSpace = async (spaceKey: string, displayName?: string) => {
    setSidebarError('')
    const id = newSession()
    setSessionsCollapsed(false)
    const group = groups.find((g) => g.key === spaceKey)
    // Show the fresh (not-yet-persisted) session under its space right away.
    addOptimistic(id, { path: spaceKey, name: displayName || group?.label || spaceKey })
    expandSpace(spaceKey)
    try {
      const result = await apiClient.selectProject(id, spaceKey)
      if (result.status !== 'success') throw new Error(result.message || t('ws_sel_select_failed'))
      openPanel('files')
      reloadRoot()
      return id
    } catch {
      addOptimistic(id, null)
      setSidebarError(t('ws_sel_select_failed'))
      return null
    }
  }

  // Keep the active project's conversations visible when switching chats.
  useEffect(() => {
    const active = sessions.find((s) => s.session_id === activeId)
    if (active?.project?.path) expandSpace(active.project.path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, sessions])

  // Scroll the active session into view after its group is expanded/rendered.
  // Depends on `sessions` too, so switching/creating a project (which inserts a
  // new group, often at the bottom) re-scrolls to the active session even
  // though activeId itself did not change. `center` makes a bottom group clearly
  // visible rather than just peeking above the fold.
  useEffect(() => {
    const el = activeRef.current
    if (!el) return
    const id = requestAnimationFrame(() => el.scrollIntoView({ block: 'center' }))
    return () => cancelAnimationFrame(id)
  }, [activeId, collapsed, sessions])

  const commitRename = async () => {
    if (!renameTarget) return
    const name = renameValue.trim()
    if (!name) return
    setBusy(true)
    try {
      const res = await apiClient.renameProject(renameTarget.path, name)
      if (res.status === 'success') {
        setRenameTarget(null)
        await loadSessions(1)
        useSessionStore.getState().bumpProjects()
      }
    } finally {
      setBusy(false)
    }
  }

  const commitDelete = async () => {
    if (!deleteTarget) return
    setBusy(true)
    try {
      const res = await apiClient.deleteProject(deleteTarget.path)
      if (res.status === 'success') {
        setDeleteTarget(null)
        await loadSessions(1)
        useSessionStore.getState().bumpProjects()
      }
    } finally {
      setBusy(false)
    }
  }

  const createProject = async () => {
    const name = newProjectName.trim()
    if (!name) return setProjectError(t('ws_sel_name_required'))
    if (name.includes('/') || name.includes('\\')) return setProjectError(t('ws_sel_name_no_slash'))
    setBusy(true)
    setProjectError('')
    try {
      const result = await apiClient.createProject('', name)
      if (result.status !== 'success' || !result.path) {
        setProjectError(result.message || t('ws_sel_create_failed'))
        return
      }
      setNewProjectOpen(false)
      const active = sessions.find((session) => session.session_id === activeId)
      await loadSessions(1)
      if (active && !useSessionStore.getState().sessions.some((session) => session.session_id === activeId)) {
        addOptimistic(activeId, active.project)
      }
      useSessionStore.getState().bumpProjects()
      expandSpace(result.path)
    } catch {
      setProjectError(t('ws_sel_create_failed'))
    } finally {
      setBusy(false)
    }
  }

  const openProject = async () => {
    const path = await window.electronAPI?.selectDirectory?.()
    if (!path) return
    const name = path.split(/[\\/]/).filter(Boolean).pop() || path
    const id = await newChatInSpace(path, name)
    if (!id) return
    await loadSessions(1)
    addOptimistic(id, { path, name })
    useSessionStore.getState().bumpProjects()
  }

  return (
    <div className="w-[240px] flex-shrink-0 flex flex-col h-full bg-surface border-r border-default">
      <div className="flex items-center justify-between px-2 h-[44px] flex-shrink-0 titlebar-drag border-b border-default">
        <Tooltip label={t('session_history')}>
          <button
            onClick={toggleSessions}
            className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors ${trafficDrop} ${trafficOffset}`}
          >
            <History size={16} />
          </button>
        </Tooltip>
        <button
          onClick={() => {
            const id = newSession()
            addOptimistic(id, null)
          }}
          className={`titlebar-no-drag inline-flex items-center gap-1.5 px-2.5 h-7 rounded-btn text-[12px] font-medium text-accent hover:bg-accent-soft cursor-pointer transition-colors ${trafficDrop}`}
        >
          <Plus size={15} />
          {t('session_new')}
        </button>
      </div>

      <div
        className="flex-1 overflow-y-auto px-2 pb-2 pt-1.5"
        onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 80 && hasMore && !loading) loadMore()
        }}
      >
        {sidebarError && <p role="alert" className="px-2 py-2 text-xs text-danger">{sidebarError}</p>}
        {displayGroups.map((group, index) => {
          const isCollapsed = group.isProject && collapsed.has(group.key)
          return (
            <React.Fragment key={group.key}>
              {index === (pinnedSessions.length ? 1 : 0) && (
                <div className="flex items-center justify-between px-2 pt-3 pb-1.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('project_section')}
                  </span>
                  <span className="flex items-center gap-0.5">
                    <IconBtn onClick={() => void openProject()} title={t('ws_sel_open')}>
                      <FolderOpen size={14} />
                    </IconBtn>
                    <IconBtn onClick={() => { setProjectError(''); setNewProjectName(''); setNewProjectOpen(true) }} title={t('ws_sel_new')}>
                      <Plus size={15} />
                    </IconBtn>
                  </span>
                </div>
              )}
              {index === (pinnedSessions.length ? 1 : 0) && groups.length === 0 && (
                <p className="px-2 py-2 text-xs text-content-tertiary">{t('project_none')}</p>
              )}
              {group.key === '__recent__' && (
                <div className="px-2 pt-4 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('session_recent')}
                </div>
              )}
              <div className="mb-1.5">
              {group.isProject ? (
                <div
                  draggable
                  onDragStart={(e) => {
                    setDragKey(group.key)
                    e.dataTransfer.effectAllowed = 'move'
                    e.dataTransfer.setData('text/plain', group.key)
                  }}
                  onDragEnd={() => {
                    setDragKey(null)
                    setDropKey(null)
                  }}
                  onDragOver={(e) => {
                    if (!dragKey || dragKey === group.key) return
                    e.preventDefault()
                    setDropKey(group.key)
                  }}
                  onDragLeave={() => {
                    if (dropKey === group.key) setDropKey(null)
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    if (dragKey && dragKey !== group.key)
                      reorderSpaces(dragKey, group.key, groups.map((g) => g.key))
                    setDragKey(null)
                    setDropKey(null)
                  }}
                  className={`group/header relative flex items-center gap-1 px-1.5 h-7 rounded-btn cursor-grab active:cursor-grabbing select-none transition-colors ${
                    dragKey === group.key ? 'opacity-40' : ''
                  } ${
                    dropKey === group.key
                      ? 'bg-accent-soft before:absolute before:-top-[3px] before:left-1 before:right-1 before:h-[2px] before:rounded-full before:bg-accent'
                      : 'hover:bg-surface-2'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => toggleCollapse(group.key)}
                    aria-expanded={!isCollapsed}
                    title={group.key}
                    className="flex items-center gap-1 min-w-0 flex-1 h-full text-left focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    <span className="relative shrink-0 w-3 h-3">
                      <ChevronDown
                        size={12}
                        className={`absolute inset-0 text-content-tertiary transition-transform group-hover/header:opacity-0 ${isCollapsed ? '-rotate-90' : ''}`}
                      />
                      <GripVertical
                        size={12}
                        className="absolute inset-0 text-content-tertiary opacity-0 group-hover/header:opacity-100"
                      />
                    </span>
                    <Folder size={14} className="shrink-0 text-content-tertiary" />
                    <span className="flex-1 min-w-0 truncate text-[12px] font-medium text-content-secondary">{group.label}</span>
                    <span className="text-[11px] text-content-disabled tabular-nums group-hover/header:hidden group-focus-within/header:hidden">
                      {Math.max(group.conversationCount, group.items.length)}
                    </span>
                  </button>
                  <span className="hidden group-hover/header:flex group-focus-within/header:flex items-center gap-0.5 shrink-0">
                    <IconBtn
                      onClick={(e) => {
                        e.stopPropagation()
                        newChatInSpace(group.key)
                      }}
                      title={t('project_new_chat')}
                    >
                      <Plus size={12} />
                    </IconBtn>
                    <IconBtn
                      onClick={(e) => {
                        e.stopPropagation()
                        setRenameTarget({ path: group.key, name: group.label })
                        setRenameValue(group.label)
                      }}
                      title={t('project_rename')}
                    >
                      <Pencil size={12} />
                    </IconBtn>
                    <IconBtn
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteTarget({ path: group.key, name: group.label })
                      }}
                      title={t('project_delete')}
                      danger
                    >
                      <Trash2 size={12} />
                    </IconBtn>
                  </span>
                </div>
              ) : group.label ? (
                <div className="px-2 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-content-disabled">
                  {group.label}
                </div>
              ) : null}

              {!isCollapsed && group.isProject && group.conversationCount === 0 && group.items.length === 0 && (
                <p className="pl-[27px] pr-2 py-1 text-[11px] text-content-tertiary">{t('project_no_conversations')}</p>
              )}

              {!isCollapsed &&
                group.items.map((s) => {
                  const isActive = s.session_id === activeId
                  const isEditing = editingId === s.session_id
                  return (
                    <div
                      key={s.session_id}
                      ref={isActive ? activeRef : undefined}
                      onClick={() => !isEditing && setActive(s.session_id)}
                      className={`group relative flex items-center gap-1.5 pr-2 h-9 rounded-btn cursor-pointer transition-colors ${
                        group.isProject ? 'pl-[27px]' : 'pl-2'
                      } ${isActive ? 'bg-accent-soft' : 'hover:bg-surface-2'}`}
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitEdit()
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="flex-1 min-w-0 bg-inset border border-strong rounded px-1.5 py-0.5 text-[13px] text-content focus:outline-none focus:border-accent"
                        />
                      ) : (
                        <span
                          className={`flex-1 min-w-0 truncate text-[13px] pr-5 group-hover:pr-0 ${
                            isActive ? 'text-accent font-medium' : 'text-content-secondary'
                          }`}
                        >
                          {s.title || s.session_id}
                        </span>
                      )}

                      {isEditing ? (
                        <div className="flex items-center gap-0.5">
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              commitEdit()
                            }}
                          >
                            <Check size={13} />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              setEditingId(null)
                            }}
                          >
                            <X size={13} />
                          </IconBtn>
                        </div>
                      ) : (
                        <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              togglePin(s.session_id)
                            }}
                            title={t(s.pinned ? 'unpin_session' : 'pin_session')}
                          >
                            <Pin
                              size={13}
                              className={s.pinned ? 'text-accent fill-accent' : ''}
                            />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              startEdit(s)
                            }}
                            title={t('session_rename')}
                          >
                            <Pencil size={13} />
                          </IconBtn>
                          <IconBtn
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteSessionTarget(s)
                            }}
                            title={t('session_delete')}
                            danger
                          >
                            <Trash2 size={13} />
                          </IconBtn>
                        </div>
                      )}
                      {s.pinned && !isEditing && (
                        <Pin
                          size={11}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-accent fill-accent pointer-events-none group-hover:hidden"
                        />
                      )}
                    </div>
                  )
                })}
              {!isCollapsed && group.isProject && hasMore && group.conversationCount >
                group.items.length + pinnedSessions.filter((s) => s.project?.path === group.key).length && (
                <button type="button" onClick={() => void loadMore()} disabled={loading}
                  className="ml-[27px] px-1 py-1 text-[11px] text-accent hover:underline disabled:opacity-50">
                  {t('project_load_more')}
                </button>
              )}
              {group.key === '__recent__' && recentSessions.length === 0 && !loading && !hasMore && (
                <p className="px-2 py-2 text-xs text-content-tertiary">{t('session_no_recent')}</p>
              )}
              </div>
            </React.Fragment>
          )
        })}

        {loading && (
          <div className="px-2 py-2 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-7 w-full" />
            ))}
          </div>
        )}
      </div>

      <Modal
        open={newProjectOpen}
        title={t('ws_sel_new_title')}
        onClose={() => setNewProjectOpen(false)}
        footer={
          <>
            <Btn onClick={() => setNewProjectOpen(false)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="primary" onClick={createProject} disabled={busy}>
              {t('ws_sel_create')}
            </Btn>
          </>
        }
      >
        <p className="text-xs text-content-tertiary mb-2">{t('ws_sel_new_subtitle')}</p>
        <TextInput
          autoFocus
          value={newProjectName}
          onChange={(e) => { setNewProjectName(e.target.value); setProjectError('') }}
          onKeyDown={(e) => { if (e.key === 'Enter') void createProject() }}
          placeholder={t('ws_sel_new_placeholder')}
          maxLength={100}
        />
        {projectError && <p role="alert" className="mt-2 text-xs text-danger">{projectError}</p>}
      </Modal>

      <Modal
        open={!!renameTarget}
        title={t('project_rename_title')}
        onClose={() => setRenameTarget(null)}
        footer={
          <>
            <Btn onClick={() => setRenameTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="primary" onClick={commitRename} disabled={busy || !renameValue.trim()}>
              {t('config_save')}
            </Btn>
          </>
        }
      >
        <TextInput
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
          }}
          maxLength={100}
        />
      </Modal>

      <Modal
        open={!!deleteTarget}
        title={t('project_delete_title')}
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Btn onClick={() => setDeleteTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="danger" onClick={commitDelete} disabled={busy}>
              {t('project_delete')}
            </Btn>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('project_delete_confirm').replace('{name}', deleteTarget?.name || '')}
        </p>
      </Modal>

      <Modal
        open={!!deleteSessionTarget}
        title={t('session_delete_title')}
        onClose={() => setDeleteSessionTarget(null)}
        footer={
          <>
            <Btn onClick={() => setDeleteSessionTarget(null)}>{t('ws_sel_cancel')}</Btn>
            <Btn
              variant="danger"
              onClick={async () => {
                if (deleteSessionTarget) await remove(deleteSessionTarget.session_id)
                setDeleteSessionTarget(null)
              }}
            >
              {t('session_delete')}
            </Btn>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('session_delete_confirm').replace(
            '{name}',
            deleteSessionTarget?.title || deleteSessionTarget?.session_id || ''
          )}
        </p>
      </Modal>
    </div>
  )
}

const IconBtn: React.FC<{
  onClick: (e: React.MouseEvent) => void
  title?: string
  danger?: boolean
  children: React.ReactNode
}> = ({ onClick, title, danger, children }) => {
  const btn = (
    <button
      onClick={onClick}
      aria-label={title}
      className={`inline-flex items-center justify-center w-6 h-6 rounded cursor-pointer transition-colors text-content-tertiary ${
        danger ? 'hover:text-danger hover:bg-danger-soft' : 'hover:text-content hover:bg-surface'
      }`}
    >
      {children}
    </button>
  )
  return title ? <Tooltip label={title}>{btn}</Tooltip> : btn
}

export default SessionList
