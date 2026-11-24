const path = require('node:path');
const fs = require('node:fs');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, shell, dialog } = require('electron');
const { PAGES, normalizeNode, originOf, sameOrigin, homeTarget, lanTarget, awayTarget } = require('./node');
const { createRouter } = require('./route');
const { certDecision, formatFingerprint } = require('./pin');
const { createStore, exportText, importText } = require('./store');

const SIDEBAR = 300;
const HEADER = 48;

app.setName('Node Controller');

const userData = process.env.NODECONTROLLER_DATA || app.getPath('userData');
if (process.env.NODECONTROLLER_DATA) app.setPath('userData', userData);
const store = createStore(path.join(userData, 'nodes.json'));
let nodes = store.load();
const router = createRouter();
const refused = new Map();

function plainOrigins() {
  const out = new Set();
  for (const n of nodes) {
    for (const page of PAGES) {
      for (const t of [homeTarget(n, page), lanTarget(n, page), awayTarget(n, page)]) {
        if (t && !t.https) out.add(originOf(t));
      }
    }
  }
  return [...out];
}

const insecure = plainOrigins();
if (insecure.length) app.commandLine.appendSwitch('unsafely-treat-insecure-origin-as-secure', insecure.join(','));

let win = null;
let view = null;
let current = null;
let overlay = false;

function fromShell(e) {
  return win && !win.isDestroyed() && e.sender === win.webContents;
}

function emit(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function layout() {
  if (!win || win.isDestroyed() || !view) return;
  const [w, h] = win.getContentSize();
  view.setBounds({ x: SIDEBAR, y: HEADER, width: Math.max(0, w - SIDEBAR), height: Math.max(0, h - HEADER) });
}

function applyVisibility() {
  if (view) view.setVisible(!overlay && !(current && current.failed));
}

function externalOpen(url) {
  try {
    const u = new URL(url);
    if (u.protocol === 'http:' || u.protocol === 'https:') shell.openExternal(u.toString());
  } catch {
    return;
  }
}

function nodeSession(node) {
  return session.fromPartition(`persist:node-${node.id}`);
}

function closePage() {
  if (view && win && !win.isDestroyed()) {
    win.contentView.removeChildView(view);
    view.webContents.close();
  }
  view = null;
  current = null;
}

async function openPage(nodeId, pageId) {
  const node = nodes.find((n) => n.id === nodeId);
  const page = PAGES.find((p) => p.id === pageId);
  if (!node || !page) return { ok: false, message: 'That page is not available.' };
  closePage();
  const target = await router.pick(node, page);
  const ses = nodeSession(node);
  view = new WebContentsView({
    webPreferences: { session: ses, sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  win.contentView.addChildView(view);
  current = { nodeId, pageId, via: target.via, origin: originOf(target), failed: false };
  layout();
  applyVisibility();
  const wc = view.webContents;
  wc.setWindowOpenHandler(({ url }) => {
    externalOpen(url);
    return { action: 'deny' };
  });
  wc.on('will-navigate', (e, url) => {
    if (!sameOrigin(url, target)) {
      e.preventDefault();
      externalOpen(url);
    }
  });
  wc.on('certificate-error', (event, url, error, certificate, callback) => {
    let hostname = '';
    try {
      hostname = new URL(url).hostname.replace(/^\[|\]$/g, '');
    } catch {
      hostname = '';
    }
    const d = certDecision({ hostname, certPem: certificate && certificate.data }, nodes);
    if (d.refused) refused.set(d.refused.hostname, d.refused);
    event.preventDefault();
    callback(d.trust);
  });
  wc.on('did-fail-load', (e, code, desc, url, isMain) => {
    if (!isMain || code === -3 || !current) return;
    router.forget(node.id);
    current.failed = true;
    applyVisibility();
    const hit = refused.get(target.host.toLowerCase());
    const cert = hit && target.via !== 'away' ? { fingerprint: formatFingerprint(hit.fingerprint), raw: hit.fingerprint } : null;
    emit('page:error', { nodeId, pageId, code, message: desc, cert, via: target.via });
  });
  wc.on('did-finish-load', () => {
    if (current && !current.failed) emit('page:loaded', { nodeId, pageId, via: target.via });
  });
  wc.loadURL(`${originOf(target)}/`);
  return { ok: true, via: target.via, origin: current.origin };
}

function snapshot() {
  return nodes.map((n) => ({ ...n }));
}

function persist() {
  store.save(nodes);
}

function register() {
  ipcMain.handle('app:info', (e) => (fromShell(e) ? { version: app.getVersion(), pages: PAGES } : null));
  ipcMain.handle('nodes:list', (e) => (fromShell(e) ? snapshot() : []));
  ipcMain.handle('nodes:save', (e, raw) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = normalizeNode(raw);
    if (!r.node) return { error: r.error };
    const i = nodes.findIndex((n) => n.id === r.node.id);
    if (i >= 0) {
      nodes[i] = r.node;
      router.forget(r.node.id);
    } else {
      nodes.push(r.node);
    }
    persist();
    return { node: r.node, nodes: snapshot() };
  });
  ipcMain.handle('nodes:remove', async (e, id) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    if (current && current.nodeId === id) closePage();
    nodes = nodes.filter((n) => n.id !== id);
    router.forget(id);
    persist();
    try {
      await session.fromPartition(`persist:node-${id}`).clearStorageData();
    } catch {
      return { nodes: snapshot() };
    }
    return { nodes: snapshot() };
  });
  ipcMain.handle('nodes:export', async (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = await dialog.showSaveDialog(win, {
      defaultPath: 'nodecontroller-nodes.json',
      filters: [{ name: 'JSON', extensions: ['json'] }],
    });
    if (r.canceled || !r.filePath) return { canceled: true };
    fs.writeFileSync(r.filePath, exportText(nodes));
    return { path: r.filePath };
  });
  ipcMain.handle('nodes:import', async (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = await dialog.showOpenDialog(win, { properties: ['openFile'], filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled || !r.filePaths.length) return { canceled: true };
    let text;
    try {
      text = fs.readFileSync(r.filePaths[0], 'utf8');
    } catch {
      return { error: 'That file could not be read.' };
    }
    const res = importText(nodes, text);
    if (res.error) return res;
    nodes = res.nodes;
    for (const n of nodes) router.forget(n.id);
    persist();
    return { nodes: snapshot(), added: res.added, replaced: res.replaced, skipped: res.skipped };
  });
  ipcMain.handle('page:open', (e, nodeId, pageId) => (fromShell(e) ? openPage(nodeId, pageId) : { ok: false }));
  ipcMain.handle('page:reload', (e) => {
    if (!fromShell(e) || !current) return { ok: false };
    router.forget(current.nodeId);
    return openPage(current.nodeId, current.pageId);
  });
  ipcMain.handle('page:close', (e) => {
    if (fromShell(e)) closePage();
    return { ok: true };
  });
  ipcMain.handle('ui:overlay', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    overlay = Boolean(on);
    applyVisibility();
    return { ok: true };
  });
  ipcMain.handle('cert:trust', (e, nodeId, fingerprint) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return { error: 'That node is gone.' };
    const want = String(fingerprint || '').toLowerCase().replace(/[^0-9a-f]/g, '');
    const hit = [...refused.values()].find((r) => r.fingerprint === want && r.nodeIds.includes(nodeId));
    if (!hit) return { error: 'That certificate was not the one refused.' };
    node.pin = hit.fingerprint;
    refused.delete(hit.hostname);
    router.forget(nodeId);
    persist();
    return { nodes: snapshot() };
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 760,
    minHeight: 480,
    title: 'Node Controller',
    backgroundColor: '#14171c',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
  win.on('resize', layout);
  win.on('closed', () => {
    win = null;
    view = null;
    current = null;
  });
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  register();
  createWindow();
});

app.on('window-all-closed', () => app.quit());
