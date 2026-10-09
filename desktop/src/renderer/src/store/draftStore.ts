import type { Attachment } from '../types'

// Draft of the chat input (text + attachments). The input lives in local
// component state and the chat route unmounts ChatPage when the user navigates
// to another page, which would otherwise destroy what was typed. This module-
// scoped variable survives the unmount and is restored on the next mount.
// Lives for the renderer process only — no persistence across app restarts.
export const chatDraft: { text: string; attachments: Attachment[] } = {
  text: '',
  attachments: [],
}

const contextualDrafts: Record<string, { text: string; attachments: Attachment[] }> = {}

export function getChatDraft(key = 'main'): { text: string; attachments: Attachment[] } {
  if (key === 'main') return chatDraft
  return contextualDrafts[key] ||= { text: '', attachments: [] }
}
