#!/usr/bin/env node
/**
 * Core-only plugin catalog sync: signed ZIPs under resources/plugin-packages/
 * plus plugin-catalog.json with relative url entries (no plugin-seed trees).
 *
 * Delegates packing/signing to pack_signed_plugin_catalog.py so HMAC format
 * matches core.plugins.signing.write_signed_zip.
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const script = path.join(__dirname, 'pack_signed_plugin_catalog.py')

const runners = [
  ['conda', ['run', '--no-capture-output', '-n', 'Stella', 'python', script]],
  ['python3', [script]],
  ['python', [script]],
]

let last = null
for (const [cmd, args] of runners) {
  const result = spawnSync(cmd, args, { stdio: 'inherit', env: process.env })
  last = result
  if (result.error && result.error.code === 'ENOENT') continue
  if (result.status === 0) process.exit(0)
  process.exit(result.status ?? 1)
}

console.error('failed to run pack_signed_plugin_catalog.py (conda/python missing)')
process.exit(last?.status ?? 1)
