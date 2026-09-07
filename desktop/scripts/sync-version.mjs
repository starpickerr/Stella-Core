#!/usr/bin/env node
// Copy the repo-root VERSION file into desktop/package.json (and the lockfile
// top-level version fields) so Electron / electron-builder see the same
// number the CLI and Python package use. Edit VERSION to bump; do not edit
// package.json "version" by hand.

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const versionPath = path.join(root, 'VERSION')
const version = fs.readFileSync(versionPath, 'utf8').trim()

// Canonical product version is X.Y.Z (no `v` prefix). Git tags are `v` + this.
if (!/^\d+\.\d+\.\d+$/.test(version)) {
  console.error(
    `[sync-version] VERSION must be X.Y.Z (no v prefix) at ${versionPath}: ${JSON.stringify(version)}`
  )
  process.exit(1)
}

function writeJson(file, data) {
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n')
}

const pkgPath = path.join(root, 'desktop/package.json')
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
if (pkg.version !== version) {
  pkg.version = version
  writeJson(pkgPath, pkg)
  console.log(`[sync-version] desktop/package.json -> ${version}`)
}

const lockPath = path.join(root, 'desktop/package-lock.json')
if (fs.existsSync(lockPath)) {
  const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'))
  let changed = false
  if (lock.version !== version) {
    lock.version = version
    changed = true
  }
  if (lock.packages?.[''] && lock.packages[''].version !== version) {
    lock.packages[''].version = version
    changed = true
  }
  if (changed) {
    writeJson(lockPath, lock)
    console.log(`[sync-version] desktop/package-lock.json -> ${version}`)
  }
}
