const path = require('node:path');
const crypto = require('node:crypto');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen } = require('electron');
const P = require('./policy');
const R = require('./ram');

app.setName('Null Browser');

if (app.isPackaged) {
  const bad = P.unsafeSwitches(process.argv.slice(1));
  if (bad.length) {
    process.stderr.write(`Refused: --${bad.join(', --')} is not allowed in this build.\n`);
    app.exit(2);
  }
}

const base = R.ramBase(app.isPackaged ? '' : process.env.NULLBROWSER_RAM_BASE || '');
R.cleanStale(base.dir);
const ram = R.createRamDir(base.dir);

process.env.HOME = ram.sub.home;
process.env.XDG_CONFIG_HOME = ram.sub.config;
process.env.XDG_CACHE_HOME = ram.sub.cache;
process.env.XDG_DATA_HOME = ram.sub.data;
process.env.XDG_STATE_HOME = ram.sub.state;
process.env.TMPDIR = ram.sub.temp;
app.setPath('home', ram.sub.home);
app.setPath('appData', ram.sub.config);
app.setPath('userData', ram.sub.chromium);
app.setPath('sessionData', ram.sub.session);
app.setPath('temp', ram.sub.temp);
app.setPath('logs', path.join(ram.sub.temp, 'logs'));
app.setPath('crashDumps', path.join(ram.sub.temp, 'crash'));

app.commandLine.appendSwitch('disable-features', P.DISABLED_FEATURES.join(','));
for (const sw of P.SWITCHES) app.commandLine.appendSwitch(sw);
app.commandLine.appendSwitch('js-flags', P.JS_FLAGS);
app.disableHardwareAcceleration();

const TOOLBAR = 44;
const GESTURE_MS = 1000;

let win = null;
let view = null;
let ses = null;
let lastInput = 0;
let notice = '';
let error = null;
let pendingCert = null;
const allowHttp = new Set();
const upgraded = new Set();
const trusted = new Set();

let cleanerStarted = false;

function cleanup() {
  R.removeRamDir(ram.dir);
  if (!cleanerStarted) {
    cleanerStarted = true;
    R.removeAfterExit(ram.dir);
  }
}

function alive() {
  return win && !win.isDestroyed();
}

function pageUrl() {
  if (!view || view.webContents.isDestroyed()) return '';
  const u = view.webContents.getURL();
  return u === 'about:blank' ? '' : u;
}

function state() {
  const wc = view && !view.webContents.isDestroyed() ? view.webContents : null;
  const url = pageUrl();
  return {
    url,
    title: wc && url ? wc.getTitle() : '',
    canBack: Boolean(wc && wc.navigationHistory.canGoBack()),
    canForward: Boolean(wc && wc.navigationHistory.canGoForward()),
    loading: Boolean(wc && wc.isLoading()),
    secure: url.startsWith('https:') && !error,
    insecure: url.startsWith('http:'),
    blank: !url && !error,
    error,
    notice,
    ram: base.ram,
  };
}

function layout() {
  if (!alive() || !view) return;
  const [w, h] = win.getContentSize();
  view.setBounds({ x: 0, y: TOOLBAR, width: w, height: Math.max(0, h - TOOLBAR) });
  view.setVisible(Boolean(pageUrl()) && !error);
}

function push() {
  layout();
  if (alive()) win.webContents.send('state', state());
}

function say(text) {
  notice = text;
  push();
  setTimeout(() => {
    if (notice === text) {
      notice = '';
      push();
    }
  }, 6000);
}

function topUrlOf(details) {
  try {
    if (details.frame && details.frame.top && details.frame.top.url) return details.frame.top.url;
  } catch {
    return pageUrl();
  }
  return pageUrl();
}

function thirdParty(details) {
  if (details.resourceType === 'mainFrame') return false;
  return P.isThirdParty(details.url, topUrlOf(details));
}

function hardenPage(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.setUserAgent(P.chromiumUserAgent(s.getUserAgent()));
  s.on('will-download', (event, item) => {
    item.cancel();
    say('Downloads are off in Null Browser.');
  });
  s.webRequest.onBeforeRequest((details, callback) => {
    if (details.url !== 'about:blank' && !P.allowSubresource(details.url)) return callback({ cancel: true });
    if (details.resourceType === 'mainFrame') {
      const up = P.httpsUpgrade(details.url, allowHttp);
      if (up) {
        upgraded.add(up);
        return callback({ redirectURL: up });
      }
    }
    return callback({});
  });
  s.webRequest.onBeforeSendHeaders((details, callback) => {
    if (!thirdParty(details)) return callback({});
    const requestHeaders = {};
    for (const [k, v] of Object.entries(details.requestHeaders)) if (k.toLowerCase() !== 'cookie') requestHeaders[k] = v;
    return callback({ requestHeaders });
  });
  s.webRequest.onHeadersReceived((details, callback) => {
    if (!thirdParty(details)) return callback({});
    const r = P.stripCookieHeaders(details.responseHeaders);
    return callback(r.removed ? { responseHeaders: r.headers } : {});
  });
}

function hardenShell(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !/^(file|data):/i.test(details.url) }));
}

function fingerprint(cert) {
  const body = String((cert && cert.data) || '').replace(/-----[A-Z ]+-----/g, '').replace(/\s+/g, '');
  const der = Buffer.from(body, 'base64');
  return der.length ? crypto.createHash('sha256').update(der).digest('hex') : '';
}

function showFingerprint(hex) {
  return (hex.toUpperCase().match(/.{1,2}/g) || []).join(':');
}

function load(url) {
  error = null;
  pendingCert = null;
  view.webContents.loadURL(url).catch(() => {});
  push();
}

function onKey(event, input) {
  if (input.type === 'mouseDown' || input.type === 'keyDown') lastInput = Date.now();
  if (input.type !== 'keyDown') return;
  const k = String(input.key).toLowerCase();
  let act = null;
  if ((input.control || input.meta) && k === 'l') act = () => alive() && win.webContents.send('focus-address');
  else if ((input.control || input.meta) && k === 'r') act = () => (error ? retry() : view.webContents.reload());
  else if (input.alt && k === 'arrowleft') act = () => view.webContents.navigationHistory.goBack();
  else if (input.alt && k === 'arrowright') act = () => view.webContents.navigationHistory.goForward();
  else if (k === 'escape') act = () => view.webContents.stop();
  if (!act) return;
  event.preventDefault();
  setImmediate(act);
}

function retry() {
  const last = error && error.url;
  if (last) load(last);
  else view.webContents.reload();
}

function createView() {
  view = new WebContentsView({
    webPreferences: {
      session: ses,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: false,
      plugins: false,
      safeDialogs: true,
      navigateOnDragDrop: false,
    },
  });
  win.contentView.addChildView(view);
  const wc = view.webContents;
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('before-input-event', onKey);
  wc.on('input-event', (ev, input) => {
    if (input && (input.type === 'mouseDown' || input.type === 'keyDown')) lastInput = Date.now();
  });
  for (const ev of ['did-start-loading', 'did-stop-loading', 'did-navigate', 'did-navigate-in-page', 'page-title-updated']) wc.on(ev, push);
  wc.on('did-start-navigation', (ev, url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) {
      error = null;
      pendingCert = null;
    }
  });
  wc.setWindowOpenHandler(({ url, disposition, features, frameName }) => {
    const tab = disposition === 'foreground-tab' || disposition === 'background-tab';
    const clicked = Date.now() - lastInput < GESTURE_MS;
    if (tab && clicked && !features && !frameName && P.allowPageUrl(url)) setImmediate(() => load(url));
    return { action: 'deny' };
  });
  wc.on('will-navigate', (ev, url) => {
    if (!P.allowPageUrl(url)) {
      ev.preventDefault();
      say('Only web addresses (http and https) are opened here.');
    }
  });
  wc.on('certificate-error', (event, url, err, cert, callback) => {
    const host = P.hostOf(url);
    const fp = fingerprint(cert);
    event.preventDefault();
    if (fp && trusted.has(`${host} ${fp}`)) return callback(true);
    pendingCert = { host, fingerprint: fp, shown: showFingerprint(fp), reason: err, trustable: P.certTrustable(host) };
    return callback(false);
  });
  wc.on('did-fail-load', (ev, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    if (pendingCert && pendingCert.host === P.hostOf(url)) {
      error = { kind: 'cert', url, message: desc, ...pendingCert };
    } else if (upgraded.has(url)) {
      const http = url.replace(/^https:/, 'http:');
      error = { kind: 'nohttps', url: http, host: P.hostOf(url), message: desc };
    } else {
      error = { kind: 'fail', url, message: desc, code };
    }
    push();
  });
  wc.on('render-process-gone', (ev, details) => {
    error = { kind: 'fail', url: pageUrl(), message: `The page stopped working (${details.reason}).`, code: 0 };
    push();
  });
  wc.loadURL('about:blank').catch(() => {});
}

function fromShell(e) {
  return alive() && e.sender === win.webContents;
}

function register() {
  ipcMain.handle('state', (e) => (fromShell(e) ? state() : null));
  ipcMain.handle('go', (e, text) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = P.normalizeInput(text);
    if (r.error) return r;
    if (r.blank) {
      error = null;
      view.webContents.loadURL('about:blank').catch(() => {});
      push();
      return { ok: true };
    }
    load(r.url);
    return { ok: true };
  });
  ipcMain.handle('nav', (e, what) => {
    if (!fromShell(e)) return { ok: false };
    const wc = view.webContents;
    if (what === 'back' && wc.navigationHistory.canGoBack()) wc.navigationHistory.goBack();
    else if (what === 'forward' && wc.navigationHistory.canGoForward()) wc.navigationHistory.goForward();
    else if (what === 'reload') retry();
    else if (what === 'stop') wc.stop();
    else if (what === 'home') {
      error = null;
      wc.loadURL('about:blank').catch(() => {});
    }
    push();
    return { ok: true };
  });
  ipcMain.handle('allow-http', (e) => {
    if (!fromShell(e) || !error || error.kind !== 'nohttps') return { ok: false };
    allowHttp.add(error.host);
    load(error.url);
    return { ok: true };
  });
  ipcMain.handle('trust-cert', (e) => {
    if (!fromShell(e) || !error || error.kind !== 'cert' || !error.trustable || !error.fingerprint) return { ok: false };
    trusted.add(`${error.host} ${error.fingerprint}`);
    load(error.url);
    return { ok: true };
  });
}

let shellPartition = '';

function shellSession() {
  if (!shellPartition) shellPartition = `nb-shell-${crypto.randomBytes(8).toString('hex')}`;
  return session.fromPartition(shellPartition);
}

function createWindow() {
  const work = screen.getPrimaryDisplay().workAreaSize;
  win = new BrowserWindow({
    width: Math.min(1280, work.width),
    height: Math.min(860, work.height),
    minWidth: Math.min(640, work.width),
    minHeight: Math.min(400, work.height),
    center: true,
    title: 'Null Browser',
    backgroundColor: '#0d1117',
    webPreferences: {
      session: shellSession(),
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });
  win.webContents.on('before-input-event', onKey);
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.on('resize', layout);
  win.on('closed', () => {
    win = null;
  });
  createView();
  win.webContents.once('did-finish-load', push);
  win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
}

app.on('web-contents-created', (e, contents) => {
  contents.on('will-attach-webview', (ev) => ev.preventDefault());
});

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => {
    app.quit();
    setTimeout(() => process.exit(0), 3000).unref();
  });
}

const primary = app.requestSingleInstanceLock();
if (!primary) {
  cleanup();
  app.exit(0);
}

app.on('second-instance', () => {
  if (alive()) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  hardenShell(session.defaultSession);
  hardenShell(shellSession());
  ses = session.fromPartition(`nullbrowser-${crypto.randomBytes(8).toString('hex')}`);
  hardenPage(ses);
  register();
  createWindow();
});

app.on('window-all-closed', () => app.quit());

app.on('will-quit', () => {
  if (ses) {
    ses.clearStorageData().catch(() => {});
    ses.clearCache().catch(() => {});
  }
});

app.on('quit', cleanup);
process.on('exit', cleanup);
