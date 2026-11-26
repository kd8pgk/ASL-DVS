const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { app, BrowserWindow, WebContentsView, Menu, session, shell, screen } = require('electron');
const { PAGES, flipDecision, otherScheme, originOf, sameOrigin, homeTarget, lanTarget, awayTarget, matchPage } = require('./node');
const { createRouter } = require('./route');
const { createMonitor } = require('./status');
const { createSessionMarker } = require('./session');
const { createLog } = require('./diag');
const LN = require('./launcher');
const { certDecision, formatFingerprint, refusedKey, refusedKeyOfUrl } = require('./pin');
const { createStore } = require('./store');
const L = require('./layout');
const P = require('./policy');
const PR = require('./presets');
const { buildPayload } = require('./payload');
const { createSessions } = require('./sessions');
const { registerIpc } = require('./ipc');

const S = { ls: null, nodes: [], splits: [], win: null, overlay: false };

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
S.splits = presetStore.load();
S.nodes = store.load();
const router = createRouter();
const refused = new Map();
const flips = new Map();
const confirmed = new Set();
const rt = new Map();
const probeMs = !app.isPackaged && Number(process.env.NODECONTROLLER_PROBE_MS) >= 100 ? Number(process.env.NODECONTROLLER_PROBE_MS) : undefined;
const monitor = createMonitor({
  getNodes: () => S.nodes,
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
S.ls = crashedLast ? L.emptyState() : L.restore(readJson(layoutFile), S.nodes, INTERNAL);
if (crashedLast) {
  try {
    fs.unlinkSync(layoutFile);
  } catch {
    S.ls = L.emptyState();
  }
}
const startupNotice = crashedLast
  ? 'The app closed unexpectedly last time, so it started with no pages open. Your nodes, saved splits and trusted certificates are kept.'
  : '';

function plainOrigins() {
  const out = new Set();
  for (const n of S.nodes) {
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

const SES = createSessions({ session, getNodes: () => S.nodes, log: (t) => logLine(t) });
const { nodeSession, lastHeardSession, harden, allNodeHosts } = SES;
const lhOk = (url) => P.lastHeardOk(url, allNodeHosts());
S.ls = L.dropLastHeard(S.ls, (t) => lhOk(t.url));

S.win = null;
S.overlay = false;
let saveTimer = null;

function alive() {
  return S.win && !S.win.isDestroyed();
}

function fromShell(e) {
  return alive() && e.sender === S.win.webContents;
}

function gridNow() {
  const [w, h] = S.win.getContentSize();
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
  if (alive()) S.win.webContents.send('notice', { text, bad: Boolean(bad) });
}

function payload() {
  return buildPayload({ ls: S.ls, nodes: S.nodes, splits: S.splits, rt, grid: gridNow(), down: monitor.snapshot().down, overlay: S.overlay, restart: needsRestart() });
}

function push() {
  if (alive()) S.win.webContents.send('layout', payload());
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
    fs.writeFileSync(tmp, JSON.stringify(L.serialize(S.ls)));
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
  const list = L.paneList(S.ls);
  const i = list.findIndex((p) => p.key === key);
  if (i < 0) return { w: 0, h: 0 };
  return L.viewRect(S.ls, L.rects(S.ls, area()).panes[i]);
}

function zoomKey(key, op) {
  if (!key || !S.ls.tabs.some((t) => t.key === key)) return;
  const v = viewRectOf(key);
  if (op === 'fit') S.ls = L.fitZoom(S.ls, key);
  else if (op === 'in' || op === 'out') S.ls = L.stepZoom(S.ls, key, op === 'in' ? 1 : -1, v.w, v.h);
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
  const r = L.rects(S.ls, area());
  const vis = L.shown(S.ls);
  for (const key of vis) if (key) ensureView(key);
  for (const [key, e] of rt) {
    if (!e.view) continue;
    const i = vis.indexOf(key);
    const tab = S.ls.tabs.find((t) => t.key === key);
    setIdle(e, i < 0 && !(tab && P.neverIdle(tab.pageId)));
    if (i >= 0 && r.panes[i]) {
      const p = L.viewRect(S.ls, r.panes[i]);
      e.view.setBounds({ x: p.x, y: p.y, width: p.w, height: p.h });
      e.zoom = L.zoomFor(S.ls, key, p.w, p.h);
      applyScale(e, p);
      e.view.setVisible(!S.overlay && e.status !== 'failed');
    } else {
      e.view.setVisible(false);
    }
  }
  push();
  saveSoon();
}

function update(next) {
  S.ls = next;
  sync();
}

function focusView() {
  const key = L.focusedKey(S.ls);
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
  const node = S.nodes.find((n) => n.id === nodeId);
  const page = PAGES.find((p) => p.id === pageId);
  if (!node || !page || !page.external) return false;
  const target = await router.pick(node, page);
  externalOpen(`${originOf(target)}/`);
  emitNotice(`${page.label} on ${node.name || node.host} opened in your web browser.`, false);
  return true;
}

function openLink(url) {
  const m = matchPage(url, S.nodes);
  const pg = m && PAGES.find((p) => p.id === m.pageId);
  if (!m || (pg && pg.external)) {
    externalOpen(url);
    return;
  }
  update(L.openTab(S.ls, m.nodeId, m.pageId));
  focusView();
}

function closeRt(key) {
  const e = rt.get(key);
  rt.delete(key);
  if (e && e.view) {
    if (alive()) S.win.contentView.removeChildView(e.view);
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
  const key = L.focusedKey(S.ls);
  if (k === '1') {
    update(L.setView(S.ls, 'single'));
  } else if (k === '2') {
    update(L.setView(S.ls, 'slots'));
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
  } else if (k === 'tab' && S.ls.tabs.length > 1) {
    const i = S.ls.tabs.findIndex((t) => t.key === key);
    const step = shift ? -1 : 1;
    update(L.openKey(S.ls, S.ls.tabs[(i + step + S.ls.tabs.length) % S.ls.tabs.length].key));
    focusView();
  }
}

function openLastHeard(nodeId, frameUrl) {
  const parts = P.splitLastHeardName(frameUrl);
  if (!lhOk(parts.url)) {
    emitNotice('That Last Heard address was refused: only web addresses on the public internet, or on one of your nodes, are opened here.', true);
    return;
  }
  const name = P.lastHeardName(parts.url, parts.name);
  closeRt(L.lhKey(name));
  S.ls = L.openLastHeard(S.ls, nodeId, parts.url, name);
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
  S.win.contentView.addChildView(view);
  const wc = view.webContents;
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('before-input-event', onKey);
  const focused = () => {
    const next = L.focusKey(S.ls, key);
    if (next !== S.ls) {
      S.ls = next;
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
  const tab = S.ls.tabs.find((t) => t.key === key);
  if (tab && tab.kind === 'lh') {
    await ensureLastHeard(key, tab);
    return;
  }
  const node = tab && S.nodes.find((n) => n.id === tab.nodeId);
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
    const d = certDecision({ hostname, certPem: certificate && certificate.data }, S.nodes);
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
      const idx = S.nodes.findIndex((n) => n.id === node.id);
      if (idx >= 0 && decision === 'flip') {
        const now = target.https ? 'https' : 'http';
        const next = otherScheme(now);
        S.nodes[idx].schemes = { ...S.nodes[idx].schemes, [page.id]: next };
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
        S.nodes[idx].schemes = { ...S.nodes[idx].schemes, [page.id]: last.from };
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
  update(L.closeTab(S.ls, key));
  focusView();
}

function reloadTab(key) {
  const tab = S.ls.tabs.find((t) => t.key === key);
  if (!tab) return;
  closeRt(key);
  router.forget(tab.nodeId);
  sync();
  focusView();
}

function snapshot() {
  return S.nodes.map((n) => ({ ...n }));
}

function persist() {
  store.save(S.nodes);
}

const { runningAppImage, launcherPaths } = LN.launcherEnv({ packaged: app.isPackaged, env: process.env, home: os.homedir() });

function createWindow() {
  const size = L.windowSize(screen.getPrimaryDisplay().workAreaSize);
  S.win = new BrowserWindow({
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
  S.win.webContents.on('before-input-event', onKey);
  S.win.webContents.on('will-navigate', (e) => e.preventDefault());
  S.win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  if (size.maximize) S.win.maximize();
  S.win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
  S.win.webContents.on('did-fail-load', (e, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    process.stderr.write(`Failed to load the window: ${desc}\n`);
    app.exit(3);
  });
  S.win.webContents.once('did-finish-load', () => sync());
  S.win.on('resize', sync);
  S.win.webContents.on('render-process-gone', (ev, details) => {
    logLine(`window process gone: reason=${details.reason} exit=${details.exitCode}`);
    if (alive()) S.win.webContents.reload();
  });
  S.win.on('close', () => logLine('window closed by the user or the system'));
  S.win.on('closed', () => {
    S.win = null;
    rt.clear();
  });
}

app.on('web-contents-created', (e, contents) => {
  contents.on('will-attach-webview', (ev) => ev.preventDefault());
});

app.on('second-instance', () => {
  if (S.win && !S.win.isDestroyed()) {
    if (S.win.isMinimized()) S.win.restore();
    S.win.focus();
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
  registerIpc({
    S, SES, INTERNAL, refused, router, monitor, presetStore, startupNotice,
    fromShell, payload, persist, push, sync, update, focusView, closeRt, closeTab, reloadTab, zoomKey,
    snapshot, emitNotice, openExternalPage, logLine, launcherPaths, runningAppImage, lhOk,
  });
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
