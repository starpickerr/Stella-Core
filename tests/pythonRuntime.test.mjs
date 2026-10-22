import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, realpathSync, symlinkSync, mkdirSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { findDevelopmentPython } from '../desktop/src/main/python-runtime.ts'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

test('desktop startup resolves the same Conda interpreter as the quality tools', () => {
  const expected = execFileSync('python3', [path.join(root, 'scripts/check_runtime.py')], { encoding: 'utf8' }).trim()
  assert.equal(realpathSync(findDevelopmentPython(root)), realpathSync(expected))
})

test('an invalid explicit interpreter is rejected instead of silently switching environments', () => {
  assert.throws(() => findDevelopmentPython(root, {
    PATH: process.env.PATH,
    STELLA_PYTHON: path.join(root, 'missing-conda-python'),
  }), /STELLA_PYTHON/)
})

test('desktop can bootstrap registered Conda Stella with no Python command on PATH', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'stella-bootstrap-'))
  try {
    const real = findDevelopmentPython(root)
    const prefix = path.join(directory, 'Stella')
    const executableName = process.platform === 'win32' ? 'python.exe' : 'python'
    const executableDir = process.platform === 'win32' ? prefix : path.join(prefix, 'bin')
    mkdirSync(path.join(prefix, 'conda-meta'), { recursive: true })
    mkdirSync(executableDir, { recursive: true })
    const executable = path.join(executableDir, executableName)
    symlinkSync(real, executable, 'file')
    mkdirSync(path.join(directory, '.conda'))
    writeFileSync(path.join(directory, '.conda', 'environments.txt'), `${prefix}\n`)
    const actual = findDevelopmentPython(root, {
      PATH: '', HOME: directory, USERPROFILE: directory, SYSTEMROOT: process.env.SYSTEMROOT,
    })
    assert.equal(realpathSync(actual), realpathSync(executable))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test('desktop accepts an interpreter path containing spaces without shell interpolation', { skip: process.platform === 'win32' }, () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'stella python '))
  try {
    const target = findDevelopmentPython(root)
    const alias = path.join(directory, 'selected python')
    symlinkSync(target, alias)
    assert.equal(findDevelopmentPython(root, { ...process.env, STELLA_PYTHON: alias }), alias)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
