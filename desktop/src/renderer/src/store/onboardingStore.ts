import { create } from 'zustand'

// Dismissal lasts for this app session; an incomplete setup reappears on restart.

interface OnboardingState {
  open: boolean
  dismissedThisSession: boolean
  maybeOpen: (chatConfigured: boolean) => void
  openWizard: () => void
  finish: () => void
  close: () => void
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  open: false,
  dismissedThisSession: false,

  maybeOpen: (chatConfigured) =>
    set((s) => {
      if (chatConfigured || s.dismissedThisSession) return { open: false }
      return { open: true }
    }),

  openWizard: () => set({ open: true }),

  finish: () => set({ open: false, dismissedThisSession: true }),

  close: () => set({ open: false }),
}))
