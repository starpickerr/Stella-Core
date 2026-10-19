import { BrowserWindow, session } from 'electron'
import * as path from 'path'

export type PluginFrameOptions = {
  pluginId: string
  pageId: string
  channelNonce: string
  resourceUrl: string
  parent: BrowserWindow
  generation?: number
}

/** CSP for plugin frames: no Node, no remote code, only own origin + host bridge. */
export const PLUGIN_FRAME_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'"
].join('; ')

/**
 * Create a sandboxed child window for a plugin page.
 * Identity is bound by the host; the page cannot override pluginId/generation.
 */
export function openPluginFrame(options: PluginFrameOptions): BrowserWindow {
  const partition = `persist:plugin:${options.pluginId}`
  const ses = session.fromPartition(partition, { cache: true })
  ses.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...(details.responseHeaders || {}) }
    headers['Content-Security-Policy'] = [PLUGIN_FRAME_CSP]
    callback({ responseHeaders: headers })
  })
  const child = new BrowserWindow({
    parent: options.parent,
    width: 960,
    height: 720,
    show: false,
    webPreferences: {
      session: ses,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      // No preload with privileged APIs for plugin frames.
      preload: undefined,
      webSecurity: true
    }
  })

  // Host-bound identity: pages cannot forge pluginId / generation via query.
  const identity = {
    pluginId: options.pluginId,
    pageId: options.pageId,
    channelNonce: options.channelNonce,
    generation: options.generation ?? 0
  }
  child.webContents.on('ipc-message', (_event, channel) => {
    if (channel === 'plugin:claim-identity') {
      // Ignore — identity is host-only; never accept page claims.
    }
  })
  ;(child as BrowserWindow & { __stellaPluginIdentity?: typeof identity }).__stellaPluginIdentity =
    identity

  child.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  child.webContents.on('will-navigate', (event, url) => {
    const allowed =
      url.startsWith(options.resourceUrl) ||
      (url.startsWith('file:') && url.includes(`/plugin-packages/${options.pluginId}/`))
    if (!allowed) {
      event.preventDefault()
    }
  })
  child.webContents.on('will-redirect', (event, url) => {
    if (!url.startsWith(options.resourceUrl) && !url.startsWith('file:')) {
      event.preventDefault()
    }
  })

  void child.loadURL(options.resourceUrl)
  child.once('ready-to-show', () => child.show())
  child.on('closed', () => {
    delete (child as BrowserWindow & { __stellaPluginIdentity?: typeof identity })
      .__stellaPluginIdentity
  })
  return child
}

export function pluginStaticRoot(pluginId: string, digest: string): string {
  return path.join(process.resourcesPath || '.', 'plugin-packages', pluginId, digest, 'ui')
}

export function assertPluginFrameHardening(options: {
  nodeIntegration?: boolean
  sandbox?: boolean
  contextIsolation?: boolean
  preload?: string | undefined
  csp?: string
}): void {
  if (options.nodeIntegration) {
    throw new Error('plugin frame must not enable nodeIntegration')
  }
  if (options.sandbox === false) {
    throw new Error('plugin frame must enable sandbox')
  }
  if (options.contextIsolation === false) {
    throw new Error('plugin frame must enable contextIsolation')
  }
  if (options.preload) {
    throw new Error('plugin frame must not ship a privileged preload')
  }
  if (options.csp && !options.csp.includes("default-src 'self'")) {
    throw new Error('plugin frame CSP must lock default-src to self')
  }
}
