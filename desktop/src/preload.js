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
  getLayout: () => ipcRenderer.invoke('layout:get'),
  openTab: (nodeId, pageId) => ipcRenderer.invoke('tabs:open', nodeId, pageId),
  activateTab: (key) => ipcRenderer.invoke('tabs:activate', key),
  closeTab: (key) => ipcRenderer.invoke('tabs:close', key),
  reloadTab: (key) => ipcRenderer.invoke('tabs:reload', key),
  dropTab: (arg) => ipcRenderer.invoke('tabs:drop', arg),
  addNext: (arg) => ipcRenderer.invoke('tabs:next', arg),
  showAlone: (arg) => ipcRenderer.invoke('tabs:alone', arg),
  removePane: (i) => ipcRenderer.invoke('tabs:remove-pane', i),
  backToSplit: () => ipcRenderer.invoke('tabs:back'),
  saveSplit: (name) => ipcRenderer.invoke('splits:save', name),
  applySplit: (id) => ipcRenderer.invoke('splits:apply', id),
  removeSplit: (id) => ipcRenderer.invoke('splits:remove', id),
  setMode: (mode) => ipcRenderer.invoke('tabs:mode', mode),
  setRatio: (ratio) => ipcRenderer.invoke('tabs:ratio', ratio),
  focusPane: (i) => ipcRenderer.invoke('tabs:focus', i),
  overlay: (on) => ipcRenderer.invoke('ui:overlay', on),
  trustCert: (nodeId, fingerprint) => ipcRenderer.invoke('cert:trust', nodeId, fingerprint),
  onLayout: (cb) => listen('layout', cb),
  onNotice: (cb) => listen('notice', cb),
});
