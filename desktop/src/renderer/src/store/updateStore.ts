import { create } from 'zustand'
import type { UpdateStatus } from '../types'
import { getLang } from '../i18n'

interface UpdateState {
  status: UpdateStatus | null
  /** Latest available version, kept across download progress updates. */
  version: string | null
  /** Download progress 0-100 while state === 'downloading'. */
  percent: number
  /** User dismissed the badge for this version (don't nag again until next). */
  dismissedVersion: string | null
  /** Whether the update panel is currently shown. Lifted here so the "check
   *  for update" menu item can re-open it on demand. */
  panelOpen: boolean

  setStatus: (s: UpdateStatus) => void
  /** Dismiss the floating badge/panel for the current version (footer dot goes
   *  away), but keep the update itself known so the menu can still surface it. */
  dismiss: () => void
  openPanel: () => void
  closePanel: () => void
  /** User explicitly clicked "check for update": ask main to re-check, and if
   *  an update is already known, re-open the panel immediately (undismiss). */
  recheck: () => void

  // Actions proxied to the main process via the preload bridge.
  download: () => void
  install: () => void
}

export const useUpdateStore = create<UpdateState>((set, get) => ({
  status: null,
  version: null,
  percent: 0,
  dismissedVersion: null,
  panelOpen: false,

  setStatus: (s) =>
    set(() => {
      // A newly detected version auto-opens the panel.
      if (s.state === 'available') return { status: s, version: s.version, percent: 0, panelOpen: true }
      if (s.state === 'downloading') return { status: s, percent: s.percent }
      if (s.state === 'downloaded') return { status: s, version: s.version, percent: 100 }
      return { status: s }
    }),

  dismiss: () => set((st) => ({ dismissedVersion: st.version, panelOpen: false })),
  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),

  recheck: () => {
    const st = get()
    // If we already know about an available/downloaded update, just re-open the
    // panel (clearing the dismiss for this version) instead of waiting on a
    // network round-trip — the user asked to see it.
    if (hasAvailableUpdate(st)) {
      set({ dismissedVersion: null, panelOpen: true })
    }
    // Always kick a fresh check too (picks up newer versions / recovers errors).
    // Pass the UI language so downloads route to the China CDN / R2 accordingly.
    window.electronAPI?.checkForUpdate?.(getLang())
  },

  download: () => window.electronAPI?.downloadUpdate?.(getLang()),
  install: () => window.electronAPI?.installUpdate?.(),
}))

// Subscribe to main-process update events. Returns an unsubscribe fn.
export function initUpdateListener(): (() => void) | undefined {
  return window.electronAPI?.onUpdateStatus?.((status) => {
    useUpdateStore.getState().setStatus(status as UpdateStatus)
  })
}

// Whether an update exists at all (available/downloading/downloaded),
// regardless of dismiss. Drives the "check for update" menu item's dot, which
// should persist as long as an update is actually available.
export function hasAvailableUpdate(state: UpdateState): boolean {
  const s = state.status
  if (!s) return false
  return s.state === 'available' || s.state === 'downloading' || s.state === 'downloaded'
}

// Whether a new version should be surfaced in the floating footer badge:
// available and not dismissed for that version. Dismissing hides only this,
// not the menu dot (hasAvailableUpdate).
export function hasPendingUpdate(state: UpdateState): boolean {
  return hasAvailableUpdate(state) && state.dismissedVersion !== state.version
}
