import { app, Tray, Menu, BrowserWindow, nativeImage } from 'electron'

let tray: Tray | null = null

interface TrayDeps {
  getWindow: () => BrowserWindow | null
  // Colored icon used on Windows/Linux trays.
  iconPath?: string
  // Monochrome (black + alpha) template icon for the macOS menu bar; renders
  // correctly in both light and dark menu bars when set as a template image.
  templateIconPath?: string
  // Called when the user picks "Quit" so the app can fully exit.
  onQuit: () => void
}

// Build a system tray icon with a minimal menu. The tray lets users restore the
// window after closing it to the background and start a new chat quickly.
export function createTray({ getWindow, iconPath, templateIconPath, onQuit }: TrayDeps): Tray | null {
  if (tray) return tray

  const isMac = process.platform === 'darwin'
  // Prefer the monochrome template icon on macOS (menu-bar convention).
  const sourcePath = isMac && templateIconPath ? templateIconPath : iconPath
  if (!sourcePath) return null

  let image = nativeImage.createFromPath(sourcePath)
  if (image.isEmpty()) return null
  // Tray icons render small; resize to avoid an oversized image on some platforms.
  image = image.resize({ width: 18, height: 18 })
  // A template image must be pure black + alpha; macOS then auto-inverts it for
  // light/dark menu bars. Only mark it as such when we actually loaded the
  // dedicated template asset (a colored icon as template would render as a blob).
  if (isMac && templateIconPath) image.setTemplateImage(true)

  tray = new Tray(image)
  tray.setToolTip(app.name)

  const showWindow = () => {
    const win = getWindow()
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show CowAgent', click: showWindow },
    {
      label: 'New Chat',
      click: () => {
        showWindow()
        getWindow()?.webContents.send('menu-action', 'new-chat')
      },
    },
    { type: 'separator' },
    { label: 'Quit', click: onQuit },
  ])
  tray.setContextMenu(contextMenu)

  // Single click restores the window (common Windows/Linux behavior).
  tray.on('click', showWindow)

  return tray
}

export function destroyTray() {
  tray?.destroy()
  tray = null
}
