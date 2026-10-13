import { spawn, execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import electron from 'electron'

const desktopDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function isAlive(pid) {
  try { process.kill(pid, 0); return true } catch { return false }
}

async function waitForExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (isAlive(pid) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  return !isAlive(pid)
}

async function stopProfileOwner(lockPath, ownsProfile) {
  let pid
  try {
    const match = fs.readlinkSync(lockPath).match(/-(\d+)$/)
    pid = match ? Number(match[1]) : undefined
  } catch { return }
  if (!pid || pid === process.pid) return

  let command
  try {
    command = execFileSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' }).trim()
  } catch { return }
  if (!ownsProfile(command)) return

  const backendPath = path.resolve(desktopDir, '..', 'app.py')
  let backendPids = []
  try {
    backendPids = execFileSync('ps', ['-axo', 'pid=,ppid=,command='], { encoding: 'utf8' })
      .split('\n')
      .map(line => line.trim().match(/^(\d+)\s+(\d+)\s+(.+)$/))
      .filter(row => row && Number(row[2]) === pid &&
        (row[3].includes(` ${backendPath}`) || /\/stella-backend(?:\s|$)/.test(row[3])))
      .map(row => Number(row[1]))
  } catch { /* the old process may already be exiting */ }

  try { process.kill(pid, 'SIGTERM') } catch { return }
  if (!(await waitForExit(pid, 3000))) {
    try { process.kill(pid, 'SIGKILL') } catch { /* already exited */ }
    if (!(await waitForExit(pid, 1000))) throw new Error(`Previous Stella process ${pid} is still running`)
  }
  for (const backendPid of backendPids) {
    if (!isAlive(backendPid)) continue
    try { process.kill(backendPid, 'SIGTERM') } catch { continue }
    if (!(await waitForExit(backendPid, 2000))) {
      try { process.kill(backendPid, 'SIGKILL') } catch { /* already exited */ }
      if (!(await waitForExit(backendPid, 1000))) throw new Error(`Previous Stella backend ${backendPid} is still running`)
    }
  }
}

// A source launch may encounter either the old isolated development profile
// or an installed client whose older code only focuses itself on a second
// launch. End the verified owner before opening the shared profile and data.
async function stopRunningDesktopInstance() {
  if (process.platform !== 'darwin' && process.platform !== 'linux') return
  const appData = process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library', 'Application Support')
    : process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config')
  const profile = path.join(appData, 'Stella')
  await stopProfileOwner(path.join(profile, 'development', 'SingletonLock'),
    command => command.startsWith(`${electron} `))
  await stopProfileOwner(path.join(profile, 'SingletonLock'),
    command => command.startsWith(`${electron} `) ||
      /(?:^|\/)Stella\.app\/Contents\/MacOS\/Stella(?:\s|$)/.test(command))
}

const env = { ...process.env }
// Codex and some other Electron-based terminals set this for their own child
// tools. It would make our Electron executable act as plain Node instead.
delete env.ELECTRON_RUN_AS_NODE

await stopRunningDesktopInstance()

const child = spawn(electron, ['.', ...process.argv.slice(2)], {
  cwd: desktopDir,
  env,
  stdio: 'inherit',
})

child.on('error', error => {
  console.error(`Could not start Electron: ${error.message}`)
  process.exitCode = 1
})
child.on('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0)
})
