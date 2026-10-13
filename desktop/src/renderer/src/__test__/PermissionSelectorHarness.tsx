import React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import PermissionSelector from '../components/PermissionSelector'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import { useSessionStore } from '../store/sessionStore'

let root: Root | undefined

export async function mountPermissionSelector(sessionId: string) {
  useSessionStore.getState().setActive(sessionId)
  if (!root) {
    const host = document.createElement('div')
    host.id = 'permission-test-root'
    host.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999'
    document.body.append(host)
    root = createRoot(host)
  }
  root.render(<PermissionSelector sessionId={sessionId} />)
  await useSessionSettingsStore.getState().refresh(sessionId)
}
