import { BrowserWindow, session } from 'electron'
import * as path from 'path'

export type PluginFrameOptions = {
  pluginId: string
  pageId: string
  channelNonce: string
  resourceUrl: string
  parent: BrowserWindow
}

/**
 * Create a sandboxed child window for a plugin page.
 * Identity is bound by the host; the page cannot override pluginId/generation.
 */
export function openPluginFrame(options: PluginFrameOptions): BrowserWindow {
  const partition = `persist:plugin:${options.pluginId}`
  const ses = session.fromPartition(partition, { cache: true })
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

  child.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  child.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(options.resourceUrl) && !url.startsWith('file:')) {
      event.preventDefault()
    }
  })

  void child.loadURL(options.resourceUrl)
  child.once('ready-to-show', () => child.show())
  return child
}

export function pluginStaticRoot(pluginId: string, digest: string): string {
  return path.join(process.resourcesPath || '.', 'plugin-packages', pluginId, digest, 'ui')
}
