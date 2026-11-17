const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('atiAPI', {
  getInitialState: () => ipcRenderer.invoke('get-initial-state'),
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),
  pickFolder: (defaultPath) => ipcRenderer.invoke('pick-folder', defaultPath),
  pickTxtFile: () => ipcRenderer.invoke('pick-txt-file'),
  openFolder: (targetPath) => ipcRenderer.invoke('open-folder', targetPath),
  openLogs: () => ipcRenderer.invoke('open-logs'),
  startDownload: (config) => ipcRenderer.invoke('start-download', config),
  cancelDownload: () => ipcRenderer.invoke('cancel-download'),
  checkUpdates: () => ipcRenderer.invoke('check-updates'),
  onUpdateStatus: (callback) => {
    ipcRenderer.on('update-status', (_e, data) => callback(data));
  },
  onEngineEvent: (callback) => {
    ipcRenderer.on('engine-event', (_e, data) => callback(data));
  }
});
