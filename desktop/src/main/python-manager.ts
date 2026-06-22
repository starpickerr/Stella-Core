import { ChildProcess, spawn } from 'child_process'
import { EventEmitter } from 'events'
import path from 'path'
import fs from 'fs'
import http from 'http'

export class PythonBackend extends EventEmitter {
  private process: ChildProcess | null = null
  private backendPath: string
  private port: number = 9899
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

  private readPort(): number {
    try {
      const configPath = path.join(this.backendPath, 'config.json')
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        if (config.web_port) {
          return config.web_port
        }
      }
    } catch {
      // ignore
    }
    return 9899
  }

  async start(): Promise<void> {
    if (this.status === 'ready' || this.status === 'starting') {
      return
    }

    this.status = 'starting'
    this.port = this.readPort()

    const alreadyRunning = await this.probeHealth()
    if (alreadyRunning) {
      this.status = 'ready'
      this.emit('log', `Backend already running on port ${this.port}`)
      this.emit('ready', this.port)
      return
    }

    const pythonPath = this.findPython()
    const appPath = path.join(this.backendPath, 'app.py')

    if (!fs.existsSync(appPath)) {
      this.status = 'error'
      this.emit('error', `app.py not found at ${appPath}`)
      return
    }

    this.emit('log', `Starting Python backend: ${pythonPath} ${appPath}`)

    this.process = spawn(pythonPath, [appPath], {
      cwd: this.backendPath,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
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

  private probeHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${this.port}/config`, (res) => {
        resolve(res.statusCode === 200)
      })
      req.on('error', () => resolve(false))
      req.setTimeout(2000, () => { req.destroy(); resolve(false) })
    })
  }

  private waitForReady(): Promise<void> {
    return new Promise((resolve) => {
      const maxAttempts = 120
      let attempts = 0

      const check = () => {
        attempts++
        if (attempts % 10 === 0) {
          this.emit('log', `Waiting for backend... (${attempts}s)`)
        }

        const req = http.get(`http://127.0.0.1:${this.port}/config`, (res) => {
          if (res.statusCode === 200) {
            this.status = 'ready'
            this.emit('log', `Backend ready on port ${this.port} after ${attempts}s`)
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
        if (this.status === 'stopped') {
          resolve()
          return
        }
        if (attempts >= maxAttempts) {
          this.status = 'error'
          this.emit('error', `Backend failed to start within ${maxAttempts} seconds`)
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
