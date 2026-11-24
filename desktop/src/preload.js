const { contextBridge, ipcRenderer } = require('electron');

function listen(channel, cb) {
  const fn = (e, payload) => cb(payload);
  ipcRenderer.on(channel, fn);
  return () => ipcRenderer.removeListener(channel, fn);
}

contextBridge.exposeInMainWorld('nc', {
  info: () => ipcRenderer.invoke('app:info'),
  listNodes: () => ipcRenderer.invoke('nodes:list'),
  saveNode: (raw) => ipcRenderer.invoke('nodes:save', raw),
  removeNode: (id) => ipcRenderer.invoke('nodes:remove', id),
  exportNodes: () => ipcRenderer.invoke('nodes:export'),
  importNodes: () => ipcRenderer.invoke('nodes:import'),
  openPage: (nodeId, pageId) => ipcRenderer.invoke('page:open', nodeId, pageId),
  reloadPage: () => ipcRenderer.invoke('page:reload'),
  closePage: () => ipcRenderer.invoke('page:close'),
  overlay: (on) => ipcRenderer.invoke('ui:overlay', on),
  trustCert: (nodeId, fingerprint) => ipcRenderer.invoke('cert:trust', nodeId, fingerprint),
  onPageError: (cb) => listen('page:error', cb),
  onPageLoaded: (cb) => listen('page:loaded', cb),
});
