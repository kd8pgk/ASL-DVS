const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const os = require('node:os');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog } = require('electron');
const P = require('./policy');
const R = require('./ram');
const F = require('./files');
const B = require('./bookmarks');
const W = require('./watchdog');

app.setName('Null Browser');

if (app.isPackaged) {
  const bad = P.unsafeSwitches(process.argv.slice(1));
  if (bad.length) {
    process.stderr.write(`Refused: --${bad.join(', --')} is not allowed in this build.\n`);
    app.exit(2);
  }
}

const base = R.ramBase(app.isPackaged ? '' : process.env.NULLBROWSER_RAM_BASE || '');
const MAX_BYTES = !app.isPackaged && Number(process.env.NULLBROWSER_MAX_BYTES) > 0 ? Number(process.env.NULLBROWSER_MAX_BYTES) : F.MAX_BYTES;
R.rammaidSweep(base.dir);
const preDir = R.prelaunchDir(process.env.NULLBROWSER_PRELAUNCH_DIR);
const ram = preDir ? R.adoptRamDir(preDir) : R.createRamDir(base.dir);

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

const fastJs = process.argv.slice(1).includes(P.FAST_JS_ARG);

app.commandLine.appendSwitch('disable-features', P.DISABLED_FEATURES.join(','));
for (const sw of P.SWITCHES) {
  const eq = sw.indexOf('=');
  if (eq === -1) app.commandLine.appendSwitch(sw);
  else app.commandLine.appendSwitch(sw.slice(0, eq), sw.slice(eq + 1));
}
if (!fastJs) app.commandLine.appendSwitch('js-flags', P.JS_FLAGS);
app.disableHardwareAcceleration();

const TOOLBAR = 44;
const BAR = 34;
const GESTURE_MS = 1000;
const LITTERBUG_MS = 3000;
const MAX_LITTERBUGS = 3;

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
const allowedSites = new Set();
const litterbugIds = new Set();
let blockedSite = '';
let nextPopup = '';
let pendingFile = null;
let fileSeq = 0;
let bookmarks = [];
let bookmarkSeq = 0;
let pendingJs = null;

let cleanerStarted = false;

function rammaid() {
  R.rammaidRemove(ram.dir);
  if (!cleanerStarted) {
    cleanerStarted = true;
    R.rammaidAfterExit(ram.dir);
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
    ask: pendingFile ? { id: pendingFile.id, text: pendingFile.text, busy: pendingFile.state !== 'ask' } : null,
    popup: blockedSite && !allowedSites.has(blockedSite) ? blockedSite : '',
    allowed: allowedSites.has(P.siteOf(P.hostOf(url))),
    ram: base.ram,
    bookmarks: bookmarks.map(({ id, url: u, title }) => ({ id, url: u, title })),
    fastJs,
    jsAsk: pendingJs,
  };
}

function bars() {
  const s = state();
  return (s.notice ? 1 : 0) + (s.ask ? 1 : 0) + (s.popup ? 1 : 0) + (s.jsAsk === null ? 0 : 1);
}

function layout() {
  if (!alive() || !view) return;
  const [w, h] = win.getContentSize();
  const top = TOOLBAR + BAR * bars();
  view.setBounds({ x: 0, y: top, width: w, height: Math.max(0, h - top) });
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

function litterbugRequest(details) {
  return litterbugIds.has(details.webContentsId);
}

function thirdParty(details) {
  if (details.resourceType === 'mainFrame') return false;
  const top = topUrlOf(details);
  if (allowedSites.has(P.siteOf(P.hostOf(top)))) return false;
  return P.isThirdParty(details.url, top);
}

function purgeOrigin(origin) {
  if (origin) ses.clearStorageData({ origin }).catch(() => {});
  ses.clearCache().catch(() => {});
}

function purgeIfSiteChanged(nextUrl) {
  const leaving = pageUrl();
  if (!leaving) return;
  const leavingSite = P.siteOf(P.hostOf(leaving));
  const nextSite = P.siteOf(P.hostOf(nextUrl));
  if (!leavingSite || leavingSite === nextSite || allowedSites.has(leavingSite)) return;
  purgeOrigin(P.originOf(leaving));
}

function watchdogFlag(site, reason) {
  if (!site || allowedSites.has(site)) return;
  purgeOrigin(P.originOf(pageUrl()));
  say(`Watchdog: ${site} ${reason}, so it was cleared.`);
}

const watchdog = W.createWatchdog({ onFlag: watchdogFlag });

const CPU_CORES = Math.max(os.cpus().length, 1);

function watchdogCpuPoll() {
  if (!view || view.webContents.isDestroyed()) return;
  const pid = view.webContents.getOSProcessId();
  const m = app.getAppMetrics().find((x) => x.pid === pid);
  if (!m) return;
  const idle = Date.now() - lastInput > W.CPU_IDLE_MS;
  watchdog.noteCpu(P.siteOf(P.hostOf(pageUrl())), idle, m.cpu.percentCPUUsage * CPU_CORES);
}

function rammaidFile(file) {
  try {
    fs.rmSync(file, { force: true });
  } catch {
    return;
  }
}

function openFile(file) {
  if (!app.isPackaged && process.env.NULLBROWSER_OPEN_LOG) {
    fs.appendFileSync(process.env.NULLBROWSER_OPEN_LOG, `${file}\n`);
    return;
  }
  shell.openPath(file).then((err) => {
    if (err) say(`No app on this computer could open ${path.basename(file)}.`);
  });
}

function checkAndOpen(rec) {
  let head = Buffer.alloc(0);
  try {
    const fd = fs.openSync(rec.file, 'r');
    head = Buffer.alloc(64);
    const n = fs.readSync(fd, head, 0, 64, 0);
    fs.closeSync(fd);
    head = head.subarray(0, n);
  } catch {
    head = Buffer.alloc(0);
  }
  if (!F.contentMatches(rec.kind, head)) {
    rammaidFile(rec.file);
    say(`${rec.name} is not really ${rec.kind === 'pdf' ? 'a PDF' : rec.kind}, so it was not opened.`);
    const from = (() => {
      try {
        return rec.item.getURL();
      } catch {
        return '';
      }
    })();
    watchdog.noteFakeFile(P.siteOf(P.hostOf(from || pageUrl())));
    return;
  }
  openFile(rec.file);
  push();
}

function endFile(rec) {
  if (pendingFile === rec) pendingFile = null;
  push();
}

function finishFile(rec, st) {
  rec.done = st;
  if (st !== 'completed') {
    rammaidFile(rec.file);
    if (rec.tooBig) say(`${rec.name} is too big to open from memory.`);
    else if (rec.answer === true) say(`${rec.name} could not be fetched.`);
    endFile(rec);
    return;
  }
  if (rec.answer === undefined) return;
  endFile(rec);
  if (rec.answer === true) checkAndOpen(rec);
  else rammaidFile(rec.file);
}

function answerFile(rec, open) {
  rec.answer = open === true;
  if (rec.done === 'completed') {
    endFile(rec);
    if (rec.answer) checkAndOpen(rec);
    else rammaidFile(rec.file);
    return;
  }
  if (rec.done) {
    endFile(rec);
    return;
  }
  if (!rec.answer) {
    rec.item.cancel();
    return;
  }
  rec.state = 'loading';
  push();
}

function onDownload(event, item) {
  const name = F.safeName(item.getFilename());
  const kind = F.classify(item.getMimeType(), name);
  const total = item.getTotalBytes();
  if (!kind) {
    item.cancel();
    say('Downloads are off in Null Browser.');
    return;
  }
  if (total > MAX_BYTES) {
    item.cancel();
    say(`${name} is too big to open from memory.`);
    return;
  }
  if (pendingFile) {
    item.cancel();
    say('Answer the question about the other file first.');
    return;
  }
  fileSeq += 1;
  const rec = { id: fileSeq, item, file: path.join(ram.sub.files, `${fileSeq}-${name}`), kind, name, text: F.question(name, kind, total), state: 'ask' };
  item.setSavePath(rec.file);
  item.on('updated', () => {
    if (rec.tooBig || item.getReceivedBytes() <= MAX_BYTES) return;
    rec.tooBig = true;
    item.cancel();
  });
  item.once('done', (e, st) => finishFile(rec, st));
  pendingFile = rec;
  push();
}

function hardenPage(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.setSpellCheckerLanguages([]);
  s.setUserAgent(P.chromiumUserAgent(s.getUserAgent()));
  s.on('will-download', onDownload);
  s.webRequest.onBeforeRequest((details, callback) => {
    if (litterbugRequest(details)) return callback({ cancel: true });
    if (details.url !== 'about:blank' && !P.allowSubresource(details.url)) return callback({ cancel: true });
    if (details.resourceType === 'mainFrame') {
      const up = P.httpsUpgrade(details.url, allowHttp);
      if (up) {
        upgraded.add(up);
        return callback({ redirectURL: up });
      }
    } else {
      watchdog.noteSubresource(P.siteOf(P.hostOf(topUrlOf(details))), P.hostOf(details.url));
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
    let headers = null;
    if (details.resourceType === 'mainFrame' && details.statusCode >= 200 && details.statusCode < 300) {
      const ct = Object.entries(details.responseHeaders || {}).find(([k]) => k.toLowerCase() === 'content-type');
      if (F.kindOfMime(ct ? [].concat(ct[1])[0] : '')) {
        headers = {};
        for (const [k, v] of Object.entries(details.responseHeaders)) if (k.toLowerCase() !== 'content-disposition') headers[k] = v;
        const name = F.safeName(decodeURIComponent((new URL(details.url).pathname.split('/').pop() || 'file')));
        headers['Content-Disposition'] = [`attachment; filename="${name}"`];
      }
    }
    if (!thirdParty(details)) return callback(headers ? { responseHeaders: headers } : {});
    if (headers) {
      const r0 = P.stripCookieHeaders(headers);
      return callback({ responseHeaders: r0.headers });
    }
    const r = P.stripCookieHeaders(details.responseHeaders);
    return callback(r.removed ? { responseHeaders: r.headers } : {});
  });
}

function hardenShell(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.setSpellCheckerLanguages([]);
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
  wc.on('will-prevent-unload', (ev) => ev.preventDefault());
  wc.on('before-input-event', onKey);
  wc.on('input-event', (ev, input) => {
    if (input && (input.type === 'mouseDown' || input.type === 'keyDown')) lastInput = Date.now();
  });
  for (const ev of ['did-start-loading', 'did-stop-loading', 'did-navigate', 'did-navigate-in-page', 'page-title-updated']) wc.on(ev, push);
  wc.on('did-start-navigation', (ev, url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) {
      purgeIfSiteChanged(url);
      error = null;
      pendingCert = null;
    }
  });
  wc.setWindowOpenHandler(({ url, disposition, features, frameName }) => {
    const tab = disposition === 'foreground-tab' || disposition === 'background-tab';
    const clicked = Date.now() - lastInput < GESTURE_MS;
    if (tab && clicked && !features && !frameName && P.allowPageUrl(url)) {
      setImmediate(() => load(url));
      return { action: 'deny' };
    }
    const site = P.siteOf(P.hostOf(pageUrl()));
    if (site && allowedSites.has(site) && P.allowPageUrl(url)) {
      nextPopup = 'real';
      return { action: 'allow', outlivesOpener: false, overrideBrowserWindowOptions: realPopupOptions(features) };
    }
    if (site) {
      blockedSite = site;
      setImmediate(push);
    }
    if (litterbugIds.size >= MAX_LITTERBUGS) {
      watchdog.notePopupCapped(site);
      return { action: 'deny' };
    }
    nextPopup = 'litterbug';
    return { action: 'allow', outlivesOpener: false, overrideBrowserWindowOptions: LITTERBUG_OPTIONS };
  });
  wc.on('did-create-window', (child) => {
    const kind = nextPopup;
    nextPopup = '';
    if (kind === 'litterbug') litterbugSink(child);
    else if (kind === 'real') realPopup(child);
    else child.destroy();
  });
  wc.on('did-navigate', (ev, url) => {
    litterbugClose();
    const site = P.siteOf(P.hostOf(url));
    if (blockedSite && blockedSite !== site) blockedSite = '';
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
    const url = pageUrl();
    error = { kind: 'fail', url, message: `The page stopped working (${details.reason}).`, code: 0 };
    watchdog.noteCrash(P.siteOf(P.hostOf(url)));
    push();
  });
  wc.loadURL('about:blank').catch(() => {});
}

const POPUP_PREFS = {
  sandbox: true,
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false,
  spellcheck: false,
  plugins: false,
  safeDialogs: true,
  navigateOnDragDrop: false,
};

const LITTERBUG_OPTIONS = {
  show: false,
  width: 1,
  height: 1,
  frame: false,
  skipTaskbar: true,
  focusable: false,
  paintWhenInitiallyHidden: false,
  webPreferences: { ...POPUP_PREFS },
};

function realPopupOptions(features) {
  const w = Number((/(?:^|,)\s*width\s*=\s*(\d+)/i.exec(features || '') || [])[1]) || 520;
  const h = Number((/(?:^|,)\s*height\s*=\s*(\d+)/i.exec(features || '') || [])[1]) || 680;
  return {
    show: true,
    width: Math.min(Math.max(w, 320), 1200),
    height: Math.min(Math.max(h, 320), 1000),
    autoHideMenuBar: true,
    backgroundColor: '#0d1117',
    webPreferences: { ...POPUP_PREFS },
  };
}

function litterbugClose() {
  for (const w of BrowserWindow.getAllWindows()) {
    if (litterbugIds.has(w.webContents.id)) w.destroy();
  }
}

function litterbugSink(child) {
  const id = child.webContents.id;
  litterbugIds.add(id);
  child.webContents.setAudioMuted(true);
  child.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  child.on('closed', () => litterbugIds.delete(id));
  setTimeout(() => {
    if (!child.isDestroyed()) child.destroy();
  }, LITTERBUG_MS).unref();
}

function realPopup(child) {
  const wc = child.webContents;
  child.setMenu(null);
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('will-prevent-unload', (ev) => ev.preventDefault());
  wc.setWindowOpenHandler(() => ({ action: 'deny' }));
  wc.on('will-navigate', (ev, url) => {
    if (!P.allowPageUrl(url)) ev.preventDefault();
  });
  wc.on('certificate-error', (event, url, err, cert, callback) => {
    event.preventDefault();
    callback(false);
  });
}

function fromShell(e) {
  return alive() && e.sender === win.webContents;
}

let shellReady = false;

function register() {
  ipcMain.handle('state', (e) => {
    if (!fromShell(e)) return null;
    if (!shellReady) {
      shellReady = true;
      process.stderr.write('shell-ready\n');
    }
    return state();
  });
  ipcMain.handle('go', (e, text) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = P.normalizeInput(text);
    if (r.error) {
      say(r.error);
      return r;
    }
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
  ipcMain.handle('file-answer', (e, id, open) => {
    if (!fromShell(e) || !pendingFile || pendingFile.id !== id || pendingFile.state !== 'ask') return { ok: false };
    answerFile(pendingFile, open);
    return { ok: true };
  });
  ipcMain.handle('allow-site', (e) => {
    if (!fromShell(e) || !blockedSite) return { ok: false };
    const site = blockedSite;
    allowedSites.add(site);
    blockedSite = '';
    say(`Pop-ups and sign-in cookies are allowed for ${site} until Null Browser closes.`);
    return { ok: true };
  });
  ipcMain.handle('dismiss-popup', (e) => {
    if (!fromShell(e)) return { ok: false };
    blockedSite = '';
    push();
    return { ok: true };
  });
  ipcMain.handle('trust-cert', (e) => {
    if (!fromShell(e) || !error || error.kind !== 'cert' || !error.trustable || !error.fingerprint) return { ok: false };
    trusted.add(`${error.host} ${error.fingerprint}`);
    load(error.url);
    return { ok: true };
  });
  ipcMain.handle('import-bookmarks', async (e) => {
    if (!fromShell(e)) return { ok: false };
    const res = await dialog.showOpenDialog(win, {
      title: 'Import bookmarks',
      filters: [{ name: 'Bookmarks', extensions: ['html', 'htm'] }],
      properties: ['openFile'],
    });
    if (res.canceled || !res.filePaths[0]) return { ok: false };
    let text = '';
    try {
      const st = fs.statSync(res.filePaths[0]);
      if (st.size > B.MAX_FILE_BYTES) {
        say('That bookmarks file is too big to import.');
        return { ok: false };
      }
      text = fs.readFileSync(res.filePaths[0], 'utf8');
    } catch {
      say('That file could not be read.');
      return { ok: false };
    }
    const found = B.parseBookmarks(text);
    const have = new Set(bookmarks.map((b) => b.url));
    let added = 0;
    let full = false;
    for (const f of found) {
      if (have.has(f.url)) continue;
      if (bookmarks.length >= B.MAX_BOOKMARKS) {
        full = true;
        continue;
      }
      have.add(f.url);
      bookmarkSeq += 1;
      bookmarks.push({ id: bookmarkSeq, url: f.url, title: f.title });
      added += 1;
    }
    if (added) say(`${added} bookmark${added === 1 ? '' : 's'} imported${full ? ' (the list is now full)' : ''}.`);
    else say(full ? 'The bookmarks list is full.' : found.length ? 'Those bookmarks were already imported.' : 'No bookmarks were found in that file.');
    push();
    return { ok: true };
  });
  ipcMain.handle('remove-bookmark', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    bookmarks = bookmarks.filter((b) => b.id !== id);
    push();
    return { ok: true };
  });
  ipcMain.handle('request-fast-js', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    if (Boolean(on) === fastJs) return { ok: true };
    pendingJs = Boolean(on);
    push();
    return { ok: true };
  });
  ipcMain.handle('cancel-fast-js', (e) => {
    if (!fromShell(e)) return { ok: false };
    pendingJs = null;
    push();
    return { ok: true };
  });
  ipcMain.handle('confirm-fast-js', (e) => {
    if (!fromShell(e) || pendingJs === null) return { ok: false };
    app.relaunch({ args: P.relaunchArgv(process.argv.slice(1), pendingJs) });
    app.quit();
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
  rammaid();
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
  setInterval(watchdogCpuPoll, W.CPU_IDLE_MS).unref();
});

app.on('window-all-closed', () => app.quit());

app.on('will-quit', () => {
  if (ses) {
    ses.clearStorageData().catch(() => {});
    ses.clearCache().catch(() => {});
  }
});

app.on('quit', rammaid);
process.on('exit', rammaid);
