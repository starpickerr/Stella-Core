import { ChildProcess, spawn } from 'child_process'
import { EventEmitter } from 'events'
import path from 'path'
import os from 'os'
import fs from 'fs'
import http from 'http'
import net from 'net'

// Writable data dir for the packaged app (config.json, run.log, user data).
// Lives in the user's home so it survives app updates and avoids writing into
// the read-only app bundle. Source/dev runs keep using the repo CWD instead.
const COW_DATA_DIR = path.join(os.homedir(), '.cow')

// Preferred port for the desktop backend. Deliberately not 9899 (the web
// console's default) so a source-run `python app.py` never collides with the
// packaged app. It's only a *preference*: if it's taken we bind a free port
// chosen by the OS, so we never hard-depend on any single port being free.
const PREFERRED_PORT = 9876

export class PythonBackend extends EventEmitter {
  private process: ChildProcess | null = null
  private backendPath: string
  private port: number = PREFERRED_PORT
  private status: 'stopped' | 'starting' | 'ready' | 'error' = 'stopped'

  constructor(backendPath: string) {
    super()
    this.backendPath = backendPath
  }

  getPort(): number {
    return this.port
  }

  getStatus(): string {
    return this.status
  }

  /**
   * Locate the packaged onedir backend executable shipped with the app.
   * Returns null when not present (e.g. during local development), so we can
   * fall back to running app.py with a system/venv Python.
   */
  private findBundledBackend(): string | null {
    const exeName = process.platform === 'win32' ? 'cowagent-backend.exe' : 'cowagent-backend'
    const candidates = [
      path.join(this.backendPath, 'cowagent-backend', exeName),
      path.join(this.backendPath, exeName),
    ]
    for (const p of candidates) {
      if (fs.existsSync(p)) {
        return p
      }
    }
    return null
  }

  private findPython(): string {
    const venvPaths = [
      path.join(this.backendPath, '.venv', 'bin', 'python'),
      path.join(this.backendPath, '.venv', 'Scripts', 'python.exe'),
      path.join(this.backendPath, 'venv', 'bin', 'python'),
      path.join(this.backendPath, 'venv', 'Scripts', 'python.exe'),
    ]

    for (const p of venvPaths) {
      if (fs.existsSync(p)) {
        return p
      }
    }

    return process.platform === 'win32' ? 'python' : 'python3'
  }

  /**
   * Read an explicit `web_port` from config.json, if the user pinned one. The
   * packaged build keeps config in COW_DATA_DIR (~/.cow); dev reads it from the
   * repo path. Returns null when unset, so the caller can auto-pick a free port
   * instead of fighting over a fixed one.
   */
  private readConfiguredPort(dataDir: string): number | null {
    try {
      const configPath = path.join(dataDir, 'config.json')
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        const p = Number(config.web_port)
        if (Number.isInteger(p) && p > 0 && p < 65536) {
          return p
        }
      }
    } catch {
      // ignore — fall through to auto-selection
    }
    return null
  }

  /**
   * Resolve a usable port without hard-depending on any specific one:
   *   1. A user-pinned web_port is honored as-is (their explicit choice).
   *   2. Otherwise try PREFERRED_PORT; if free, use it.
   *   3. If taken, let the OS hand us a guaranteed-free ephemeral port.
   * This never throws on a busy port — it just moves on to a free one.
   */
  private async resolvePort(dataDir: string): Promise<number> {
    const pinned = this.readConfiguredPort(dataDir)
    if (pinned !== null) {
      return pinned
    }
    if (await this.isPortFree(PREFERRED_PORT)) {
      return PREFERRED_PORT
    }
    return this.findFreePort()
  }

  /** True if we can bind 127.0.0.1:port right now (i.e. it's free). */
  private isPortFree(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once('error', () => resolve(false))
        .once('listening', () => {
          tester.close(() => resolve(true))
        })
        .listen(port, '127.0.0.1')
    })
  }

  /** Ask the OS for a free ephemeral port (listen on 0, read the assigned one). */
  private findFreePort(): Promise<number> {
    return new Promise((resolve, reject) => {
      const srv = net.createServer()
      srv.once('error', reject)
      srv.listen(0, '127.0.0.1', () => {
        const addr = srv.address()
        const port = typeof addr === 'object' && addr ? addr.port : PREFERRED_PORT
        srv.close(() => resolve(port))
      })
    })
  }

  async start(): Promise<void> {
    if (this.status === 'ready' || this.status === 'starting') {
      return
    }

    this.status = 'starting'

    // Prefer the packaged self-contained backend (production); fall back to
    // running app.py with a Python interpreter (local development).
    const bundled = this.findBundledBackend()
    // Packaged app stores writable data in ~/.cow; dev keeps it in the repo.
    const dataDir = bundled ? COW_DATA_DIR : this.backendPath

    // Always launch our OWN backend (re-entrancy is guarded above by the
    // status check, so we never double-spawn for this instance). We don't reuse
    // whatever happens to be on the port: that's how the app previously
    // attached to a source-run web console and read the wrong config. Pick a
    // usable port instead — honoring a user-pinned web_port, else PREFERRED_PORT
    // when free, else an OS-assigned free port. This never depends on a probe.
    try {
      this.port = await this.resolvePort(dataDir)
    } catch {
      this.port = PREFERRED_PORT
    }

    let command: string
    let args: string[]
    let cwd: string

    if (bundled) {
      command = bundled
      args = []
      // Run from the writable data dir (~/.cow), NOT the install dir. When the
      // app is installed under Program Files, a non-admin user has no write
      // permission to the executable's folder, so any relative-path write
      // during startup would crash the backend (works only as admin). The
      // bundle reads its read-only resources via sys._MEIPASS, so cwd is free
      // to point elsewhere.
      try {
        fs.mkdirSync(COW_DATA_DIR, { recursive: true })
      } catch {
        // ignore — get_data_root() also ensures the dir on the Python side
      }
      cwd = COW_DATA_DIR
      this.emit('log', `Starting bundled backend: ${bundled} (cwd=${cwd})`)
    } else {
      const pythonPath = this.findPython()
      const appPath = path.join(this.backendPath, 'app.py')
      if (!fs.existsSync(appPath)) {
        this.status = 'error'
        this.emit('error', `app.py not found at ${appPath}`)
        return
      }
      command = pythonPath
      args = [appPath]
      cwd = this.backendPath
      this.emit('log', `Starting Python backend: ${pythonPath} ${appPath}`)
    }

    this.process = spawn(command, args, {
      cwd,
      // COW_DESKTOP enables the lighter desktop runtime (no plugins, no MCP).
      // COW_DATA_DIR (packaged only) redirects writable data to ~/.cow so the
      // app bundle stays read-only; dev runs omit it and keep using the repo.
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        COW_DESKTOP: '1',
        // The shell owns the port: tell the backend to bind exactly here so the
        // two sides can never disagree (and we avoid the 9899 web-console clash).
        COW_WEB_PORT: String(this.port),
        ...(bundled ? { COW_DATA_DIR } : {}),
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    })

    this.process.stdout?.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean)
      for (const line of lines) {
        this.emit('log', line)
      }
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean)
      for (const line of lines) {
        this.emit('log', line)
      }
    })

    this.process.on('exit', (code) => {
      this.status = 'stopped'
      this.emit('log', `Python process exited with code ${code}`)
      if (code !== 0 && code !== null) {
        this.emit('error', `Python process exited with code ${code}`)
      }
    })

    this.process.on('error', (err) => {
      this.status = 'error'
      this.emit('error', `Failed to start Python: ${err.message}`)
    })

    await this.waitForReady()
  }

  private waitForReady(): Promise<void> {
    return new Promise((resolve) => {
      // Wall-clock deadline rather than an attempt counter: if the machine
      // sleeps/suspends, the 1s timers stretch out and a counter would give up
      // far too early. Time-based bounding tracks real elapsed time instead.
      const timeoutMs = 120_000
      const startedAt = Date.now()

      const check = () => {
        const req = http.get(`http://127.0.0.1:${this.port}/config`, (res) => {
          if (res.statusCode === 200) {
            this.status = 'ready'
            this.emit('log', `Backend ready on port ${this.port}`)
            this.emit('ready', this.port)
            resolve()
          } else {
            retry()
          }
        })

        req.on('error', () => retry())
        req.setTimeout(2000, () => {
          req.destroy()
          retry()
        })
      }

      const retry = () => {
        if (this.status === 'stopped' || this.status === 'ready') {
          resolve()
          return
        }
        if (Date.now() - startedAt >= timeoutMs) {
          this.status = 'error'
          this.emit('error', `Backend failed to start within ${Math.round(timeoutMs / 1000)} seconds`)
          resolve()
          return
        }
        setTimeout(check, 1000)
      }

      setTimeout(check, 2000)
    })
  }

  stop(): void {
    const proc = this.process
    if (proc) {
      proc.kill('SIGTERM')
      // Keep a local ref so the SIGKILL fallback can still reach the process
      // even after we clear `this.process`; otherwise a stuck backend would
      // never be force-killed and leak as a zombie.
      setTimeout(() => {
        if (!proc.killed) {
          proc.kill('SIGKILL')
        }
      }, 5000)
      this.process = null
    }
    this.status = 'stopped'
  }

  async restart(): Promise<void> {
    this.stop()
    await new Promise((resolve) => setTimeout(resolve, 2000))
    await this.start()
  }
}
