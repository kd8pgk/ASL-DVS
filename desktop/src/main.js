const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, shell, dialog, screen } = require('electron');
const { PAGES, MAX_PINS, flipDecision, otherScheme, normalizeNode, originOf, sameOrigin, homeTarget, lanTarget, awayTarget, matchPage } = require('./node');
const { createRouter } = require('./route');
const { createMonitor } = require('./status');
const { createSessionMarker } = require('./session');
const { createLog } = require('./diag');
const LN = require('./launcher');
const { certDecision, formatFingerprint, refusedKey, refusedKeyOfUrl } = require('./pin');
const { createStore, exportText, importText } = require('./store');
const L = require('./layout');
const P = require('./policy');
const PR = require('./presets');

const CONNECTION_FIELDS = ['host', 'https', 'schemes', 'ports', 'pins', 'lanIp', 'awayHost', 'awayPort', 'awayHttps'];
const FLIP_WINDOW_MS = 30000;

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
const primary = app.requestSingleInstanceLock();
if (!primary) app.exit(0);
const marker = createSessionMarker(path.join(userData, 'running.json'));
const crashedLast = primary ? marker.begin().crashed : false;
const store = createStore(path.join(userData, 'nodes.json'));
const layoutFile = path.join(userData, 'layout.json');
const presetStore = PR.createPresetStore(path.join(userData, 'splits.json'));
let splits = presetStore.load();
let nodes = store.load();
const router = createRouter();
const refused = new Map();
const flips = new Map();
const confirmed = new Set();
const rt = new Map();
const probeMs = !app.isPackaged && Number(process.env.NODECONTROLLER_PROBE_MS) >= 100 ? Number(process.env.NODECONTROLLER_PROBE_MS) : undefined;
const monitor = createMonitor({
  getNodes: () => nodes,
  getPages: () => PAGES,
  onChange: () => push(),
  interval: probeMs,
});

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

const INTERNAL = PAGES.filter((p) => !p.external);
let ls = crashedLast ? L.emptyState() : L.restore(readJson(layoutFile), nodes, INTERNAL);
if (crashedLast) {
  try {
    fs.unlinkSync(layoutFile);
  } catch {
    ls = L.emptyState();
  }
}
let startupNotice = crashedLast
  ? 'The app closed unexpectedly last time, so it started with no pages open. Your nodes, saved splits and trusted certificates are kept.'
  : '';

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
const securedAtStart = new Set(insecure);
let restartLogged = false;

function needsRestart() {
  const need = plainOrigins().some((o) => !securedAtStart.has(o));
  if (need && !restartLogged) {
    restartLogged = true;
    logLine('a page on plain http was added: a restart lets it use the microphone and clipboard');
  }
  return need;
}

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

const refusedSeen = new Set();

function logRefused(kind, permission) {
  const k = `${kind}:${permission}`;
  if (refusedSeen.has(k)) return;
  refusedSeen.add(k);
  logLine(`permission refused: ${permission} (${kind} pages)`);
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
    const media = permission === 'media' && details ? details.mediaTypes : undefined;
    const ok = P.allowPermission(permission, origin, hostsFor(), media);
    if (!ok) logRefused(kind, permission);
    callback(ok);
  });
  ses.setPermissionCheckHandler((wc, permission, origin, details) => {
    const media = permission === 'media' && details ? details.mediaType : undefined;
    const ok = P.allowPermission(permission, origin, hostsFor(), media);
    if (!ok) logRefused(kind, permission);
    return ok;
  });
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
let shellReady = false;
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

const diag = createLog(path.join(userData, 'diagnostics.log'));

function logLine(text) {
  diag.write(text);
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
  const zoomOf = {};
  list.forEach((p, i) => {
    const v = L.viewRect(ls, r.panes[i]);
    zoomOf[p.key] = L.zoomFor(ls, p.key, v.w, v.h);
  });
  return {
    grid: { sidebar: g.sidebar, header: g.header, strip: g.strip },
    view: ls.view,
    ratio: ls.ratio,
    focus: ls.focus,
    down: monitor.snapshot().down,
    canSplit: L.canSplit(ls),
    canBack: L.canBack(ls),
    canSave: L.SLOTS.reduce((n, sl) => n + ls.slots[sl].length, 0) >= 2,
    splits: splits.map((p) => ({ id: p.id, name: p.name, count: PR.count(p) })),
    zones: L.dropZones(g.area),
    overlay,
    restart: needsRestart(),
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
        zoom: zoomOf[t.key] === undefined ? 1 : zoomOf[t.key],
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
        zoom: zoomOf[p.key],
        zoomSet: ls.zooms[p.key] !== undefined,
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

function applyScale(e, rect) {
  if (!e.view) return;
  const wc = e.view.webContents;
  if (wc.isDestroyed()) return;
  const z = e.zoom;
  const tag = z === 1 ? 'off' : `${rect.w}x${rect.h}@${z}`;
  if (e.emu === tag) return;
  e.emu = tag;
  if (z === 1) {
    wc.disableDeviceEmulation();
    return;
  }
  const vw = Math.max(1, Math.round(rect.w / z));
  const vh = Math.max(1, Math.round(rect.h / z));
  wc.enableDeviceEmulation({
    screenPosition: 'desktop',
    screenSize: { width: vw, height: vh },
    viewPosition: { x: 0, y: 0 },
    viewSize: { width: vw, height: vh },
    deviceScaleFactor: 0,
    scale: z,
  });
}

function viewRectOf(key) {
  const list = L.paneList(ls);
  const i = list.findIndex((p) => p.key === key);
  if (i < 0) return { w: 0, h: 0 };
  return L.viewRect(ls, L.rects(ls, area()).panes[i]);
}

function zoomKey(key, op) {
  if (!key || !ls.tabs.some((t) => t.key === key)) return;
  const v = viewRectOf(key);
  if (op === 'fit') ls = L.fitZoom(ls, key);
  else if (op === 'in' || op === 'out') ls = L.stepZoom(ls, key, op === 'in' ? 1 : -1, v.w, v.h);
  else return;
  sync();
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
      e.zoom = L.zoomFor(ls, key, p.w, p.h);
      applyScale(e, p);
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
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return;
    if (!app.isPackaged && process.env.NODECONTROLLER_EXTERNAL_LOG) {
      fs.appendFileSync(process.env.NODECONTROLLER_EXTERNAL_LOG, `${u.toString()}\n`);
      return;
    }
    shell.openExternal(u.toString());
  } catch {
    return;
  }
}

async function openExternalPage(nodeId, pageId) {
  const node = nodes.find((n) => n.id === nodeId);
  const page = PAGES.find((p) => p.id === pageId);
  if (!node || !page || !page.external) return false;
  const target = await router.pick(node, page);
  externalOpen(`${originOf(target)}/`);
  emitNotice(`${page.label} on ${node.name || node.host} opened in your web browser.`, false);
  return true;
}

function openLink(url) {
  const m = matchPage(url, nodes);
  const pg = m && PAGES.find((p) => p.id === m.pageId);
  if (!m || (pg && pg.external)) {
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
  const shift = Boolean(input.shift);
  if (!['1', '2', 'w', '=', '+', '-', '0', 'r', 'tab'].includes(k)) return;
  event.preventDefault();
  setImmediate(() => runKey(k, shift));
}

function runKey(k, shift) {
  const key = L.focusedKey(ls);
  if (k === '1') {
    update(L.setView(ls, 'single'));
  } else if (k === '2') {
    update(L.setView(ls, 'slots'));
  } else if (k === 'w' && key) {
    closeTab(key);
  } else if ((k === '=' || k === '+') && key) {
    zoomKey(key, 'in');
  } else if (k === '-' && key) {
    zoomKey(key, 'out');
  } else if (k === '0' && key) {
    zoomKey(key, 'fit');
  } else if (k === 'r' && key) {
    reloadTab(key);
  } else if (k === 'tab' && ls.tabs.length > 1) {
    const i = ls.tabs.findIndex((t) => t.key === key);
    const step = shift ? -1 : 1;
    update(L.openKey(ls, ls.tabs[(i + step + ls.tabs.length) % ls.tabs.length].key));
    focusView();
  }
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

function makeView(key, e, ses, { via, nodeId, onOk }) {
  const view = new WebContentsView({
    webPreferences: {
      session: ses,
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
  wc.on('did-finish-load', () => {
    if (rt.get(key) === e && e.status === 'loading') {
      e.status = 'ok';
      if (onOk) onOk();
      push();
    }
  });
  wc.on('render-process-gone', (ev, details) => {
    logLine(`page process gone: ${key} reason=${details.reason} exit=${details.exitCode}`);
    if (rt.get(key) !== e) return;
    e.status = 'failed';
    e.error = { message: `The page stopped working (${details.reason}). Try again to reload it.`, code: 0, via, nodeId, cert: null };
    sync();
  });
  return wc;
}

async function ensureLastHeard(key, tab) {
  const e = { view: null, status: 'loading', error: null, via: 'home', origin: '' };
  rt.set(key, e);
  const wc = makeView(key, e, lastHeardSession(), { via: 'home', nodeId: tab.nodeId });
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
    logLine(`load failed: ${key} ${desc} (${code}) ${url}`);
    e.status = 'failed';
    e.error = { message: desc, code, via: 'home', nodeId: tab.nodeId, cert: null };
    sync();
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
  const wc = makeView(key, e, nodeSession(node), {
    via: target.via,
    nodeId: node.id,
    onOk: () => {
      flips.delete(key);
      confirmed.add(`${key} ${originOf(target)}`);
    },
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
    if (d.refused) {
      const rk = refusedKeyOfUrl(url);
      refused.set(rk, { ...d.refused, key: rk });
    }
    event.preventDefault();
    callback(d.trust);
  });
  wc.on('did-fail-load', (ev, code, desc, url, isMain) => {
    if (!isMain || code === -3 || rt.get(key) !== e) return;
    logLine(`load failed: ${key} ${desc} (${code}) ${url} via=${target.via} scheme=${target.https ? 'https' : 'http'}`);
    router.forget(node.id);
    const last = flips.get(key);
    const recent = Boolean(last && Date.now() - last.at < FLIP_WINDOW_MS);
    const decision = flipDecision({ code, via: target.via, recent, confirmed: confirmed.has(`${key} ${originOf(target)}`) });
    if (decision !== 'none') {
      const idx = nodes.findIndex((n) => n.id === node.id);
      if (idx >= 0 && decision === 'flip') {
        const now = target.https ? 'https' : 'http';
        const next = otherScheme(now);
        nodes[idx].schemes = { ...nodes[idx].schemes, [page.id]: next };
        persist();
        logLine(`scheme for ${key}: ${now} -> ${next}`);
        flips.set(key, { at: Date.now(), from: now });
        emitNotice(`${page.label} on ${node.name || node.host} answers on ${next}, not ${now}. That is what will be used for it from now on.`, false);
        setImmediate(() => {
          if (rt.get(key) !== e) return;
          closeRt(key);
          sync();
        });
        return;
      }
      if (idx >= 0 && decision === 'revert') {
        nodes[idx].schemes = { ...nodes[idx].schemes, [page.id]: last.from };
        persist();
        logLine(`scheme for ${key}: back to ${last.from}, the other one failed too`);
        flips.delete(key);
      }
    }
    const hit = refused.get(refusedKey(target.host, target.port, target.https));
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
  wc.loadURL(`${originOf(target)}/`).catch(() => {});
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

function runningAppImage() {
  if (app.isPackaged) return process.env.APPIMAGE || '';
  return process.env.NODECONTROLLER_TEST_APPIMAGE || '';
}

function homeDir() {
  if (!app.isPackaged && process.env.NODECONTROLLER_TEST_HOME) return process.env.NODECONTROLLER_TEST_HOME;
  return os.homedir();
}

function desktopDir() {
  const home = homeDir();
  const conf = process.env.XDG_CONFIG_HOME && path.isAbsolute(process.env.XDG_CONFIG_HOME) ? process.env.XDG_CONFIG_HOME : path.join(home, '.config');
  let text = '';
  try {
    text = fs.readFileSync(path.join(conf, 'user-dirs.dirs'), 'utf8');
  } catch {
    text = '';
  }
  return LN.desktopDirFrom(home, text);
}

function launcherPaths() {
  return LN.launcherPaths(homeDir(), desktopDir());
}

function register() {
  const str = (v) => typeof v === 'string';
  ipcMain.handle('app:info', (e) => (fromShell(e) ? { version: app.getVersion(), pages: PAGES } : null));
  ipcMain.handle('layout:get', (e) => {
    if (!fromShell(e)) return null;
    if (!shellReady) {
      shellReady = true;
      process.stderr.write('shell-ready\n');
      if (startupNotice) {
        const text = startupNotice;
        startupNotice = '';
        setTimeout(() => emitNotice(text, true), 400);
      }
    }
    return payload();
  });
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
    monitor.refresh();
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
    monitor.refresh();
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
    try {
      fs.writeFileSync(r.filePath, exportText(nodes));
    } catch (err) {
      logLine(`export failed: ${err && err.code ? err.code : err}`);
      return { error: 'The node list could not be written there. Pick another folder.' };
    }
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
    monitor.refresh();
    return { nodes: snapshot(), added: res.added, replaced: res.replaced, skipped: res.skipped };
  });
  ipcMain.handle('tabs:open', (e, nodeId, pageId) => {
    if (!fromShell(e) || !str(nodeId) || !str(pageId)) return { ok: false };
    if (!nodes.some((n) => n.id === nodeId) || !PAGES.some((p) => p.id === pageId)) return { ok: false };
    if (PAGES.find((p) => p.id === pageId).external) {
      openExternalPage(nodeId, pageId);
      return { ok: true };
    }
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
    if (str(arg.nodeId) && str(arg.pageId) && nodes.some((n) => n.id === arg.nodeId) && INTERNAL.some((p) => p.id === arg.pageId)) {
      ls = L.addTab(ls, arg.nodeId, arg.pageId);
      return L.keyOf(arg.nodeId, arg.pageId);
    }
    return null;
  };
  ipcMain.handle('tabs:drop', (e, arg) => {
    if (!fromShell(e) || !arg || !str(arg.slot) || !L.SLOTS.includes(arg.slot)) return { ok: false };
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
  ipcMain.handle('tabs:zoom', (e, arg) => {
    if (!fromShell(e) || !arg || !str(arg.op)) return { ok: false };
    zoomKey(str(arg.key) ? arg.key : L.focusedKey(ls), arg.op);
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
    const r = PR.apply(ls, preset, nodes, INTERNAL);
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
  ipcMain.handle('app:restart', (e) => {
    if (!fromShell(e)) return { ok: false };
    logLine('restarting at the user\'s request');
    if (process.env.APPIMAGE) app.relaunch({ execPath: process.env.APPIMAGE, args: process.argv.slice(1) });
    else app.relaunch();
    app.quit();
    return { ok: true };
  });
  ipcMain.handle('launcher:status', (e) => (fromShell(e) ? LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) : null));
  ipcMain.handle('launcher:install', (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    let r;
    try {
      let icon = null;
      try {
        icon = fs.readFileSync(path.join(__dirname, '..', 'ui', 'icon.png'));
      } catch {
        icon = null;
      }
      r = LN.installLauncher({ paths: launcherPaths(), running: runningAppImage(), iconPng: icon, version: app.getVersion() });
    } catch (err) {
      logLine(`launcher install failed: ${err && err.code ? err.code : err}`);
      return { error: 'The launcher could not be added. See diagnostics.log.' };
    }
    if (r.error) return r;
    logLine(`launcher added${r.shortcut ? ' with a desktop icon' : ''}`);
    return { ok: true, shortcut: Boolean(r.shortcut), status: LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) };
  });
  ipcMain.handle('launcher:remove', (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    LN.removeLauncher({ paths: launcherPaths() });
    logLine('launcher removed');
    return { ok: true, status: LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) };
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
    node.pins = [...node.pins.filter((p) => p !== hit.fingerprint), hit.fingerprint].slice(-MAX_PINS);
    for (const [k, r] of refused) if (r.fingerprint === hit.fingerprint) refused.delete(k);
    router.forget(nodeId);
    persist();
    for (const t of ls.tabs) if (t.nodeId === nodeId && t.kind !== 'lh') closeRt(t.key);
    sync();
    return { nodes: snapshot() };
  });
}

function createWindow() {
  const size = L.windowSize(screen.getPrimaryDisplay().workAreaSize);
  win = new BrowserWindow({
    width: size.width,
    height: size.height,
    minWidth: size.minWidth,
    minHeight: size.minHeight,
    center: true,
    title: 'Node Controller Desktop',
    backgroundColor: '#0d1117',
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
  if (size.maximize) win.maximize();
  win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
  win.webContents.on('did-fail-load', (e, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    process.stderr.write(`Failed to load the window: ${desc}\n`);
    app.exit(3);
  });
  win.webContents.once('did-finish-load', () => sync());
  win.on('resize', sync);
  win.webContents.on('render-process-gone', (ev, details) => {
    logLine(`window process gone: reason=${details.reason} exit=${details.exitCode}`);
    if (alive()) win.webContents.reload();
  });
  win.on('close', () => logLine('window closed by the user or the system'));
  win.on('closed', () => {
    win = null;
    rt.clear();
  });
}

app.on('web-contents-created', (e, contents) => {
  contents.on('will-attach-webview', (ev) => ev.preventDefault());
});

app.on('second-instance', () => {
  if (win && !win.isDestroyed()) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => {
    app.quit();
    setTimeout(() => process.exit(0), 3000).unref();
  });
}

app.whenReady().then(() => {
  if (crashedLast) logLine('the last run did not exit cleanly: the open pages were not restored');
  if (P.sandboxOff(process.argv.slice(1)) || app.commandLine.hasSwitch('no-sandbox')) {
    logLine('WARNING: running without the Chromium sandbox (--no-sandbox). The AppImage turns it off by itself when this system does not allow unprivileged user namespaces; the pages are less isolated from this computer than they should be.');
  }
  Menu.setApplicationMenu(null);
  harden(session.defaultSession, 'shell');
  register();
  createWindow();
  monitor.start();
});

app.on('child-process-gone', (ev, details) => {
  logLine(`helper process gone: type=${details.type} name=${details.name || ''} reason=${details.reason} exit=${details.exitCode}`);
});

process.on('uncaughtException', (err) => {
  logLine(`error in the main process: ${err && err.stack ? err.stack : err}`);
});

process.on('unhandledRejection', (err) => {
  logLine(`unhandled promise rejection: ${err && err.stack ? err.stack : err}`);
});

app.on('before-quit', () => {
  logLine('quitting');
  marker.end();
  monitor.stop();
  if (saveTimer) saveNow();
});

app.on('window-all-closed', () => app.quit());
