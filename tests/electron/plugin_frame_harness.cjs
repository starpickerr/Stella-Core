// R03 runtime harness: opens the *real* openPluginFrame() (compiled from
// desktop/src/main/plugin-frame.ts) in Electron and reports what the plugin page
// can actually see. Run via tests/test_plugin_frame_electron.py; prints one JSON
// line prefixed with "G5_RESULT " on stdout.
//
// env: STELLA_FRAME_JS (compiled plugin-frame.js), STELLA_FRAME_USER_DATA (temp dir)
const http = require('http')
const path = require('path')
const { app, BrowserWindow } = require('electron')

const frameJs = process.env.STELLA_FRAME_JS
const userData = process.env.STELLA_FRAME_USER_DATA
if (!frameJs || !userData) {
  console.error('STELLA_FRAME_JS and STELLA_FRAME_USER_DATA are required')
  app.exit(2)
}
app.setPath('userData', userData)
app.disableHardwareAcceleration()

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>window.__inlineRan = true;</script>
<script src="/probe.js"></script></body></html>`

// External same-origin script (allowed by script-src 'self').
const PROBE = `
window.__violations = [];
document.addEventListener('securitypolicyviolation', (e) => window.__violations.push(e.violatedDirective));
(async () => {
  const r = {};
  r.requireType = typeof require;
  r.processType = typeof process;
  r.moduleType = typeof module;
  r.BufferType = typeof Buffer;
  r.inlineScriptRan = window.__inlineRan === true;
  try {
    const resp = await fetch('/probe.js');
    r.cspHeader = resp.headers.get('content-security-policy');
  } catch (e) { r.cspHeaderError = String(e); }
  try {
    await fetch('http://example.invalid/x', { mode: 'no-cors' });
    r.foreignFetch = 'allowed';
  } catch (e) { r.foreignFetch = 'blocked'; }
  try { r.evalAllowed = !!eval('1+1'); } catch (e) { r.evalAllowed = false; }
  window.__probe = r;
})();
`

const server = http.createServer((req, res) => {
  if (req.url === '/probe.js') {
    res.writeHead(200, { 'content-type': 'application/javascript' })
    res.end(PROBE)
  } else {
    res.writeHead(200, { 'content-type': 'text/html' })
    res.end(PAGE)
  }
})

function finish(result, code) {
  console.log('G5_RESULT ' + JSON.stringify(result))
  server.close()
  app.exit(code)
}

app.whenReady().then(() => {
  server.listen(0, '127.0.0.1', async () => {
    const port = server.address().port
    try {
      const { openPluginFrame } = require(path.resolve(frameJs))
      const parent = new BrowserWindow({ show: false })
      const child = openPluginFrame({
        pluginId: 'g5.harness',
        pageId: 'main',
        channelNonce: 'nonce',
        resourceUrl: `http://127.0.0.1:${port}/index.html`,
        parent
      })
      const prefs = child.webContents.getLastWebPreferences()
      await new Promise((resolve, reject) => {
        child.webContents.once('did-finish-load', resolve)
        child.webContents.once('did-fail-load', (_e, code, desc) => reject(new Error(desc)))
      })
      let probe = null
      for (let i = 0; i < 50 && !probe; i++) {
        probe = await child.webContents.executeJavaScript('window.__probe || null')
        if (!probe) await new Promise((r) => setTimeout(r, 100))
      }
      const violations = await child.webContents.executeJavaScript('window.__violations')

      // Navigation / popup hardening (R03): foreign navigations and window.open must be denied.
      const allowedOrigin = `http://127.0.0.1:${port}/`
      let navigatedAway = false
      child.webContents.on('did-navigate', (_e, url) => {
        if (!url.startsWith(allowedOrigin) && !url.startsWith('file:')) {
          navigatedAway = true
        }
      })
      // Attempt foreign navigation; will-navigate handler should prevent it.
      await child.webContents.executeJavaScript(
        'void location.assign("https://example.invalid/escape")'
      )
      await new Promise((r) => setTimeout(r, 300))
      const urlAfterNav = child.webContents.getURL()

      // window.open must be denied by setWindowOpenHandler.
      const openResult = await child.webContents.executeJavaScript(
        '(() => { const w = window.open("https://example.invalid/popup"); return w ? "opened" : "denied"; })()'
      )

      finish(
        {
          prefs: {
            sandbox: prefs.sandbox,
            nodeIntegration: prefs.nodeIntegration,
            contextIsolation: prefs.contextIsolation,
            webSecurity: prefs.webSecurity,
            preload: prefs.preload || null
          },
          probe,
          violations,
          identity: child.__stellaPluginIdentity || null,
          navigation: {
            urlAfterForeignAssign: urlAfterNav,
            navigatedAway,
            windowOpen: openResult
          }
        },
        probe ? 0 : 3
      )
    } catch (e) {
      finish({ error: String(e && e.stack ? e.stack : e) }, 1)
    }
  })
})
