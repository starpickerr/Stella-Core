/**
 * Dynamic electron-builder config for WINDOWS code signing.
 *
 * Mirrors electron-builder.js (which handles mac.binaries) but for Windows.
 * It wires the Racent remote code-signing CLI into electron-builder so that
 * every produced .exe (the app launcher + the NSIS installer) is signed in the
 * cloud — the EV private key never leaves the CA's HSM, satisfying the post-2023
 * "private key must live in hardware" rule.
 *
 * Two signing passes are needed:
 *   1. win.signtoolOptions.sign (customSign) — electron-builder calls this for
 *      each artifact it produces (app .exe, uninstaller, NSIS installer).
 *   2. afterPack — signs the PyInstaller backend (cowagent-backend.exe) that is
 *      copied in via extraResources. electron-builder's sign hook only touches
 *      its OWN outputs, so the nested backend exe must be signed here, BEFORE
 *      the installer is assembled, so the signed backend ends up inside it.
 *
 * VENDOR PRIVACY: the CLI path and all credentials come from env vars only.
 * Nothing in this file (or the public workflow) names the reseller, so a public
 * repo never leaks which signing vendor we use.
 *
 * DRY-RUN / SKIP: when SIGNTOOL_CERT_CODE is absent we skip signing entirely
 * (unsigned dev/dry builds keep working). When COW_SIGN_DRY_RUN=1 we pass
 * --dry-run so the WHOLE pipeline can be validated in CI with a self-signed
 * cert, WITHOUT a real certificate and WITHOUT consuming any signing quota.
 */
const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const config = require('./package.json').build

// Absolute path to the Racent signtool CLI on the runner. Injected by CI so
// this file never hardcodes a vendor download URL. e.g. C:\signtool\signtool.exe
const SIGNTOOL = process.env.SIGNTOOL_PATH || ''
const ACCESS_KEY = process.env.SIGNTOOL_ACCESS_KEY || ''
const ACCESS_SECRET = process.env.SIGNTOOL_ACCESS_SECRET || ''
const CERT_CODE = process.env.SIGNTOOL_CERT_CODE || ''
// Dry-run validates the pipeline with a self-signed cert (no quota, no real
// cert needed). Any truthy value enables it.
const DRY_RUN = !!process.env.COW_SIGN_DRY_RUN

// RFC3161 timestamp server for SHA256. Microsoft's is reliable from CI runners
// worldwide; overridable via env if needed.
const TIMESTAMP = process.env.SIGNTOOL_TIMESTAMP || 'http://timestamp.acs.microsoft.com'

// Signing is possible when we have the CLI plus either a real cert code or
// explicit dry-run mode (dry-run accepts placeholder credentials).
function canSign() {
  if (!SIGNTOOL || !fs.existsSync(SIGNTOOL)) return false
  if (DRY_RUN) return true
  return !!(ACCESS_KEY && ACCESS_SECRET && CERT_CODE)
}

/**
 * Sign a single file in place using the Racent CLI. The CLI writes to a
 * separate --out path (it refuses to overwrite an existing file), so we sign to
 * a temp file and atomically move it back over the original.
 */
function signFile(filePath) {
  const tmpOut = `${filePath}.signed`
  // Remove a stale temp from a previous failed run (CLI errors if --out exists).
  try {
    if (fs.existsSync(tmpOut)) fs.rmSync(tmpOut)
  } catch {
    /* ignore */
  }

  const args = [
    'sign',
    ...(DRY_RUN ? ['--dry-run'] : []),
    `--access-key=${ACCESS_KEY}`,
    `--access-secret=${ACCESS_SECRET}`,
    `--cert-code=${CERT_CODE}`,
    `--file=${filePath}`,
    `--out=${tmpOut}`,
    '--sha1=false',
    '--sha2=true',
    '--timestamp-rfc3161',
    TIMESTAMP,
  ]

  // Never print credentials: log only the file being signed.
  console.log(`[win-sign] signing ${path.basename(filePath)}${DRY_RUN ? ' (dry-run)' : ''}`)
  execFileSync(SIGNTOOL, args, { stdio: ['ignore', 'inherit', 'inherit'] })

  if (!fs.existsSync(tmpOut)) {
    throw new Error(`[win-sign] signed output not produced for ${filePath}`)
  }
  // Replace the original with the signed copy.
  fs.rmSync(filePath)
  fs.renameSync(tmpOut, filePath)
}

// electron-builder calls this for each artifact it generates (app exe, NSIS
// installer, uninstaller). Signature: (configuration) => void, where
// configuration.path is the file to sign.
async function customSign(configuration) {
  if (!canSign()) {
    console.warn('[win-sign] signing skipped (no signtool/credentials)')
    return
  }
  signFile(configuration.path)
}

// Recursively collect .exe/.dll under the packed backend dir so nested native
// binaries get signed too (Defender flags PyInstaller bundles most often).
function collectSignables(dir) {
  const out = []
  const walk = (d) => {
    for (const name of fs.readdirSync(d)) {
      const full = path.join(d, name)
      const st = fs.lstatSync(full)
      if (st.isSymbolicLink()) continue
      if (st.isDirectory()) {
        walk(full)
        continue
      }
      if (/\.(exe|dll)$/i.test(name)) out.push(full)
    }
  }
  walk(dir)
  return out
}

// Sign the PyInstaller backend BEFORE the installer is built, so the signed
// backend is what gets packaged. context.appOutDir is the unpacked app dir.
async function afterPack(context) {
  if (process.platform !== 'win32') return
  if (!canSign()) return
  const backendDir = path.join(context.appOutDir, 'resources', 'backend', 'cowagent-backend')
  if (!fs.existsSync(backendDir)) {
    console.warn(`[win-sign] backend dir not found, skipping backend signing: ${backendDir}`)
    return
  }
  const files = collectSignables(backendDir)
  console.log(`[win-sign] signing ${files.length} backend binaries`)
  for (const f of files) signFile(f)
}

// Extend the base config: attach the sign hook + afterPack. Only meaningful on
// Windows builds (this config is only passed via --config on the win matrix leg).
config.win = { ...config.win, signtoolOptions: { sign: customSign, signingHashAlgorithms: ['sha256'] } }
config.afterPack = afterPack

module.exports = config
