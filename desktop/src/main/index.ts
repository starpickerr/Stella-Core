import { app, BrowserWindow, session, shell, ipcMain, dialog, nativeImage, Notification, systemPreferences } from 'electron'
import path from 'path'
import fs from 'fs'
import http from 'http'
import { PythonBackend, BackendError } from './python-manager'
import { buildAppMenu } from './menu'
import { createTray, destroyTray, getTray } from './tray'
import { initUpdater, checkForUpdates, openDownload } from './updater'
import { setupThemeIPC, loadAppConfig } from './themes'
import { setupHttpRelayIPC } from './http-relay'
import { setupAppIconIPC, applyCachedAppIcon, getRuntimeAppIcon } from './app-icon'

// Force the product name so the Dock/menu shows the app name even in dev mode,
// where the default Electron binary would otherwise report "Electron". The name
// can be overridden by the bundled app-config (appName); defaults to Stella.
app.setName(loadAppConfig()?.appName || 'Stella')
const desktopProfile = path.join(app.getPath('appData'), 'Stella')
fs.mkdirSync(desktopProfile, { recursive: true })
app.setPath('userData', desktopProfile)

// Windows shows notifications only when an AppUserModelID is set; without it
// they are silently dropped. Harmless on macOS/Linux.
if (process.platform === 'win32') {
  app.setAppUserModelId('com.starpickerr.stella')
}

let mainWindow: BrowserWindow | null = null
let pythonBackend: PythonBackend | null = null
let reminderPollTimer: ReturnType<typeof setInterval> | null = null
let reminderPollActive = false
// True once the user explicitly quits (menu/tray), so close-to-tray is bypassed.
let isQuitting = false
let replacingInstance = false

const isDev = !app.isPackaged
const VITE_DEV_PORT = 5173
const useHotRenderer = isDev && process.argv.includes('--hot-renderer')

// Launched by the OS at login (Windows passes --hidden; macOS reports it via
// getLoginItemSettings().wasOpenedAsHidden). Start minimized to the tray so
// autostart is unobtrusive.
function launchedHidden(): boolean {
  if (process.argv.includes('--hidden')) return true
  try {
    return app.getLoginItemSettings().wasOpenedAsHidden === true
  } catch {
    return false
  }
}

function probePort(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${port}`, (res) => {
      resolve(res.statusCode !== undefined)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(500, () => { req.destroy(); resolve(false) })
  })
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

  if (useHotRenderer) {
    probePort(VITE_DEV_PORT).then((ready) => {
      if (!ready) {
        console.error(`[Electron] Vite is not running on port ${VITE_DEV_PORT}`)
        return
      }
      const devUrl = `http://localhost:${VITE_DEV_PORT}`
      console.log(`[Electron] Loading Vite dev server: ${devUrl}`)
      mainWindow?.loadURL(devUrl)
      mainWindow?.webContents.openDevTools()
    })
  } else if (fs.existsSync(rendererHtml)) {
    console.log('[Electron] Loading built renderer files')
    mainWindow.loadFile(rendererHtml)
  } else {
    console.error('[Electron] No renderer available. Run "npm run build:renderer" first.')
  }

  // Surface renderer-side console output and load failures to the main-process
  // stdout. Without this, "stuck on initializing" hangs are invisible from the
  // terminal because all renderer logs stay in the (closed) devtools.
  mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    console.log(`[renderer:${level}] ${message} (${sourceId}:${line})`)
  })
  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error(`[renderer] did-fail-load ${code} ${desc} ${url}`)
  })

  // Replay the backend's current state to a renderer that has just loaded.
  // Backend events are fire-and-forget sends, but the renderer only subscribes
  // once React has mounted — so a failure detected in the first few hundred
  // milliseconds (a missing executable is detected almost immediately) was
  // announced to nobody, and the user was left staring at the generic
  // "initialization failed" with no reason attached.
  mainWindow.webContents.on('did-finish-load', () => {
    sendBackendState()
  })

  mainWindow.once('ready-to-show', () => {
    // Skip the initial paint when autostarted hidden: the window stays in the
    // tray/Dock until the user opens it, matching the "unobtrusive" intent.
    if (launchedHidden()) return
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Last-resort backstop for a stray file drop: Chromium would navigate the
  // renderer to the dropped file and the UI would be gone until restart.
  // Renderer reloads keep the same URL, so they are unaffected.
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (url.startsWith('file:') && url !== mainWindow?.webContents.getURL()) {
      console.warn(`[Electron] Blocked navigation to dropped file: ${url}`)
      e.preventDefault()
    }
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

/**
 * Push the backend's current state to the renderer. Used both for the initial
 * replay after a page load and as the shape every live status event follows.
 */
function sendBackendState() {
  if (!pythonBackend || !mainWindow || mainWindow.isDestroyed()) return
  const status = pythonBackend.getStatus()
  if (status === 'ready') {
    mainWindow.webContents.send('backend-status', { status: 'ready', port: pythonBackend.getPort() })
    return
  }
  if (status === 'error') {
    const err = pythonBackend.getLastError()
    mainWindow.webContents.send('backend-status', {
      status: 'error',
      error: err?.message,
      code: err?.code,
      path: err?.path,
    })
    return
  }
  mainWindow.webContents.send('backend-status', { status: 'starting', port: pythonBackend.getPort() })
}

async function startBackend() {
  const backendPath = getBackendPath()
  // isDev distinguishes a source checkout from an installed app. The backend
  // manager needs to know: an installed app must never fall back to looking
  // for a Python interpreter, and its writable data always lives in ~/.stella.
  pythonBackend = new PythonBackend(backendPath, !isDev)

  // Keep the private backend token in Electron's main process. This hook
  // covers fetch, EventSource and media loads from our window alike.
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const port = pythonBackend?.getPort()
    const ownedUrl = port && details.url.startsWith(`http://127.0.0.1:${port}/`)
    if (ownedUrl && details.webContentsId === mainWindow?.webContents.id) {
      callback({ requestHeaders: {
        ...details.requestHeaders,
        'X-Stella-Desktop-Token': pythonBackend!.getInternalToken(),
      } })
      return
    }
    callback({ requestHeaders: details.requestHeaders })
  })

  pythonBackend.on('ready', (port: number) => {
    console.log(`[backend] ready on port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'ready', port })
    startReminderPolling()
  })

  // The port isn't a constant: pickPort() may land on a fallback when the
  // preferred one is unbindable (Windows reserved ranges). Tell the renderer as
  // soon as we know, so it probes the right port from the first attempt.
  pythonBackend.on('port', (port: number) => {
    console.log(`[backend] using port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'starting', port })
  })

  // The backend went away after having served requests. Tell the renderer so it
  // drops its cached 'ready' — otherwise the window keeps looking healthy while
  // every request fails, which is how a dead backend used to surface as a bare
  // "TypeError: Failed to fetch" in the chat.
  pythonBackend.on('lost', () => {
    console.warn('[backend] stopped responding')
    mainWindow?.webContents.send('backend-status', { status: 'lost' })
  })

  pythonBackend.on('error', (error: BackendError) => {
    // Mirror to the main-process stdout too: otherwise backend startup errors
    // are only visible in the renderer devtools, making `npm run dev` hangs
    // impossible to diagnose from the terminal.
    console.error(`[backend] error: ${error.code} — ${error.message}${error.path ? ` [${error.path}]` : ''}`)
    sendBackendState()
  })

  pythonBackend.on('log', (line: string) => {
    console.log(`[backend] ${line}`)
    mainWindow?.webContents.send('backend-log', line)
  })

  await pythonBackend.start()
}

interface ReminderDelivery {
  delivery_id: string
  claim_id: string
  title: string
  body?: string
  notification_title?: string
}

function desktopPost<T>(port: number, token: string, route: string, body: object): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body)
    const req = http.request({
      hostname: '127.0.0.1', port, path: route, method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
      timeout: 10_000,
    }, (res) => {
      let raw = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => { raw += chunk })
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(new Error(`Reminder API returned ${res.statusCode}`))
        try { resolve(JSON.parse(raw) as T) } catch (error) { reject(error) }
      })
    })
    req.on('timeout', () => req.destroy(new Error('Reminder API timed out')))
    req.on('error', reject)
    req.end(payload)
  })
}

async function pollDesktopReminders() {
  if (reminderPollActive || !pythonBackend || pythonBackend.getStatus() !== 'ready') return
  reminderPollActive = true
  try {
    const port = pythonBackend.getPort()
    const token = pythonBackend.getInternalToken()
    const claimed = await desktopPost<{ deliveries: ReminderDelivery[] }>(
      port, token, '/api/desktop/notifications/claim', {})
    for (const delivery of claimed.deliveries || []) {
      let shown = false
      let error = ''
      try {
        if (!Notification.isSupported()) throw new Error('System notifications are unavailable')
        const icon = getRuntimeAppIcon() || getIconPath('png')
        const notification = new Notification({
          title: delivery.notification_title || '事务到期',
          body: delivery.body || delivery.title,
          ...(icon ? { icon } : {}),
        })
        notification.show()
        shown = true
      } catch (cause) {
        error = cause instanceof Error ? cause.message : String(cause)
      }
      await desktopPost(port, token, '/api/desktop/notifications/ack', {
        delivery_id: delivery.delivery_id, claim_id: delivery.claim_id, shown, error,
      })
    }
  } catch (error) {
    console.warn('[reminders] claim or delivery failed:', error)
  } finally {
    reminderPollActive = false
  }
}

function startReminderPolling() {
  if (!reminderPollTimer) reminderPollTimer = setInterval(pollDesktopReminders, 30_000)
  void pollDesktopReminders()
}

function setupIPC() {
  // Await the port decision rather than reading the current guess: the renderer
  // usually asks before startBackend() has probed anything, and a wrong answer
  // here means it polls a port nothing will ever listen on.
  ipcMain.handle('get-backend-port', async () => {
    return pythonBackend ? pythonBackend.whenPortReady() : null
  })

  ipcMain.handle('get-backend-status', () => {
    return pythonBackend?.getStatus() ?? 'stopped'
  })

  // Pull-based access to the last failure, so the renderer can always ask why
  // startup failed instead of depending on having been subscribed at the exact
  // moment the event fired.
  ipcMain.handle('get-backend-error', () => {
    return pythonBackend?.getLastError() ?? null
  })

  // Where config.json and run.log live, so the error screen can open the folder
  // for a user whose UI never came up.
  ipcMain.handle('get-data-dir', () => {
    return pythonBackend?.getDataDir() ?? ''
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

  // Open a local file with the OS default app; falls back to revealing it in
  // the file manager when no handler exists. Returns '' on success.
  ipcMain.handle('open-path', async (_event, targetPath: string) => {
    if (!targetPath) return 'empty path'
    const err = await shell.openPath(targetPath)
    if (err) shell.showItemInFolder(targetPath)
    return err
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

  // Current app version, shown in the NavRail footer.
  ipcMain.handle('get-app-version', () => app.getVersion())

  // Launch-at-login: backed by the OS login-item registry on macOS and the
  // Run registry key on Windows (both handled natively by Electron). Linux has
  // no reliable cross-desktop mechanism, so it reports/accepts nothing there.
  //
  // Windows caveat: we register our Run key WITH `args: ['--hidden']`. Per the
  // Electron docs, `openAtLogin` only reports true when getLoginItemSettings()
  // is called with the SAME `args` — so we MUST pass them here to match, or the
  // toggle "snaps back" to off (a false readback overwrites the flip). We do NOT
  // use `executableWillLaunchAtLogin`: it ignores args and reports true for ANY
  // startup entry for this exe (e.g. one added by an installer / Startup-folder
  // shortcut), which made the toggle appear ON by default. Matching args keeps
  // the default OFF and only reflects the entry this app actually created.
  const WIN_LOGIN_ARGS = ['--hidden']
  const isLaunchAtLoginEnabled = (): boolean => {
    if (isWin) return app.getLoginItemSettings({ args: WIN_LOGIN_ARGS }).openAtLogin === true
    if (isMac) return app.getLoginItemSettings().openAtLogin
    return false
  }
  ipcMain.handle('get-login-item', () => isLaunchAtLoginEnabled())
  // Returns the real outcome so the UI never lies: { ok, enabled, error }.
  // - ok=false + error: writing the login item threw (surface it, don't swallow).
  // - ok=true but enabled!=requested: the OS/policy silently refused the change.
  // The renderer shows the reason instead of just snapping the toggle back.
  ipcMain.handle('set-login-item', (_event, enabled: boolean) => {
    if (!isMac && !isWin) {
      return { ok: false, enabled: false, error: 'unsupported-platform' }
    }
    try {
      app.setLoginItemSettings({
        openAtLogin: !!enabled,
        // Start hidden/minimized so autostart is unobtrusive; the window can
        // still be brought up from the Dock/tray.
        openAsHidden: isMac ? true : undefined,
        args: isWin ? WIN_LOGIN_ARGS : undefined,
      })
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      console.error('[login-item] setLoginItemSettings failed:', error)
      return { ok: false, enabled: isLaunchAtLoginEnabled(), error }
    }
    const effective = isLaunchAtLoginEnabled()
    return { ok: effective === !!enabled, enabled: effective, error: '' }
  })

  // Update checks: renderer-driven "check for update" plus the silent poll
  // below. Finding a newer GitHub Release only opens the panel; the download
  // button hands the URL to the system browser (no in-app installer).
  ipcMain.handle('update-check', () => {
    // This channel is only hit by an explicit "check for update" click, so the
    // panel should re-open even if the version was previously dismissed.
    checkForUpdates(true)
  })
  ipcMain.handle('update-download', (_event, url?: string) => {
    openDownload(url)
  })

  // Synchronous OS locale lookup (e.g. "zh-CN", "en-US"). Used by the renderer
  // to pick a sensible default UI language on first run before any paint.
  ipcMain.on('get-system-locale', (event) => {
    event.returnValue = app.getLocale() || app.getSystemLocale?.() || ''
  })

  // Show a native OS notification (e.g. a scheduler reminder or a finished
  // task). Clicking it brings the window forward and asks the renderer to open
  // the given session.
  ipcMain.handle('notify', (_event, payload: { title?: string; body?: string; sessionId?: string; silent?: boolean; showWhenFocused?: boolean }) => {
    if (!Notification.isSupported() || !payload?.body) return false
    // Skip when the window is focused: the user is already watching, so a
    // notification (and sound) would just be noise, especially for short tasks.
    if (mainWindow?.isFocused() && !payload.showWhenFocused) return false
    // Use the runtime app icon if one was set (via set-app-icon), so the
    // notification matches the current window/Dock icon. Falls back to the
    // packaged icon.
    const iconOpt = getRuntimeAppIcon() || getIconPath('png')
    const n = new Notification({
      title: payload.title || app.name,
      body: payload.body,
      silent: !!payload.silent,
      ...(iconOpt ? { icon: iconOpt } : {}),
    })
    n.on('click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
      }
      if (payload.sessionId) {
        mainWindow?.webContents.send('open-session', payload.sessionId)
      }
    })
    n.show()
    return true
  })
}

function emitMaximizeState() {
  const max = mainWindow?.isMaximized() ?? false
  mainWindow?.webContents.send('window-maximize-changed', max)
}

// Both builds share one Electron profile and one backend data directory. A new
// launch asks the current owner to quit, then waits for the lock before it
// opens either the profile or the data store.
app.on('second-instance', (_event, _argv, _workingDirectory, additionalData) => {
  if (replacingInstance) return
  replacingInstance = true
  isQuitting = true
  const request = additionalData as { executable?: unknown; args?: unknown } | undefined
  if (typeof request?.executable === 'string' && Array.isArray(request.args) &&
      request.args.every(arg => typeof arg === 'string')) {
    app.relaunch({ execPath: request.executable, args: request.args })
  } else {
    app.relaunch()
  }
  app.quit()
})

const launchArgs = process.argv.slice(1).map((arg, index) =>
  index === 0 && !arg.startsWith('-') ? path.resolve(arg) : arg)
const gotTheLock = app.requestSingleInstanceLock({ executable: process.execPath, args: launchArgs })
if (!gotTheLock) {
  app.quit()
}

if (gotTheLock) app.whenReady().then(async () => {
  if (replacingInstance) return
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

  // The chat input's voice recording uses getUserMedia. Approval of media
  // permission requests isn't guaranteed without an explicit handler across
  // Electron versions/platforms, so allow them; other permission types keep
  // the same default allow behavior the app had without a handler.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(true))

  // On macOS the Chromium-layer handler above isn't enough: getUserMedia also
  // needs system-level (TCC) microphone authorization, which only the native
  // askForMediaAccess prompt can grant. Request it up front so the first mic
  // click surfaces the system dialog instead of failing with a denied error.
  if (process.platform === 'darwin') {
    const micStatus = systemPreferences.getMediaAccessStatus('microphone')
    if (micStatus === 'not-determined') {
      systemPreferences.askForMediaAccess('microphone').catch(() => {})
    }
  }

  setupIPC()
  setupThemeIPC()
  setupHttpRelayIPC()
  setupAppIconIPC({ getWindow: () => mainWindow, getTray })
  createWindow()
  buildAppMenu(() => mainWindow)
  // No menu-bar tray on macOS — the Dock + window controls are enough there.
  // Keep the tray on Windows/Linux where minimizing to a tray icon is expected.
  if (!isMac) {
    createTray({
      getWindow: () => mainWindow,
      iconPath: getIconPath('png'),
      onQuit: () => {
        isQuitting = true
        app.quit()
      },
    })
  }
  // Re-apply a previously set icon/title before the page loads.
  applyCachedAppIcon()
  await startBackend()

  // Wire update checks: a first silent check a few seconds after launch (so it
  // doesn't compete with backend startup), then poll every 4 hours so a
  // long-running window still surfaces new releases. Both are automatic checks
  // (userInitiated=false): the panel auto-opens once per new version, and once
  // the user dismisses it these polls only keep the footer/menu dot lit rather
  // than re-popping the panel. Download is always a browser hand-off.
  initUpdater(() => mainWindow)
  setTimeout(() => checkForUpdates(), 5000)
  const UPDATE_POLL_MS = 4 * 60 * 60 * 1000
  setInterval(() => checkForUpdates(), UPDATE_POLL_MS)

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
  if (replacingInstance) pythonBackend?.stopSync()
  else pythonBackend?.stop()
})
