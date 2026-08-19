import { create } from 'zustand'
import apiClient from '../api/client'
import type { SessionSettingsState } from '../types'

/**
 * Per-session model + permission overrides, mirroring the web console's
 * `_sessCfg`. Both fall back to the global config when unset; the composer chips
 * read `cfg` to render the effective model/permission and their menus.
 */
export type ComposerMenu = 'workspace' | 'permission' | 'model' | null

interface SessionSettingsStore {
  /** Settings for the currently loaded session, or null before the first fetch. */
  cfg: SessionSettingsState | null
  /** Which session `cfg` describes, so a stale response for a switched-away
   *  session is ignored. */
  sessionId: string | null
  loading: boolean
  /** Which composer menu is open. Shared so the three chips exclude each other,
   *  and so a permission-denied hint can open the permission menu. */
  openMenu: ComposerMenu

  /** Fetch (and cache) settings for a session. Safe to call repeatedly. */
  refresh: (sessionId: string) => Promise<void>
  /** Apply a model / permission change, then repaint from the server echo. */
  apply: (
    sessionId: string,
    body: { provider?: string | null; model?: string | null; permission?: string | null }
  ) => Promise<boolean>
  /** Drop cached settings (e.g. on a brand-new chat) so chips fall back to global. */
  reset: () => void
  setOpenMenu: (menu: ComposerMenu) => void
}

export const useSessionSettingsStore = create<SessionSettingsStore>((set, get) => ({
  cfg: null,
  sessionId: null,
  loading: false,
  openMenu: null,

  setOpenMenu: (menu) => set({ openMenu: menu }),

  refresh: async (sessionId) => {
    if (!sessionId) return
    set({ loading: true })
    try {
      const data = await apiClient.getSessionSettings(sessionId)
      if (data.status !== 'success') {
        set({ loading: false })
        return
      }
      // Ignore a response that arrived after the user switched sessions.
      set({ cfg: { model: data.model, permission: data.permission }, sessionId, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  apply: async (sessionId, body) => {
    try {
      const data = await apiClient.updateSessionSettings(sessionId, body)
      if (data.status !== 'success' || !data.model || !data.permission) return false
      set({ cfg: { model: data.model, permission: data.permission }, sessionId })
      return true
    } catch {
      return false
    }
  },

  reset: () => set({ cfg: null, sessionId: null, openMenu: null }),
}))

/** True when `cfg` is loaded and belongs to the given session. */
export function cfgFor(sessionId: string): SessionSettingsState | null {
  const { cfg, sessionId: loaded } = useSessionSettingsStore.getState()
  return cfg && loaded === sessionId ? cfg : null
}
