import { create } from 'zustand'
import type { UpdateStatus } from '../types'

interface UpdateState {
  status: UpdateStatus | null
  /** Latest available version, kept across status updates. */
  version: string | null
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

  // Opens the installer (or the GitHub Releases page) in the system browser.
  download: () => void
}

function statusUrl(status: UpdateStatus | null): string | undefined {
  if (!status) return undefined
  if (status.state === 'available') return status.assetUrl || status.pageUrl
  if (status.state === 'error') return status.pageUrl
  return undefined
}

export const useUpdateStore = create<UpdateState>((set, get) => ({
  status: null,
  version: null,
  dismissedVersion: null,
  panelOpen: false,

  setStatus: (s) =>
    set((st) => {
      if (s.state === 'available') {
        // Auto-open the panel once per version, but don't nag: an automatic
        // check (startup / 4h poll) that finds a version the user already
        // dismissed leaves the panel closed and only keeps the dot lit. A
        // different (newer) version, or an explicit "check for update" click
        // (userInitiated), re-opens it. recheck() clears dismissedVersion, so a
        // manual check always satisfies the "not dismissed" condition too.
        const alreadyDismissed = st.dismissedVersion === s.version
        const shouldOpen = s.userInitiated === true || !alreadyDismissed
        return {
          status: s,
          version: s.version,
          panelOpen: shouldOpen,
        }
      }
      if (s.state === 'error') {
        return { status: s, panelOpen: s.userInitiated === true || st.panelOpen }
      }
      return { status: s }
    }),

  dismiss: () => set((st) => ({ dismissedVersion: st.version, panelOpen: false })),
  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),

  recheck: () => {
    // Clear any dismiss so a known update surfaces again. Only re-open the panel
    // when an update actually exists — if we're already up to date, opening the
    // panel would just flash it (the banner renders nothing for not-available)
    // and the "up to date" feedback belongs in the menu, not a panel. The menu
    // (NavRail) decides whether to close itself + show the panel based on this.
    const known = hasAvailableUpdate(get())
    set({ dismissedVersion: null, panelOpen: known })
    window.electronAPI?.checkForUpdate?.()
  },

  download: () => {
    window.electronAPI?.downloadUpdate?.(statusUrl(get().status))
  },
}))

// Subscribe to main-process update events. Returns an unsubscribe fn.
export function initUpdateListener(): (() => void) | undefined {
  return window.electronAPI?.onUpdateStatus?.((status) => {
    useUpdateStore.getState().setStatus(status as UpdateStatus)
  })
}

// Whether an update exists at all, regardless of dismiss. Drives the "check
// for update" menu item's dot, which should persist as long as an update is
// actually available.
export function hasAvailableUpdate(state: UpdateState): boolean {
  return state.status?.state === 'available'
}

// Whether a new version should be surfaced in the floating footer badge:
// available and not dismissed for that version. Dismissing hides only this,
// not the menu dot (hasAvailableUpdate).
export function hasPendingUpdate(state: UpdateState): boolean {
  return hasAvailableUpdate(state) && state.dismissedVersion !== state.version
}
