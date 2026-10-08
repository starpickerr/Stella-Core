import { create } from 'zustand'
import apiClient from '../api/client'

interface BriefingRunState {
  running: boolean
  pendingResultId: string | null
  error: string | null
  run: (operation: 'create' | 'update') => Promise<void>
  takeResult: () => string | null
  clearError: () => void
}

// The briefing route unmounts when the user opens another feature. Keep the
// in-flight request here so returning to the route cannot start a second run.
let activeRun: Promise<void> | null = null

export const useBriefingRunStore = create<BriefingRunState>((set, get) => ({
  running: false,
  pendingResultId: null,
  error: null,

  run: (operation) => {
    if (activeRun) return activeRun
    set({ running: true, pendingResultId: null, error: null })
    activeRun = apiClient.runBriefing(operation)
      .then((value) => set({ pendingResultId: value.briefing.id }))
      .catch((cause) => set({ error: cause instanceof Error ? cause.message : String(cause) }))
      .finally(() => {
        activeRun = null
        set({ running: false })
      })
    return activeRun
  },

  takeResult: () => {
    const id = get().pendingResultId
    if (id) set({ pendingResultId: null })
    return id
  },

  clearError: () => set({ error: null }),
}))
