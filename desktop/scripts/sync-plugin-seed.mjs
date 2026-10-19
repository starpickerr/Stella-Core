#!/usr/bin/env node
/**
 * Write desktop/resources/plugin-catalog.json from Stella-Plugins/catalog/official.json.
 * Core-only packaging: do NOT copy plugin trees into resources/plugin-seed.
 * Packaged first boot resolves catalog entries without local seed paths
 * (missing_source until signed packages are fetched or a sibling checkout is used).
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(__dirname, '..')
const coreRoot = path.resolve(desktopRoot, '..')
const officialCatalog = path.resolve(coreRoot, '..', 'Stella-Plugins', 'catalog', 'official.json')
const seedRoot = path.join(desktopRoot, 'resources', 'plugin-seed')
const catalogPath = path.join(desktopRoot, 'resources', 'plugin-catalog.json')

if (!fs.existsSync(officialCatalog)) {
  console.error(`missing Stella-Plugins catalog at ${officialCatalog}`)
  process.exit(1)
}

const source = JSON.parse(fs.readFileSync(officialCatalog, 'utf8'))
if (!source.coreApi || !Array.isArray(source.plugins) || source.plugins.length === 0) {
  console.error('official catalog missing coreApi/plugins')
  process.exit(1)
}

// Packaged catalog: keep identity + digest + optional url; drop local checkout paths
// so DMG bootstrap cannot accidentally depend on sibling Stella-Plugins or seed trees.
const plugins = source.plugins.map((entry) => {
  const next = {
    pluginId: entry.pluginId,
    hostApi: entry.hostApi || '^1.0.0',
    version: entry.version,
    sha256: entry.sha256,
  }
  if (entry.url) next.url = entry.url
  return next
})

for (const entry of plugins) {
  if (!entry.pluginId || !entry.version || !entry.sha256) {
    console.error(`catalog entry incomplete: ${JSON.stringify(entry)}`)
    process.exit(1)
  }
}

fs.rmSync(seedRoot, { recursive: true, force: true })
fs.mkdirSync(path.dirname(catalogPath), { recursive: true })
const catalog = { coreApi: source.coreApi, plugins }
fs.writeFileSync(catalogPath, `${JSON.stringify(catalog, null, 2)}\n`)
console.log(`wrote ${catalogPath} (${plugins.length} plugins, no plugin-seed)`)
for (const entry of plugins) {
  console.log(`  ${entry.pluginId}@${entry.version}`)
}
