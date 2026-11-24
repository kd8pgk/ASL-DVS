const path = require('node:path');
const fs = require('node:fs');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, shell, dialog } = require('electron');
const { PAGES, normalizeNode, originOf, sameOrigin, homeTarget, lanTarget, awayTarget } = require('./node');
const { createRouter } = require('./route');
const { certDecision, formatFingerprint } = require('./pin');
const { createStore, exportText, importText } = require('./store');
const L = require('./layout');
const P = require('./policy');

const SIDEBAR = 300;
const HEADER = 48;
const CONNECTION_FIELDS = ['host', 'https', 'ports', 'pin', 'lanIp', 'lanPin', 'awayHost', 'awayPort', 'awayHttps'];

app.setName('Node Controller');

if (app.isPackaged) {
  const bad = P.unsafeSwitches(process.argv.slice(1));
  if (bad.length) {
    process.stderr.write(`Refused: --${bad.join(', --')} is not allowed in this build.\n`);
    app.exit(2);
  }
}

app.commandLine.appendSwitch('disable-features', P.DISABLED_FEATURES.join(','));
for (const sw of P.SWITCHES) app.commandLine.appendSwitch(sw);

const userData = process.env.NODECONTROLLER_DATA || app.getPath('userData');
if (process.env.NODECONTROLLER_DATA) app.setPath('userData', userData);
const store = createStore(path.join(userData, 'nodes.json'));
const layoutFile = path.join(userData, 'layout.json');
let nodes = store.load();
const router = createRouter();
const refused = new Map();
const rt = new Map();

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

let ls = L.restore(readJson(layoutFile), nodes, PAGES);

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

const hardened = new WeakSet();

function nodeOfPartition(ses) {
  const hit = [...partitions].find(([, s]) => s === ses);
  return hit ? nodes.find((n) => n.id === hit[0]) : null;
}

const partitions = new Map();

function nodeSession(node) {
  const name = `persist:node-${node.id}`;
  const ses = session.fromPartition(name);
  partitions.set(node.id, ses);
  harden(ses, true);
  return ses;
}

function harden(ses, forNode) {
  if (hardened.has(ses)) return;
  hardened.add(ses);
  const hostsFor = () => {
    const n = forNode ? nodeOfPartition(ses) : null;
    return n ? P.hostsOfNode(n) : [];
  };
  ses.setPermissionRequestHandler((wc, permission, callback, details) => {
    const origin = (details && details.requestingUrl) || (wc && !wc.isDestroyed() ? wc.getURL() : '');
    callback(P.allowPermission(permission, origin, hostsFor(), details && details.mediaTypes));
  });
  ses.setPermissionCheckHandler((wc, permission, origin, details) =>
    P.allowPermission(permission, origin, hostsFor(), details && details.mediaType));
  ses.setDevicePermissionHandler(() => false);
  ses.setSpellCheckerEnabled(false);
  ses.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
    const ok = forNode ? P.allowRequest(details.url, hostsFor()) : P.allowShellRequest(details.url);
    callback({ cancel: !ok });
  });
}

let win = null;
let overlay = false;
let saveTimer = null;

function alive() {
  return win && !win.isDestroyed();
}

function fromShell(e) {
  return alive() && e.sender === win.webContents;
}

function area() {
  const [w, h] = win.getContentSize();
  return { x: SIDEBAR, y: HEADER, w: Math.max(0, w - SIDEBAR), h: Math.max(0, h - HEADER) };
}

function labelOf(tab) {
  const n = nodes.find((x) => x.id === tab.nodeId);
  const p = PAGES.find((x) => x.id === tab.pageId);
  return `${n ? n.name || n.host : '?'} · ${p ? p.label : '?'}`;
}

function payload() {
  const r = L.rects(ls, area());
  const vis = L.shown(ls);
  return {
    mode: ls.mode,
    ratio: ls.ratio,
    focus: ls.focus,
    canSplit: ls.tabs.length >= 2,
    overlay,
    tabs: ls.tabs.map((t) => {
      const e = rt.get(t.key);
      return {
        key: t.key,
        nodeId: t.nodeId,
        pageId: t.pageId,
        label: labelOf(t),
        shown: vis.indexOf(t.key),
        status: e ? e.status : 'idle',
        via: e ? e.via : 'home',
      };
    }),
    panes: r.panes.map((rect, i) => {
      const key = vis[i];
      const e = key ? rt.get(key) : null;
      return { rect, key, status: e ? e.status : key ? 'loading' : 'empty', error: e && e.status === 'failed' ? e.error : null };
    }),
    divider: r.divider,
  };
}

function push() {
  if (alive()) win.webContents.send('layout', payload());
}

function saveSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 300);
}

function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  try {
    fs.mkdirSync(userData, { recursive: true });
    const tmp = `${layoutFile}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(L.serialize(ls)));
    fs.renameSync(tmp, layoutFile);
  } catch {
    return;
  }
}

function sync() {
  if (!alive()) return;
  const r = L.rects(ls, area());
  const vis = L.shown(ls);
  for (const key of vis) if (key) ensureView(key);
  for (const [key, e] of rt) {
    if (!e.view) continue;
    const i = vis.indexOf(key);
    if (i >= 0 && r.panes[i]) {
      const p = r.panes[i];
      e.view.setBounds({ x: p.x, y: p.y, width: p.w, height: p.h });
      e.view.setVisible(!overlay && e.status !== 'failed');
    } else {
      e.view.setVisible(false);
    }
  }
  push();
  saveSoon();
}

function update(next) {
  ls = next;
  sync();
}

function focusView() {
  const key = L.shown(ls)[ls.focus];
  const e = key ? rt.get(key) : null;
  if (e && e.view && !e.view.webContents.isDestroyed() && e.status !== 'failed') e.view.webContents.focus();
}

function externalOpen(url) {
  try {
    const u = new URL(url);
    if (u.protocol === 'http:' || u.protocol === 'https:') shell.openExternal(u.toString());
  } catch {
    return;
  }
}

function closeRt(key) {
  const e = rt.get(key);
  rt.delete(key);
  if (e && e.view) {
    if (alive()) win.contentView.removeChildView(e.view);
    if (!e.view.webContents.isDestroyed()) e.view.webContents.close();
  }
}

function onKey(event, input) {
  if (input.type !== 'keyDown' || !(input.control || input.meta) || input.alt) return;
  const k = String(input.key).toLowerCase();
  const key = L.shown(ls)[ls.focus];
  if (k === '1' || k === '2' || k === '3') {
    update(L.setMode(ls, L.MODES[Number(k) - 1]));
  } else if (k === 'w' && key) {
    closeTab(key);
  } else if (k === 'r' && key) {
    reloadTab(key);
  } else if (k === 'tab' && ls.tabs.length > 1) {
    const i = ls.tabs.findIndex((t) => t.key === key);
    const step = input.shift ? -1 : 1;
    update(L.openKey(ls, ls.tabs[(i + step + ls.tabs.length) % ls.tabs.length].key));
    focusView();
  } else {
    return;
  }
  event.preventDefault();
}

async function ensureView(key) {
  if (rt.has(key)) return;
  const tab = ls.tabs.find((t) => t.key === key);
  const node = tab && nodes.find((n) => n.id === tab.nodeId);
  const page = tab && PAGES.find((p) => p.id === tab.pageId);
  if (!node || !page) return;
  const e = { view: null, status: 'loading', error: null, via: 'home', origin: '' };
  rt.set(key, e);
  const target = await router.pick(node, page);
  if (rt.get(key) !== e || !alive()) return;
  e.via = target.via;
  e.origin = originOf(target);
  const view = new WebContentsView({
    webPreferences: {
      session: nodeSession(node),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: false,
    },
  });
  e.view = view;
  win.contentView.addChildView(view);
  const wc = view.webContents;
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('before-input-event', onKey);
  const focused = () => {
    const i = L.shown(ls).indexOf(key);
    if (i >= 0 && i !== ls.focus) {
      ls = L.focusPane(ls, i);
      push();
      saveSoon();
    }
  };
  wc.on('focus', focused);
  wc.on('input-event', (ev, input) => {
    if (input && input.type === 'mouseDown') focused();
  });
  wc.setWindowOpenHandler(({ url }) => {
    externalOpen(url);
    return { action: 'deny' };
  });
  wc.on('will-navigate', (ev, url) => {
    if (!sameOrigin(url, target)) {
      ev.preventDefault();
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
  wc.on('did-fail-load', (ev, code, desc, url, isMain) => {
    if (!isMain || code === -3 || rt.get(key) !== e) return;
    router.forget(node.id);
    const hit = refused.get(target.host.toLowerCase());
    e.status = 'failed';
    e.error = {
      message: desc,
      code,
      via: target.via,
      nodeId: node.id,
      cert: hit && target.via !== 'away' ? { fingerprint: formatFingerprint(hit.fingerprint), raw: hit.fingerprint } : null,
    };
    sync();
  });
  wc.on('did-finish-load', () => {
    if (rt.get(key) === e && e.status === 'loading') {
      e.status = 'ok';
      push();
    }
  });
  wc.loadURL(`${originOf(target)}/`);
  sync();
}

function closeTab(key) {
  closeRt(key);
  update(L.closeTab(ls, key));
  focusView();
}

function reloadTab(key) {
  const tab = ls.tabs.find((t) => t.key === key);
  if (!tab) return;
  closeRt(key);
  router.forget(tab.nodeId);
  sync();
  focusView();
}

function snapshot() {
  return nodes.map((n) => ({ ...n }));
}

function persist() {
  store.save(nodes);
}

function register() {
  const str = (v) => typeof v === 'string';
  ipcMain.handle('app:info', (e) => (fromShell(e) ? { version: app.getVersion(), pages: PAGES } : null));
  ipcMain.handle('layout:get', (e) => (fromShell(e) ? payload() : null));
  ipcMain.handle('nodes:list', (e) => (fromShell(e) ? snapshot() : []));
  ipcMain.handle('nodes:save', (e, raw) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = normalizeNode(raw);
    if (!r.node) return { error: r.error };
    const i = nodes.findIndex((n) => n.id === r.node.id);
    let changed = false;
    if (i >= 0) {
      const old = nodes[i];
      changed = CONNECTION_FIELDS.some((f) => JSON.stringify(old[f]) !== JSON.stringify(r.node[f]));
      nodes[i] = r.node;
      router.forget(r.node.id);
    } else {
      nodes.push(r.node);
    }
    persist();
    if (changed) for (const t of ls.tabs) if (t.nodeId === r.node.id) closeRt(t.key);
    sync();
    return { node: r.node, nodes: snapshot() };
  });
  ipcMain.handle('nodes:remove', async (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    for (const t of ls.tabs) if (t.nodeId === id) closeRt(t.key);
    ls = L.closeNode(ls, id);
    nodes = nodes.filter((n) => n.id !== id);
    router.forget(id);
    persist();
    sync();
    try {
      await (partitions.get(id) || session.fromPartition(`persist:node-${id}`)).clearStorageData();
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
    sync();
    return { nodes: snapshot(), added: res.added, replaced: res.replaced, skipped: res.skipped };
  });
  ipcMain.handle('tabs:open', (e, nodeId, pageId) => {
    if (!fromShell(e) || !str(nodeId) || !str(pageId)) return { ok: false };
    if (!nodes.some((n) => n.id === nodeId) || !PAGES.some((p) => p.id === pageId)) return { ok: false };
    update(L.openTab(ls, nodeId, pageId));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:activate', (e, key) => {
    if (!fromShell(e) || !str(key)) return { ok: false };
    update(L.openKey(ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:close', (e, key) => {
    if (fromShell(e) && str(key)) closeTab(key);
    return { ok: true };
  });
  ipcMain.handle('tabs:reload', (e, key) => {
    if (fromShell(e) && str(key)) reloadTab(key);
    return { ok: true };
  });
  ipcMain.handle('tabs:mode', (e, mode) => {
    if (fromShell(e) && str(mode)) update(L.setMode(ls, mode));
    return { ok: true };
  });
  ipcMain.handle('tabs:ratio', (e, ratio) => {
    if (fromShell(e)) update(L.setRatio(ls, ratio));
    return { ok: true };
  });
  ipcMain.handle('tabs:focus', (e, i) => {
    if (fromShell(e)) {
      update(L.focusPane(ls, i));
      focusView();
    }
    return { ok: true };
  });
  ipcMain.handle('ui:overlay', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    overlay = Boolean(on);
    sync();
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
    for (const t of ls.tabs) if (t.nodeId === nodeId) closeRt(t.key);
    sync();
    return { nodes: snapshot() };
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 520,
    title: 'Node Controller',
    backgroundColor: '#14171c',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.webContents.on('before-input-event', onKey);
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
  win.webContents.once('did-finish-load', () => sync());
  win.on('resize', sync);
  win.on('closed', () => {
    win = null;
    rt.clear();
  });
}

app.on('web-contents-created', (e, contents) => {
  contents.on('will-attach-webview', (ev) => ev.preventDefault());
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  harden(session.defaultSession, false);
  register();
  createWindow();
});

app.on('before-quit', () => {
  if (saveTimer) saveNow();
});

app.on('window-all-closed', () => app.quit());
