import { create } from 'zustand'
import apiClient from '../api/client'
import type { Artifact, WorkspaceEntry } from '../types'

const WIDTH_KEY = 'cow_workspace_width'
export const WS_MIN_WIDTH = 300
export const WS_DEFAULT_WIDTH = 440

function readWidth(): number {
  const raw = parseInt(localStorage.getItem(WIDTH_KEY) || '', 10)
  return Number.isFinite(raw) && raw >= WS_MIN_WIDTH ? raw : WS_DEFAULT_WIDTH
}

export type WorkspaceTab = 'preview' | 'files'

interface WorkspaceState {
  open: boolean
  tab: WorkspaceTab
  width: number
  /** File currently shown in the preview tab. */
  current: WorkspaceEntry | null
  previewError: string | null
  /**
   * Set once the user closes the panel by hand. While true we stop
   * auto-opening artifacts, so the panel never fights the user.
   */
  autoOpenSuppressed: boolean
  /** Artifacts produced by the turn that is currently streaming. */
  turnArtifacts: Artifact[]
  /** Directory the files tab should jump to, with a counter so repeated
   *  requests for the same folder still trigger a reload. */
  browseDir: string | null
  browseSeq: number

  openPanel: (tab?: WorkspaceTab) => void
  closePanel: (byUser?: boolean) => void
  togglePanel: () => void
  setTab: (tab: WorkspaceTab) => void
  setWidth: (w: number) => void

  preview: (target: WorkspaceEntry | Artifact | string) => Promise<void>
  addTurnArtifact: (a: Artifact) => void
  resetTurnArtifacts: () => void
  maybeAutoOpen: () => void
}

/** Artifact and WorkspaceEntry differ only in naming; normalize to an entry. */
function toEntry(a: Artifact): WorkspaceEntry {
  return {
    name: a.file_name,
    path: a.rel_path,
    is_dir: false,
    kind: a.kind,
    previewable: a.previewable,
    size: a.size,
    mtime: 0,
    abs_path: a.abs_path,
    raw_url: a.raw_url,
    preview_url: a.preview_url,
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  open: false,
  tab: 'preview',
  width: readWidth(),
  current: null,
  previewError: null,
  autoOpenSuppressed: false,
  turnArtifacts: [],
  browseDir: null,
  browseSeq: 0,

  openPanel: (tab) => set((s) => ({ open: true, tab: tab ?? s.tab })),

  closePanel: (byUser) =>
    set((s) => ({ open: false, autoOpenSuppressed: byUser ? true : s.autoOpenSuppressed })),

  togglePanel: () => {
    const s = get()
    if (s.open) {
      s.closePanel(true)
      return
    }
    set({ open: true, autoOpenSuppressed: false, tab: s.current ? 'preview' : 'files' })
  },

  setTab: (tab) => set({ tab }),

  setWidth: (w) => {
    const next = Math.max(WS_MIN_WIDTH, Math.round(w))
    localStorage.setItem(WIDTH_KEY, String(next))
    set({ width: next })
  },

  preview: async (target) => {
    let entry: WorkspaceEntry | null = null
    if (typeof target === 'string') {
      try {
        entry = (await apiClient.workspaceResolve(target)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
    } else if ('rel_path' in target) {
      entry = toEntry(target)
    } else {
      entry = target
    }

    // Directories have nothing to render; browse into them instead.
    const browseIfDir = (e: WorkspaceEntry | null): boolean => {
      if (!e?.is_dir) return false
      set({
        open: true,
        tab: 'files',
        previewError: null,
        browseDir: e.path,
        browseSeq: get().browseSeq + 1,
      })
      return true
    }
    if (browseIfDir(entry)) return

    // Cards rebuilt from history carry only a path; fetch the signed URLs.
    if (entry && !entry.preview_url) {
      try {
        entry = (await apiClient.workspaceResolve(entry.abs_path || entry.path)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
      if (browseIfDir(entry)) return
    }

    set({ open: true, tab: 'preview', current: entry, previewError: null })
  },

  addTurnArtifact: (a) =>
    set((s) =>
      s.turnArtifacts.some((x) => x.abs_path === a.abs_path)
        ? s
        : { turnArtifacts: [...s.turnArtifacts, a] }
    ),

  resetTurnArtifacts: () => set({ turnArtifacts: [] }),

  /**
   * Auto-open policy: only when the turn produced exactly one previewable
   * artifact, and only while the user hasn't dismissed the panel by hand.
   */
  maybeAutoOpen: () => {
    const { turnArtifacts, autoOpenSuppressed, preview } = get()
    const previewable = turnArtifacts.filter((a) => a.previewable)
    set({ turnArtifacts: [] })
    if (autoOpenSuppressed || previewable.length !== 1) return
    preview(previewable[0])
  },
}))
