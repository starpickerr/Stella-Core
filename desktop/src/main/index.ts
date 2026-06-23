import { app, BrowserWindow, shell, ipcMain, dialog, nativeImage } from 'electron'
import path from 'path'
import fs from 'fs'
import http from 'http'
import { PythonBackend } from './python-manager'
import { buildAppMenu } from './menu'
import { createTray, destroyTray } from './tray'
import { initUpdater, checkForUpdates, startDownload, quitAndInstall } from './updater'

let mainWindow: BrowserWindow | null = null
let pythonBackend: PythonBackend | null = null
// True once the user explicitly quits (menu/tray), so close-to-tray is bypassed.
let isQuitting = false

const isDev = !app.isPackaged
const VITE_DEV_PORTS = [5173, 5174, 5175, 5176]

function probePort(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${port}`, (res) => {
      resolve(res.statusCode !== undefined)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(500, () => { req.destroy(); resolve(false) })
  })
}

async function findViteDevServer(): Promise<string | null> {
  for (const port of VITE_DEV_PORTS) {
    if (await probePort(port)) {
      return `http://localhost:${port}`
    }
  }
  return null
}

function getIconPath(ext: string = 'png'): string | undefined {
  const iconFile = `icon.${ext}`
  const iconPath = isDev
    ? path.resolve(__dirname, '../../resources', iconFile)
    : path.join(process.resourcesPath, iconFile)
  if (fs.existsSync(iconPath)) return iconPath
  return undefined
}

const isMac = process.platform === 'darwin'
const isWin = process.platform === 'win32'

// Persisted window bounds
const windowStateFile = () => path.join(app.getPath('userData'), 'window-state.json')

function loadWindowState(): { width: number; height: number; x?: number; y?: number } {
  try {
    const raw = fs.readFileSync(windowStateFile(), 'utf-8')
    const s = JSON.parse(raw)
    if (typeof s.width === 'number' && typeof s.height === 'number') return s
  } catch {
    /* first run or unreadable */
  }
  return { width: 1280, height: 800 }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMinimized() || mainWindow.isFullScreen()) return
  const b = mainWindow.getBounds()
  try {
    fs.writeFileSync(windowStateFile(), JSON.stringify(b))
  } catch {
    /* ignore */
  }
}

function createWindow() {
  const state = loadWindowState()

  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 900,
    minHeight: 600,
    // macOS: native traffic lights inset into our custom titlebar.
    // Windows: fully frameless; we render custom window controls in-app.
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 14, y: 16 } : undefined,
    frame: isMac ? undefined : false,
    backgroundColor: '#0e0e10',
    icon: getIconPath(),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  const persist = () => saveWindowState()
  mainWindow.on('resize', persist)
  mainWindow.on('move', persist)
  mainWindow.on('maximize', emitMaximizeState)
  mainWindow.on('unmaximize', emitMaximizeState)

  const rendererHtml = path.join(__dirname, '../renderer/index.html')

  if (isDev) {
    findViteDevServer().then((devUrl) => {
      if (devUrl) {
        console.log(`[Electron] Loading Vite dev server: ${devUrl}`)
        mainWindow?.loadURL(devUrl)
        mainWindow?.webContents.openDevTools()
      } else if (fs.existsSync(rendererHtml)) {
        console.log('[Electron] Vite dev server not found, loading built files')
        mainWindow?.loadFile(rendererHtml)
      } else {
        console.error('[Electron] No renderer available. Run "npm run build:renderer" first.')
      }
    })
  } else {
    mainWindow.loadFile(rendererHtml)
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Close-to-tray: hide the window instead of destroying it, so the tray's
  // "Show" can bring it back. Only a real Quit (menu/tray/Cmd+Q) destroys it.
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function getBackendPath(): string {
  if (isDev) {
    return path.resolve(__dirname, '../../..')
  }
  return path.join(process.resourcesPath, 'backend')
}

async function startBackend() {
  const backendPath = getBackendPath()
  pythonBackend = new PythonBackend(backendPath)

  pythonBackend.on('ready', (port: number) => {
    mainWindow?.webContents.send('backend-status', { status: 'ready', port })
  })

  pythonBackend.on('error', (error: string) => {
    mainWindow?.webContents.send('backend-status', { status: 'error', error })
  })

  pythonBackend.on('log', (line: string) => {
    mainWindow?.webContents.send('backend-log', line)
  })

  await pythonBackend.start()
}

function setupIPC() {
  ipcMain.handle('get-backend-port', () => {
    return pythonBackend?.getPort() ?? null
  })

  ipcMain.handle('get-backend-status', () => {
    return pythonBackend?.getStatus() ?? 'stopped'
  })

  ipcMain.handle('restart-backend', async () => {
    await pythonBackend?.restart()
    return true
  })

  ipcMain.handle('select-directory', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('select-file', async (_event, filters?: Electron.FileFilter[]) => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: filters || [{ name: 'All Files', extensions: ['*'] }],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  // Custom window controls (used by Windows frameless titlebar)
  ipcMain.handle('window-minimize', () => mainWindow?.minimize())
  ipcMain.handle('window-maximize', () => {
    if (!mainWindow) return false
    if (mainWindow.isMaximized()) mainWindow.unmaximize()
    else mainWindow.maximize()
    return mainWindow.isMaximized()
  })
  ipcMain.handle('window-close', () => mainWindow?.close())
  ipcMain.handle('window-is-maximized', () => mainWindow?.isMaximized() ?? false)

  // Auto-update controls (renderer-driven: check, then opt-in download/install)
  ipcMain.handle('update-check', () => checkForUpdates())
  ipcMain.handle('update-download', () => startDownload())
  ipcMain.handle('update-install', () => quitAndInstall())
}

function emitMaximizeState() {
  const max = mainWindow?.isMaximized() ?? false
  mainWindow?.webContents.send('window-maximize-changed', max)
}

// Single-instance lock: focus the existing window instead of opening a second app.
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

app.whenReady().then(async () => {
  // Set Dock icon on macOS (PNG is most reliable for nativeImage)
  if (process.platform === 'darwin') {
    const pngPath = getIconPath('png')
    if (pngPath) {
      const icon = nativeImage.createFromPath(pngPath)
      if (!icon.isEmpty()) {
        app.dock.setIcon(icon)
        console.log('[Electron] Dock icon set:', pngPath)
      } else {
        console.warn('[Electron] Dock icon loaded but empty:', pngPath)
      }
    } else {
      console.warn('[Electron] Dock icon not found in resources/')
    }
  }

  setupIPC()
  createWindow()
  buildAppMenu(() => mainWindow)
  createTray({
    getWindow: () => mainWindow,
    iconPath: getIconPath('png'),
    onQuit: () => {
      isQuitting = true
      app.quit()
    },
  })
  await startBackend()

  // Wire auto-update and do a first silent check a few seconds after launch so
  // it doesn't compete with backend startup for resources.
  initUpdater(() => mainWindow)
  setTimeout(() => checkForUpdates(), 5000)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    } else {
      mainWindow?.show()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  saveWindowState()
  destroyTray()
  pythonBackend?.stop()
})
