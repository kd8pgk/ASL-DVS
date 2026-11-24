const path = require('node:path');
const fs = require('node:fs');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, shell, dialog } = require('electron');
const { PAGES, normalizeNode, originOf, sameOrigin, homeTarget, lanTarget, awayTarget, matchPage } = require('./node');
const { createRouter } = require('./route');
const { certDecision, formatFingerprint } = require('./pin');
const { createStore, exportText, importText } = require('./store');
const L = require('./layout');
const P = require('./policy');
const PR = require('./presets');

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
const presetStore = PR.createPresetStore(path.join(userData, 'splits.json'));
let splits = presetStore.load();
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
const partitions = new Map();
const LH_PARTITION = 'lasthard';

function nodeOfPartition(ses) {
  const hit = [...partitions].find(([, v]) => v === ses);
  return hit ? nodes.find((n) => n.id === hit[0]) : null;
}

function allNodeHosts() {
  return nodes.flatMap((n) => P.hostsOfNode(n));
}

function nodeSession(node) {
  const ses = session.fromPartition(`persist:node-${node.id}`);
  partitions.set(node.id, ses);
  harden(ses, 'node');
  return ses;
}

function lastHeardSession() {
  const ses = session.fromPartition(LH_PARTITION);
  harden(ses, 'lh');
  return ses;
}

function harden(ses, kind) {
  if (hardened.has(ses)) return;
  hardened.add(ses);
  const hostsFor = () => {
    const n = kind === 'node' ? nodeOfPartition(ses) : null;
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
    let ok;
    if (kind === 'node') ok = P.allowRequest(details.url, hostsFor());
    else if (kind === 'lh') ok = P.allowLastHeardRequest(details.url, allNodeHosts());
    else ok = P.allowShellRequest(details.url);
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

function gridNow() {
  const [w, h] = win.getContentSize();
  return L.grid(w, h);
}

function area() {
  return gridNow().area;
}

function emitNotice(text, bad) {
  if (alive()) win.webContents.send('notice', { text, bad: Boolean(bad) });
}

function labelOf(tab) {
  if (tab.kind === 'lh') return 'Last Heard';
  const n = nodes.find((x) => x.id === tab.nodeId);
  const p = PAGES.find((x) => x.id === tab.pageId);
  return `${n ? n.name || n.host : '?'} · ${p ? p.label : '?'}`;
}

function shortLabel(key) {
  const t = ls.tabs.find((x) => x.key === key);
  if (!t) return '';
  if (t.kind === 'lh') return 'Last Heard';
  const p = PAGES.find((x) => x.id === t.pageId);
  return p ? p.label : t.pageId;
}

function payload() {
  const g = gridNow();
  const r = L.rects(ls, g.area);
  const list = L.paneList(ls);
  const vis = list.map((p) => p.key);
  const pageOf = (t) => PAGES.find((x) => x.id === t.pageId);
  return {
    grid: { sidebar: g.sidebar, header: g.header, strip: g.strip },
    view: ls.view,
    ratio: ls.ratio,
    focus: ls.focus,
    canSplit: L.canSplit(ls),
    canBack: L.canBack(ls),
    canSave: L.SLOTS.reduce((n, sl) => n + ls.slots[sl].length, 0) >= 2,
    splits: splits.map((p) => ({ id: p.id, name: p.name, count: PR.count(p) })),
    zones: L.dropZones(g.area),
    overlay,
    slots: L.SLOTS.map((sl) => ({
      slot: sl,
      label: L.SLOT_LABEL[sl],
      pages: ls.slots[sl].map((k) => ({ key: k, label: labelOf(ls.tabs.find((t) => t.key === k)), selected: ls.sel[sl] === k })),
    })),
    tabs: ls.tabs.map((t) => {
      const e = rt.get(t.key);
      const pg = pageOf(t);
      return {
        key: t.key,
        nodeId: t.nodeId,
        pageId: t.pageId,
        kind: t.kind || 'page',
        label: labelOf(t),
        slot: L.slotOf(ls, t.key),
        singleOnly: Boolean(pg && pg.single),
        shown: vis.includes(t.key),
        focused: vis.includes(t.key) && L.focusedKey(ls) === t.key,
        status: e ? e.status : 'idle',
        idle: e ? e.idle === true : true,
        via: e ? e.via : 'home',
      };
    }),
    panes: list.map((p, i) => {
      const e = rt.get(p.key);
      const rect = r.panes[i];
      return {
        slot: p.slot,
        key: p.key,
        rect,
        view: L.viewRect(ls, rect),
        label: labelOf(ls.tabs.find((t) => t.key === p.key)),
        stack: p.slot ? ls.slots[p.slot].map((k) => ({ key: k, label: shortLabel(k), selected: k === p.key })) : [],
        status: e ? e.status : 'loading',
        error: e && e.status === 'failed' ? e.error : null,
      };
    }),
    strips: list.length >= 2,
    dividers: r.dividers,
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

function setIdle(e, idle) {
  if (!e.view || e.idle === idle) return;
  const wc = e.view.webContents;
  if (wc.isDestroyed()) return;
  e.idle = idle;
  wc.setBackgroundThrottling(idle);
  wc.setAudioMuted(idle);
}

function sync() {
  if (!alive()) return;
  const r = L.rects(ls, area());
  const vis = L.shown(ls);
  for (const key of vis) if (key) ensureView(key);
  for (const [key, e] of rt) {
    if (!e.view) continue;
    const i = vis.indexOf(key);
    const tab = ls.tabs.find((t) => t.key === key);
    setIdle(e, i < 0 && !(tab && P.neverIdle(tab.pageId)));
    if (i >= 0 && r.panes[i]) {
      const p = L.viewRect(ls, r.panes[i]);
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
  const key = L.focusedKey(ls);
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

function openLink(url) {
  const m = matchPage(url, nodes);
  if (!m) {
    externalOpen(url);
    return;
  }
  update(L.openTab(ls, m.nodeId, m.pageId));
  focusView();
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
  const key = L.focusedKey(ls);
  if (k === '1') {
    update(L.setView(ls, 'single'));
  } else if (k === '2') {
    update(L.setView(ls, 'slots'));
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

function openLastHeard(nodeId, url) {
  if (!P.lastHeardOk(url, allNodeHosts())) {
    emitNotice('That Last Heard address was refused: only web addresses on the public internet, or on one of your nodes, are opened here.', true);
    return;
  }
  const had = ls.tabs.find((t) => t.key === L.LH_KEY);
  ls = L.openLastHeard(ls, nodeId, url);
  if (had && had.url !== url) closeRt(L.LH_KEY);
  sync();
  focusView();
}

async function ensureLastHeard(key, tab) {
  const e = { view: null, status: 'loading', error: null, via: 'home', origin: '' };
  rt.set(key, e);
  const view = new WebContentsView({
    webPreferences: {
      session: lastHeardSession(),
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
    const next = L.focusKey(ls, key);
    if (next !== ls) {
      ls = next;
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
    if (!P.lastHeardOk(url, allNodeHosts())) {
      ev.preventDefault();
      emitNotice('The Last Heard page tried to go somewhere that is not allowed.', true);
    }
  });
  wc.on('certificate-error', (event, url, error, certificate, callback) => {
    event.preventDefault();
    callback(false);
  });
  wc.on('did-fail-load', (ev, code, desc, url, isMain) => {
    if (!isMain || code === -3 || rt.get(key) !== e) return;
    e.status = 'failed';
    e.error = { message: desc, code, via: 'home', nodeId: tab.nodeId, cert: null };
    sync();
  });
  wc.on('did-finish-load', () => {
    if (rt.get(key) === e && e.status === 'loading') {
      e.status = 'ok';
      push();
    }
  });
  wc.loadURL(tab.url);
  sync();
}

async function ensureView(key) {
  if (rt.has(key)) return;
  const tab = ls.tabs.find((t) => t.key === key);
  if (tab && tab.kind === 'lh') {
    await ensureLastHeard(key, tab);
    return;
  }
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
    const next = L.focusKey(ls, key);
    if (next !== ls) {
      ls = next;
      push();
      saveSoon();
    }
  };
  wc.on('focus', focused);
  wc.on('input-event', (ev, input) => {
    if (input && input.type === 'mouseDown') focused();
  });
  wc.setWindowOpenHandler(({ url, frameName }) => {
    if (P.isLastHeardWindow(page.id, frameName)) openLastHeard(node.id, url);
    else openLink(url);
    return { action: 'deny' };
  });
  wc.on('will-navigate', (ev, url) => {
    if (!sameOrigin(url, target)) {
      ev.preventDefault();
      openLink(url);
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
    if (changed) for (const t of ls.tabs) if (t.nodeId === r.node.id && t.kind !== 'lh') closeRt(t.key);
    sync();
    return { node: r.node, nodes: snapshot() };
  });
  ipcMain.handle('nodes:remove', async (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    for (const t of ls.tabs) if (t.nodeId === id) closeRt(t.key);
    ls = L.closeNode(ls, id);
    nodes = nodes.filter((n) => n.id !== id);
    splits = splits.filter((p) => !L.SLOTS.some((sl) => p.slots[sl].some((it) => it.nodeId === id)));
    presetStore.save(splits);
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
  const resolveKey = (arg) => {
    if (!arg || typeof arg !== 'object') return null;
    if (str(arg.key)) return ls.tabs.some((t) => t.key === arg.key) ? arg.key : null;
    if (str(arg.nodeId) && str(arg.pageId) && nodes.some((n) => n.id === arg.nodeId) && PAGES.some((p) => p.id === arg.pageId)) {
      ls = L.addTab(ls, arg.nodeId, arg.pageId);
      return L.keyOf(arg.nodeId, arg.pageId);
    }
    return null;
  };
  ipcMain.handle('tabs:drop', (e, arg) => {
    if (!fromShell(e) || !arg || !str(arg.slot)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.putInSlot(ls, key, arg.slot));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:next', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.addNext(ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:alone', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.showAlone(ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:unslot', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.unslot(ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:view', (e, view) => {
    if (fromShell(e) && str(view)) {
      update(L.setView(ls, view));
      focusView();
    }
    return { ok: true };
  });
  ipcMain.handle('splits:save', (e, name) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const made = PR.fromState(ls, name);
    if (made.error) return { error: made.error };
    const r = PR.put(splits, made.preset);
    if (r.error) return { error: r.error };
    splits = r.list;
    presetStore.save(splits);
    push();
    return { ok: true };
  });
  ipcMain.handle('splits:apply', (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    const preset = splits.find((p) => p.id === id);
    if (!preset) return { error: 'That split is gone.' };
    const r = PR.apply(ls, preset, nodes, PAGES);
    if (r.error) return { error: r.error };
    update(r.state);
    focusView();
    return { ok: true };
  });
  ipcMain.handle('splits:remove', (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    splits = splits.filter((p) => p.id !== id);
    presetStore.save(splits);
    push();
    return { ok: true };
  });
  ipcMain.handle('tabs:ratio', (e, ratio) => {
    if (fromShell(e)) update(L.setRatio(ls, ratio));
    return { ok: true };
  });
  ipcMain.handle('tabs:focus', (e, slot) => {
    if (fromShell(e) && str(slot)) {
      update(L.focusSlot(ls, slot));
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
    for (const t of ls.tabs) if (t.nodeId === nodeId && t.kind !== 'lh') closeRt(t.key);
    sync();
    return { nodes: snapshot() };
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1100,
    minHeight: 700,
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
  harden(session.defaultSession, 'shell');
  register();
  createWindow();
});

app.on('before-quit', () => {
  if (saveTimer) saveNow();
});

app.on('window-all-closed', () => app.quit());
