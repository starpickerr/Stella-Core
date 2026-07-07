import { app, BrowserWindow } from 'electron'
import fs from 'fs'
import path from 'path'
// electron-updater is CommonJS: its members live on module.exports, with no
// meaningful default export. Under module=commonjs + esModuleInterop, a named
// import compiles to `electron_updater_1.autoUpdater` and resolves correctly,
// whereas `import pkg from 'electron-updater'` yields undefined.
import { autoUpdater } from 'electron-updater'

// Status payloads pushed to the renderer over the 'update-status' channel.
// The renderer drives the NavRail badge + update panel from these.
export type UpdateStatus =
  | { state: 'checking' }
  | { state: 'available'; version: string; notes?: string }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

let getWindow: () => BrowserWindow | null = () => null

// Persist update logs to a file so a user hitting a silent "spinner never
// resolves" can just send us userData/logs/updater.log. We can't rely on a
// logging dep, so this is a tiny append-only writer, plus console for the
// in-app log view / terminal.
let logFile: string | null = null

function initLogFile() {
  try {
    const dir = path.join(app.getPath('userData'), 'logs')
    fs.mkdirSync(dir, { recursive: true })
    logFile = path.join(dir, 'updater.log')
  } catch {
    logFile = null
  }
}

function log(...parts: unknown[]) {
  const line = `[${new Date().toISOString()}] [updater] ${parts
    .map((p) => (typeof p === 'string' ? p : safeStringify(p)))
    .join(' ')}`
  // Console: shows up in the terminal (dev) and the packaged app's stdout.
  console.log(line)
  if (logFile) {
    try {
      fs.appendFileSync(logFile, line + '\n')
    } catch {
      // ignore disk errors — logging must never break the updater
    }
  }
}

function safeStringify(v: unknown): string {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function send(status: UpdateStatus) {
  getWindow()?.webContents.send('update-status', status)
}

export function initUpdater(windowGetter: () => BrowserWindow | null): void {
  getWindow = windowGetter
  initLogFile()

  log(`init: appVersion=${app.getVersion()} packaged=${app.isPackaged} logFile=${logFile ?? '<none>'}`)

  // In dev (not packaged) there's no update feed; skip wiring entirely so
  // electron-updater doesn't throw on the missing app-update.yml.
  if (!app.isPackaged) {
    log('not packaged — updater wiring skipped')
    return
  }

  // User-driven flow: we surface "available" and let the user opt in to the
  // download, rather than pulling bytes silently in the background.
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true
  // The desktop channel ships pre-release-tagged builds (e.g. 0.0.8-test), so a
  // current version like 0.0.7-test must be allowed to compare against, and be
  // offered, other pre-release versions. Without this electron-updater's semver
  // compare can silently skip pre-releases and neither "available" nor
  // "not-available" fires — the UI just spins forever.
  autoUpdater.allowPrerelease = true
  autoUpdater.allowDowngrade = false
  // Route electron-updater's own internal logging to our file too, so we
  // capture the feed URL, parsed versions and any stack traces it logs.
  autoUpdater.logger = {
    info: (m: unknown) => log('eu-info:', m),
    warn: (m: unknown) => log('eu-warn:', m),
    error: (m: unknown) => log('eu-error:', m),
    debug: (m: unknown) => log('eu-debug:', m),
  } as unknown as typeof autoUpdater.logger

  autoUpdater.on('checking-for-update', () => {
    log(`checking-for-update: current=${app.getVersion()}`)
    send({ state: 'checking' })
  })
  autoUpdater.on('update-available', (info) => {
    log(`update-available: current=${app.getVersion()} remote=${info.version} -> update needed`)
    send({
      state: 'available',
      version: info.version,
      notes: typeof info.releaseNotes === 'string' ? info.releaseNotes : undefined,
    })
  })
  autoUpdater.on('update-not-available', (info) => {
    log(`update-not-available: current=${app.getVersion()} remote=${info?.version ?? '<unknown>'} -> up to date`)
    send({ state: 'not-available' })
  })
  autoUpdater.on('download-progress', (p) => {
    log(`download-progress: ${Math.round(p.percent)}% (${p.transferred}/${p.total} bytes, ${Math.round(p.bytesPerSecond / 1024)} KB/s)`)
    send({ state: 'downloading', percent: Math.round(p.percent) })
  })
  autoUpdater.on('update-downloaded', (info) => {
    log(`update-downloaded: version=${info.version} -> ready to install`)
    send({ state: 'downloaded', version: info.version })
  })
  autoUpdater.on('error', (err) => {
    const message = err == null ? 'unknown' : err.message || String(err)
    log(`error: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message })
  })
}

// Silent check shortly after launch. When not packaged there's no update feed,
// but a manual click should still get visible feedback instead of looking dead:
// reply "not-available" so the menu can show "up to date".
export function checkForUpdates(): void {
  if (!app.isPackaged) {
    // Dev-only UI harness: set COW_MOCK_UPDATE=1 to simulate an available
    // update so the update panel/menu interactions can be exercised in
    // `npm run dev` (where there's no real feed). Never runs in a packaged app.
    if (process.env.COW_MOCK_UPDATE) {
      const version = process.env.COW_MOCK_UPDATE_VERSION || '9.9.9'
      log(`checkForUpdates: not packaged, MOCK available version=${version}`)
      send({ state: 'available', version })
      return
    }
    log('checkForUpdates: not packaged, replying not-available')
    send({ state: 'not-available' })
    return
  }
  log(`checkForUpdates: requesting feed, current=${app.getVersion()}`)
  autoUpdater.checkForUpdates().catch((err) => {
    const message = err?.message || String(err)
    log(`checkForUpdates: request failed: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message })
  })
}

export function startDownload(): void {
  if (!app.isPackaged) return
  log('startDownload: user requested download')
  autoUpdater.downloadUpdate().catch((err) => {
    const message = err?.message || String(err)
    log(`startDownload: failed: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message })
  })
}

export function quitAndInstall(): void {
  if (!app.isPackaged) return
  log('quitAndInstall: relaunching to install update')
  // isSilent=false (show installer), isForceRunAfter=true (relaunch after).
  autoUpdater.quitAndInstall(false, true)
}
