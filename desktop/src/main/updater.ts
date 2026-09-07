import { app, BrowserWindow, net, shell } from 'electron'
import fs from 'fs'
import path from 'path'

// Status payloads pushed to the renderer over the 'update-status' channel.
// The renderer drives the NavRail badge + update panel from these.
export type UpdateStatus =
  | { state: 'checking' }
  // userInitiated: the check came from an explicit "check for update" click
  // (not the startup/interval poll). The renderer uses this to decide whether
  // to auto-open the panel: automatic checks stay silent (dot only) once a
  // version was dismissed; a manual check always re-opens.
  | {
      state: 'available'
      version: string
      notes?: string
      pageUrl: string
      assetUrl?: string
      userInitiated?: boolean
    }
  | { state: 'not-available' }
  | { state: 'error'; message: string; pageUrl: string; userInitiated?: boolean }

const OWNER = 'starpickerr'
const REPO = 'Stella'
const RELEASES_API = `https://api.github.com/repos/${OWNER}/${REPO}/releases?per_page=5`
const RELEASES_PAGE = `https://github.com/${OWNER}/${REPO}/releases`

// Git tags are always `vX.Y.Z`. package.json / VERSION / dmg names use `X.Y.Z`.
const RELEASE_TAG = /^v(\d+\.\d+\.\d+)$/
const CORE_VERSION = /^(\d+)\.(\d+)\.(\d+)$/

let getWindow: () => BrowserWindow | null = () => null

interface GithubAsset {
  name: string
  browser_download_url: string
}

interface GithubRelease {
  tag_name: string
  draft: boolean
  prerelease: boolean
  html_url: string
  body: string | null
  assets: GithubAsset[]
}

function parseCore(raw: string): [number, number, number] | null {
  const v = raw.trim().replace(/^v/i, '')
  const m = v.match(CORE_VERSION)
  if (!m) return null
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

// Eligible GitHub tags only: `vX.Y.Z` (the `v` is required). Returns `X.Y.Z`.
function parseReleaseTag(tag: string): string | null {
  const m = tag.trim().match(RELEASE_TAG)
  return m ? m[1] : null
}

function isNewer(remote: string, current: string): boolean {
  const a = parseCore(remote)
  const b = parseCore(current)
  if (!a) return false
  if (!b) return true
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i]
  }
  return false
}

function pickAsset(assets: GithubAsset[], version: string): string | undefined {
  const names: string[] = []
  if (process.platform === 'darwin') {
    const arch = process.arch === 'arm64' ? 'arm64' : 'x64'
    names.push(`Stella-${version}-${arch}.dmg`)
  } else if (process.platform === 'win32') {
    names.push(`Stella-Setup-${version}-x64.exe`, `Stella-Setup-${version}.exe`)
  }
  for (const name of names) {
    const hit = assets.find((a) => a.name === name)
    if (hit) return hit.browser_download_url
  }
  const fallbackExt = process.platform === 'darwin' ? '.dmg' : process.platform === 'win32' ? '.exe' : ''
  if (!fallbackExt) return undefined
  return assets.find((a) => a.name.toLowerCase().endsWith(fallbackExt))?.browser_download_url
}

function isAllowedDownloadUrl(url: string): boolean {
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    if (u.hostname === 'github.com' && u.pathname.startsWith(`/${OWNER}/${REPO}`)) return true
    if (u.hostname === 'objects.githubusercontent.com') return true
    if (u.hostname.endsWith('.githubusercontent.com')) return true
    return false
  } catch {
    return false
  }
}

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
}

// Tracks whether the in-flight check was triggered by an explicit user click.
// Stamped onto the resulting 'available' event so the renderer knows whether to
// auto-open the panel (manual) or stay silent with just the dot (automatic).
let userInitiatedCheck = false

// Silent check shortly after launch. When not packaged there's no update feed,
// but a manual click should still get visible feedback instead of looking dead:
// reply "not-available" so the menu can show "up to date".
//   userInitiated: pass true for an explicit "check for update" click so the
//   panel re-opens even if the version was previously dismissed. The startup +
//   interval polls pass false, so a dismissed version only lights the dot.
export function checkForUpdates(userInitiated = false): void {
  userInitiatedCheck = userInitiated
  if (!app.isPackaged) {
    // Dev-only UI harness: set STELLA_MOCK_UPDATE=1 to simulate an available
    // update so the update panel/menu interactions can be exercised in
    // `npm run dev` (where there's no real feed). Never runs in a packaged app.
    if (process.env.STELLA_MOCK_UPDATE) {
      const version = process.env.STELLA_MOCK_UPDATE_VERSION || '9.9.9'
      log(`checkForUpdates: not packaged, MOCK available version=${version}`)
      send({
        state: 'available',
        version,
        notes: 'Mock update (STELLA_MOCK_UPDATE)',
        pageUrl: RELEASES_PAGE,
        userInitiated: userInitiatedCheck,
      })
      return
    }
    log('checkForUpdates: not packaged, replying not-available')
    send({ state: 'not-available' })
    return
  }
  void fetchLatestRelease()
}

async function fetchLatestRelease(): Promise<void> {
  const current = app.getVersion()
  log(`checkForUpdates: requesting GitHub releases, current=${current}`)
  send({ state: 'checking' })

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  try {
    const res = await net.fetch(RELEASES_API, {
      signal: controller.signal,
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': `Stella/${current}`,
        'X-GitHub-Api-Version': '2022-11-28',
      },
    })
    if (!res.ok) {
      throw new Error(`GitHub releases ${res.status}`)
    }
    const payload = (await res.json()) as GithubRelease[]
    if (!Array.isArray(payload)) {
      throw new Error('GitHub releases: unexpected payload')
    }
    for (const release of payload) {
      if (release.draft) {
        log(`checkForUpdates: skip draft tag=${release.tag_name}`)
        continue
      }
      if (release.prerelease) {
        log(`checkForUpdates: skip prerelease tag=${release.tag_name}`)
        continue
      }
      const version = parseReleaseTag(release.tag_name)
      if (!version) {
        log(`checkForUpdates: skip tag=${release.tag_name} (need vX.Y.Z)`)
        continue
      }
      if (!isNewer(version, current)) {
        log(`checkForUpdates: latest=${version} current=${current} -> up to date`)
        send({ state: 'not-available' })
        return
      }
      const assetUrl = pickAsset(release.assets || [], version)
      log(
        `checkForUpdates: update-available current=${current} remote=${version} asset=${assetUrl ?? '<none>'} userInitiated=${userInitiatedCheck}`
      )
      const notes = typeof release.body === 'string' && release.body.trim() ? release.body.trim() : undefined
      send({
        state: 'available',
        version,
        notes: notes && notes.length > 4000 ? `${notes.slice(0, 4000)}…` : notes,
        pageUrl: release.html_url || `${RELEASES_PAGE}/tag/v${version}`,
        assetUrl,
        userInitiated: userInitiatedCheck,
      })
      return
    }
    log('checkForUpdates: no published releases -> not-available')
    send({ state: 'not-available' })
  } catch (err) {
    const message = err == null ? 'unknown' : (err as Error).message || String(err)
    log(`checkForUpdates: request failed: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message, pageUrl: RELEASES_PAGE, userInitiated: userInitiatedCheck })
  } finally {
    clearTimeout(timer)
  }
}

export function openDownload(url?: string): void {
  const target = url && isAllowedDownloadUrl(url) ? url : RELEASES_PAGE
  log(`openDownload: ${target}`)
  void shell.openExternal(target)
}
