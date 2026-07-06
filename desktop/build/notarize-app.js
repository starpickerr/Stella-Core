/**
 * electron-builder afterSign hook: notarize the signed .app ourselves.
 *
 * Why not electron-builder's built-in notarize (mac.notarize):
 * it runs `notarytool submit --wait`, which aborts the whole build on ANY
 * network blip during status polling (NSURLErrorDomain -1001 timeout / -1009
 * offline), with no retry — and on failure it re-submits a fresh upload,
 * piling up duplicate submissions. We saw arm64 get "Accepted" yet the build
 * still failed because the poll request dropped.
 *
 * This hook runs after signing and BEFORE the dmg is built, so we:
 *   1. zip the .app with ditto (the payload Apple actually accepts for this
 *      large PyInstaller bundle — submitting the dmg got stuck In Progress),
 *   2. `notarytool submit --no-wait` ONCE to get a submission id,
 *   3. poll that SAME id until Accepted/Invalid — a failed poll (network) is
 *      ignored and retried; we never re-submit,
 *   4. staple the ticket onto the .app; electron-builder then packs the dmg.
 *
 * Requires env: APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID.
 * If they're absent (unsigned/dry build) the hook is a no-op.
 * Tunables: NOTARIZE_MAX_WAIT_MINUTES (default 180), NOTARIZE_POLL_SECONDS (default 30).
 */
const { execFileSync } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

function sh(cmd, args, opts = {}) {
  return execFileSync(cmd, args, { encoding: 'utf8', ...opts })
}

exports.default = async function notarizeApp(context) {
  const { electronPlatformName, appOutDir, packager } = context
  if (electronPlatformName !== 'darwin') return

  const appleId = process.env.APPLE_ID
  const applePassword = process.env.APPLE_APP_SPECIFIC_PASSWORD
  const teamId = process.env.APPLE_TEAM_ID
  if (!appleId || !applePassword || !teamId) {
    console.log('[notarize-app] APPLE_* env not set — skipping notarization')
    return
  }

  const appName = packager.appInfo.productFilename
  const appPath = path.join(appOutDir, `${appName}.app`)
  if (!fs.existsSync(appPath)) {
    console.log(`[notarize-app] no .app at ${appPath}, skipping`)
    return
  }

  const auth = [
    '--apple-id', appleId,
    '--password', applePassword,
    '--team-id', teamId,
  ]

  const maxWaitMin = parseInt(process.env.NOTARIZE_MAX_WAIT_MINUTES || '180', 10)
  const pollSec = parseInt(process.env.NOTARIZE_POLL_SECONDS || '30', 10)

  // 1) zip the .app (ditto preserves symlinks/metadata; --keepParent keeps .app).
  const zipPath = path.join(os.tmpdir(), `${appName}-${context.arch}-notarize.zip`)
  console.log(`[notarize-app] zipping ${appPath} -> ${zipPath}`)
  sh('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zipPath], { stdio: 'inherit' })

  // 2) submit ONCE, no --wait, capture the submission id.
  console.log('[notarize-app] submitting to notary service (no-wait)...')
  const submitOut = sh('xcrun', ['notarytool', 'submit', zipPath, ...auth, '--no-wait', '--output-format', 'json'])
  let submissionId
  try {
    submissionId = JSON.parse(submitOut).id
  } catch (e) {
    throw new Error(`[notarize-app] could not parse submission id:\n${submitOut}`)
  }
  if (!submissionId) throw new Error(`[notarize-app] empty submission id:\n${submitOut}`)
  console.log(`[notarize-app] submission id: ${submissionId} (polling same id, never resubmitting)`)

  // 3) poll the SAME id; a failed poll (network) is ignored and retried.
  const deadline = Date.now() + maxWaitMin * 60 * 1000
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  for (;;) {
    let status = ''
    try {
      const infoOut = sh('xcrun', ['notarytool', 'info', submissionId, ...auth, '--output-format', 'json'])
      status = JSON.parse(infoOut).status || ''
    } catch (e) {
      status = '' // treat query failure as unknown; keep polling
    }
    const ts = new Date().toISOString().slice(11, 19)
    console.log(`[notarize-app] [${ts}] status: ${status || '<query failed, retrying>'}`)

    if (status === 'Accepted') break
    if (status === 'Invalid' || status === 'Rejected') {
      try {
        console.log(sh('xcrun', ['notarytool', 'log', submissionId, ...auth]))
      } catch {}
      throw new Error(`[notarize-app] notarization ${status} (id: ${submissionId})`)
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `[notarize-app] not finished after ${maxWaitMin} min (id: ${submissionId}). ` +
        `NOT resubmitting. Check later: xcrun notarytool info ${submissionId}`
      )
    }
    await sleep(pollSec * 1000)
  }

  // 4) staple the ticket onto the .app (dmg is built afterwards by electron-builder).
  console.log('[notarize-app] Accepted; stapling ticket to .app')
  let stapleTry = 1
  for (;;) {
    try {
      sh('xcrun', ['stapler', 'staple', appPath], { stdio: 'inherit' })
      break
    } catch (e) {
      if (stapleTry >= 3) throw e
      console.log('[notarize-app] staple failed, retrying in 15s...')
      await sleep(15000)
      stapleTry++
    }
  }
  try { fs.unlinkSync(zipPath) } catch {}
  console.log('[notarize-app] notarization + staple complete')
}
