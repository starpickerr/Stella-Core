import { execFileSync } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

/** Source checkouts share the same Conda resolver as Make and Python quality tools. */
export function findDevelopmentPython(backendPath: string, env: NodeJS.ProcessEnv = process.env): string {
  const resolver = path.join(backendPath, 'scripts', 'check_runtime.py')
  // Bootstrap only: the Python resolver remains responsible for final selection.
  const home = env.HOME || env.USERPROFILE || os.homedir()
  const prefixes: string[] = env.CONDA_PREFIX ? [env.CONDA_PREFIX] : []
  const registry = path.join(home, '.conda', 'environments.txt')
  if (fs.existsSync(registry)) prefixes.push(...fs.readFileSync(registry, 'utf8').split(/\r?\n/).map(line => line.trim()).filter(Boolean))
  const roots = ['anaconda3', 'miniconda3', 'miniforge3', 'mambaforge', '.conda'].map(name => path.join(home, name))
  if (env.CONDA_EXE) roots.unshift(path.dirname(path.dirname(env.CONDA_EXE)))
  if (process.platform === 'win32') {
    for (const base of [env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), env.PROGRAMDATA || 'C:/ProgramData']) {
      roots.push(...['anaconda3', 'miniconda3', 'miniforge3'].map(name => path.join(base, name)))
    }
  } else {
    roots.push(...['anaconda3', 'miniconda3', 'miniforge3'].map(name => path.join('/opt', name)), '/opt/homebrew/Caskroom/miniconda/base')
  }
  for (const root of [...roots, ...(env.CONDA_ENVS_PATH || '').split(path.delimiter).filter(Boolean)]) {
    const base = roots.includes(root) ? path.join(root, 'envs') : root
    prefixes.push(...['Stella', 'stella'].map(name => path.join(base, name)))
  }
  const bootstrap = prefixes.filter(prefix => path.basename(prefix).toLowerCase() === 'stella' && fs.existsSync(path.join(prefix, 'conda-meta')))
    .map(prefix => path.join(prefix, process.platform === 'win32' ? 'python.exe' : 'bin/python'))
  const candidates = env.STELLA_PYTHON ? [env.STELLA_PYTHON] : [...new Set([...bootstrap, 'python3', 'python'])]
  let lastError: unknown
  for (const executable of candidates) {
    try {
      const python = execFileSync(executable, [resolver], {
        cwd: backendPath,
        env,
        encoding: 'utf8',
        timeout: 15_000,
        stdio: ['ignore', 'pipe', 'pipe'],
      }).trim()
      if (python) return python
    } catch (error) {
      lastError = error
    }
  }
  throw new Error(`Cannot resolve Conda Stella Python. Configure STELLA_PYTHON. ${String(lastError)}`)
}
