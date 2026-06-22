import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  selectFile: (filters?: Electron.FileFilter[]) => ipcRenderer.invoke('select-file', filters),

  onBackendStatus: (callback: (data: { status: string; port?: number; error?: string }) => void) => {
    ipcRenderer.on('backend-status', (_event, data) => callback(data))
  },

  onBackendLog: (callback: (line: string) => void) => {
    ipcRenderer.on('backend-log', (_event, line) => callback(line))
  },

  // Window controls (custom titlebar on Windows)
  windowMinimize: () => ipcRenderer.invoke('window-minimize'),
  windowMaximize: () => ipcRenderer.invoke('window-maximize'),
  windowClose: () => ipcRenderer.invoke('window-close'),
  windowIsMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onMaximizeChange: (callback: (maximized: boolean) => void) => {
    ipcRenderer.on('window-maximize-changed', (_event, max) => callback(max))
  },

  // App menu / shortcut actions forwarded from the main process.
  onMenuAction: (callback: (action: string) => void) => {
    ipcRenderer.on('menu-action', (_event, action: string) => callback(action))
  },

  platform: process.platform,
})
