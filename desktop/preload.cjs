const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktop', Object.freeze({
  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: values => ipcRenderer.invoke('settings:save', values),
  exportNote: (id, format) => ipcRenderer.invoke('note:export', { id, format }),
  backup: () => ipcRenderer.invoke('library:backup'),
  previewRestore: () => ipcRenderer.invoke('library:restore-preview'),
  restore: preview => ipcRenderer.invoke('library:restore', preview),
  activateRestored: directory => ipcRenderer.invoke('library:activate-restored', directory),
  chooseLibrary: () => ipcRenderer.invoke('library:choose'),
  revealData: () => ipcRenderer.invoke('library:reveal'),
  openOriginal: id => ipcRenderer.invoke('source:open', id),
}));
