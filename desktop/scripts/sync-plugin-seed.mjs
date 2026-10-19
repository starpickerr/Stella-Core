#!/usr/bin/env node
/**
 * Copy Stella-Plugins default packages into desktop/resources/plugin-seed and
 * write resources/plugin-catalog.json with catalog-relative paths so a packaged
 * DMG can first-boot without a sibling checkout or network.
 */
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(__dirname, '..')
const coreRoot = path.resolve(desktopRoot, '..')
const pluginsRoot = path.resolve(coreRoot, '..', 'Stella-Plugins', 'plugins')
const seedRoot = path.join(desktopRoot, 'resources', 'plugin-seed')
const catalogPath = path.join(desktopRoot, 'resources', 'plugin-catalog.json')

const DOMAINS = [
  'bills',
  'calendar',
  'tasks',
  'email',
  'elearning',
  'briefing',
  'automation',
]

function packageFiles(root) {
  const files = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === '__pycache__') continue
        walk(full)
      } else if (entry.isFile()) {
        if (entry.name.endsWith('.pyc') || entry.name.endsWith('.pyo')) continue
        files.push(full)
      }
    }
  }
  walk(root)
  return files.sort()
}

function treeDigest(root) {
  const h = createHash('sha256')
  for (const file of packageFiles(root)) {
    const rel = path.relative(root, file).split(path.sep).join('/')
    h.update(rel)
    h.update('\0')
    h.update(fs.readFileSync(file))
    h.update('\0')
  }
  return h.digest('hex')
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue
    const from = path.join(src, entry.name)
    const to = path.join(dest, entry.name)
    if (entry.isDirectory()) copyDir(from, to)
    else if (entry.isFile() && !entry.name.endsWith('.pyc') && !entry.name.endsWith('.pyo')) {
      fs.copyFileSync(from, to)
    }
  }
}

if (!fs.existsSync(pluginsRoot)) {
  console.error(`missing Stella-Plugins at ${pluginsRoot}`)
  process.exit(1)
}

fs.rmSync(seedRoot, { recursive: true, force: true })
fs.mkdirSync(seedRoot, { recursive: true })

const plugins = []
for (const domain of DOMAINS) {
  const src = path.join(pluginsRoot, domain)
  if (!fs.existsSync(src)) {
    console.error(`missing plugin ${src}`)
    process.exit(1)
  }
  const dest = path.join(seedRoot, domain)
  copyDir(src, dest)
  const digest = treeDigest(dest)
  plugins.push({
    pluginId: `stella.${domain}`,
    hostApi: '^1.0.0',
    version: '1.0.0',
    path: `plugin-seed/${domain}`,
    sha256: digest,
  })
  console.log(`seeded ${domain} sha256=${digest.slice(0, 12)}…`)
}

const catalog = { coreApi: '1.0.0', plugins }
fs.writeFileSync(catalogPath, `${JSON.stringify(catalog, null, 2)}\n`)
console.log(`wrote ${catalogPath}`)
