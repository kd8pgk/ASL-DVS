const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nb', {
  state: () => ipcRenderer.invoke('state'),
  go: (text) => ipcRenderer.invoke('go', text),
  nav: (what) => ipcRenderer.invoke('nav', what),
  allowHttp: () => ipcRenderer.invoke('allow-http'),
  trustCert: () => ipcRenderer.invoke('trust-cert'),
  fileAnswer: (id, open) => ipcRenderer.invoke('file-answer', id, open),
  allowSite: () => ipcRenderer.invoke('allow-site'),
  dismissPopup: () => ipcRenderer.invoke('dismiss-popup'),
  importBookmarks: () => ipcRenderer.invoke('import-bookmarks'),
  removeBookmark: (id) => ipcRenderer.invoke('remove-bookmark', id),
  requestFastJs: (on) => ipcRenderer.invoke('request-fast-js', on),
  cancelFastJs: () => ipcRenderer.invoke('cancel-fast-js'),
  confirmFastJs: () => ipcRenderer.invoke('confirm-fast-js'),
  lineSet: (key, value) => ipcRenderer.invoke('line-set', key, value),
  stopImages: () => ipcRenderer.invoke('stop-images'),
  onState: (cb) => ipcRenderer.on('state', (e, s) => cb(s)),
  onFocusAddress: (cb) => ipcRenderer.on('focus-address', () => cb()),
});
