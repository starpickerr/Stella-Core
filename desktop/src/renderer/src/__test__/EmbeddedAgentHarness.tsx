import React from 'react'
import { createRoot } from 'react-dom/client'
import EmbeddedAgent from '../components/EmbeddedAgent'

const mount = document.createElement('div')
mount.id = 'embedded-test-root'
document.body.appendChild(mount)
const root = createRoot(mount)

declare global {
  interface Window {
    mountEmbedded: (context: 'calendar' | 'todos', presetRequest?: { id: string; text: string } | null) => void
    detachEmbedded: () => void
  }
}

window.mountEmbedded = (context, presetRequest) => root.render(
  <EmbeddedAgent key={context} context={context} presetRequest={presetRequest || undefined} />)
window.detachEmbedded = () => root.render(null)
