/**
 * electron-builder afterPack hook.
 *
 * The Python backend is a PyInstaller onedir bundle shipped via extraResources
 * into Contents/Resources/backend/. electron-builder's deep signing does NOT
 * cover extraResources, so its executable + hundreds of .so/.dylib files stay
 * unsigned — which makes notarization reject the whole app.
 *
 * This hook runs before electron-builder signs the .app: it code-signs every
 * Mach-O file under the backend dir with hardened runtime + entitlements, so
 * the outer app signature and notarization succeed.
 */
const { execFileSync, execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

exports.default = async function signBackend(context) {
  const { electronPlatformName, appOutDir, packager } = context
  if (electronPlatformName !== 'darwin') return

  // Signing identity comes from CSC_NAME (set in CI and, for local builds,
  // your shell). No identity => unsigned build (e.g. dry runs), so skip the
  // backend signing rather than fail.
  const cscName = process.env.CSC_NAME
  if (!cscName) {
    console.log('[sign-backend] CSC_NAME not set — unsigned build, skipping backend signing')
    return
  }

  // Resolve CSC_NAME to a certificate SHA-1 hash. In CI electron-builder
  // imports the cert into a temporary keychain (not login.keychain), so
  // matching by name is unreliable — `codesign` may not find it. The SHA-1 is
  // unambiguous and works across the whole keychain search list.
  //
  // `security find-identity -v -p codesigning` searches every keychain on the
  // user search list (including the temp one electron-builder registers) and
  // prints lines like:  1) <SHA1>  "Developer ID Application: ... (TEAMID)"
  let identity = cscName
  try {
    const idList = execFileSync(
      'security',
      ['find-identity', '-v', '-p', 'codesigning'],
      { encoding: 'utf8' }
    )
    for (const line of idList.split('\n')) {
      const m = line.match(/\)\s+([0-9A-F]{40})\s+"(.+)"/i)
      if (m && m[2] === cscName) {
        identity = m[1]
        break
      }
    }
  } catch (e) {
    console.warn('[sign-backend] could not resolve identity hash, falling back to name')
  }
  console.log(`[sign-backend] using signing identity: ${identity}`)

  const appName = packager.appInfo.productFilename
  const backendDir = path.join(
    appOutDir,
    `${appName}.app`,
    'Contents',
    'Resources',
    'backend'
  )

  if (!fs.existsSync(backendDir)) {
    console.log(`[sign-backend] no backend dir at ${backendDir}, skipping`)
    return
  }

  const entitlements = path.join(__dirname, 'entitlements.mac.plist')

  // Collect every Mach-O file (executables + dylibs/so) under backend/.
  // `file` output contains "Mach-O" for native binaries.
  const files = []
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const full = path.join(dir, name)
      const stat = fs.lstatSync(full)
      if (stat.isSymbolicLink()) continue
      if (stat.isDirectory()) {
        walk(full)
        continue
      }
      try {
        const out = execSync(`file -b "${full}"`, { encoding: 'utf8' })
        if (out.includes('Mach-O')) files.push(full)
      } catch {
        // ignore unreadable entries
      }
    }
  }
  walk(backendDir)

  console.log(`[sign-backend] signing ${files.length} Mach-O files under backend/`)

  // Sign inner libraries first, then the main executable last (inside-out).
  files.sort((a, b) => b.length - a.length)

  for (const f of files) {
    execFileSync(
      'codesign',
      [
        '--force',
        '--timestamp',
        '--options',
        'runtime',
        '--entitlements',
        entitlements,
        '--sign',
        identity,
        f,
      ],
      { stdio: 'inherit' }
    )
  }

  console.log('[sign-backend] backend signing complete')
}
