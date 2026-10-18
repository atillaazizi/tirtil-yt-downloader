const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('atiAPI', {
  // Window state (macOS native traffic lights handle min/max/close)
  onWindowStateChange: (callback) => {
    ipcRenderer.on('window-state-changed', (_e, state) => callback(state));
  },

  // File system & shell
  pickFolder: (defaultPath) => ipcRenderer.invoke('pick-folder', defaultPath),
  pickTxtFile: () => ipcRenderer.invoke('pick-txt-file'),
  openFolder: (targetPath) => ipcRenderer.invoke('open-folder', targetPath),
  openLogs: () => ipcRenderer.invoke('open-logs'),
  openExternalUrl: (url) => ipcRenderer.invoke('open-external-url', url),

  // Engine actions
  getInitialState: () => ipcRenderer.invoke('get-initial-state'),
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),
  clearCache: () => ipcRenderer.invoke('clear-cache'),
  startDownload: (config) => ipcRenderer.invoke('start-download', config),
  cancelDownload: () => ipcRenderer.invoke('cancel-download'),

  // Real-time engine event stream
  onEngineEvent: (callback) => {
    ipcRenderer.on('engine-event', (_e, data) => callback(data));
  }
});
