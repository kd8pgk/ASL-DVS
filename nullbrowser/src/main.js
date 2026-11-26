const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const os = require('node:os');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog, net, protocol } = require('electron');
const P = require('./policy');
const R = require('./ram');
const F = require('./files');
const B = require('./bookmarks');
const W = require('./watchdog');
const S = require('./slow');
const SH = require('./shot');
const DL = require('./download');

const REAL_HOME = os.homedir();

app.setName('Null Browser');
protocol.registerSchemesAsPrivileged([{ scheme: S.SCHEME, privileges: { standard: true, secure: true, corsEnabled: true, supportFetchAPI: true } }]);

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

const { st } = require('./state');
const { onDownload, answerFile, rammaidFile, runDownload, scanFiles, entryOf } = require('./downloads');
const shared = require('./ctx');
const { makeShot, answerShot } = require('./screenshot');
const { hardenShell, pageLang, fingerprint, showFingerprint, topUrlOf, litterbugRequest, thirdParty } = require('./network');
const { line, meter, starts, served, ahead, own, pageId, slowActive, lineState, lineChanged, serve, resetLine, clearAhead, stopImages, holdImage, pump, onReport, setLine, lineErrored } = require('./slowline');

const TOOLBAR = 44;
const BAR = 34;
const GESTURE_MS = 1000;
const LITTERBUG_MS = 3000;
const STUCK_MS = 2000;
const MAX_LITTERBUGS = 3;

const dlQueue = DL.createQueue(runDownload);

let cleanerStarted = false;

function rammaid() {
  R.rammaidRemove(ram.dir);
  if (!cleanerStarted) {
    cleanerStarted = true;
    R.rammaidAfterExit(ram.dir);
  }
}

function alive() {
  return st.win && !st.win.isDestroyed();
}

function pageUrl() {
  if (!st.view || st.view.webContents.isDestroyed()) return '';
  const u = st.view.webContents.getURL();
  return u === 'about:blank' ? '' : u;
}

function state() {
  const wc = st.view && !st.view.webContents.isDestroyed() ? st.view.webContents : null;
  const url = pageUrl();
  return {
    url,
    title: wc && url ? wc.getTitle() : '',
    canBack: Boolean(wc && wc.navigationHistory.canGoBack()),
    canForward: Boolean(wc && wc.navigationHistory.canGoForward()),
    loading: Boolean(wc && wc.isLoading()),
    secure: url.startsWith('https:') && !st.error,
    insecure: url.startsWith('http:'),
    blank: !url && !st.error,
    error: st.error,
    notice: st.notice,
    ask: st.pendingFile ? { id: st.pendingFile.id, text: st.pendingFile.text, busy: st.pendingFile.state !== 'ask' } : null,
    popup: st.blockedSite && !st.allowedSites.has(st.blockedSite) ? st.blockedSite : '',
    allowed: st.allowedSites.has(P.siteOf(P.hostOf(url))),
    ram: base.ram,
    bookmarks: st.bookmarks.map(({ id, url: u, title }) => ({ id, url: u, title })),
    fastJs,
    jsAsk: st.pendingJs,
    leave: st.pendingLeave ? { id: st.pendingLeave.id, text: st.pendingLeave.text } : null,
    line: lineState(),
    shot: st.pendingShot ? { text: st.pendingShot.text, busy: st.pendingShot.busy } : null,
    dl: {
      allowed: st.dlAllowed,
      asking: st.dlAsking,
      panel: st.dlPanelOpen,
      queuePanel: st.dlQueueOpen,
      warn: st.dlWarn,
      list: st.dlList.map(({ href, kind, name, path: p, host }) => ({ href, kind, name, path: p, host })),
      queue: dlQueue.snapshot(),
      busy: dlQueue.busy(),
    },
  };
}

function lineRows(l) {
  return (l.open ? 1 : 0) + ((l.active && (l.busy || l.retrying)) || l.ahead ? 1 : 0);
}

function bars() {
  const s = state();
  return (s.notice ? 1 : 0) + (s.ask ? 1 : 0) + (s.popup ? 1 : 0) + (s.jsAsk === null ? 0 : 1) + (s.leave ? 1 : 0) + (s.shot ? 1 : 0) + lineRows(s.line) + (s.dl.asking ? 1 : 0) + (s.dl.queue.length ? 1 : 0);
}

function layout() {
  if (!alive() || !st.view) return;
  const [w, h] = st.win.getContentSize();
  const top = TOOLBAR + BAR * bars();
  st.view.setBounds({ x: 0, y: top, width: w, height: Math.max(0, h - top) });
  st.view.setVisible(Boolean(pageUrl()) && !st.error);
}

function push() {
  layout();
  if (alive()) st.win.webContents.send('state', state());
}

function say(text) {
  st.notice = text;
  push();
  setTimeout(() => {
    if (st.notice === text) {
      st.notice = '';
      push();
    }
  }, 6000);
}

function purgeOrigin(origin) {
  if (origin) st.ses.clearStorageData({ origin }).catch(() => {});
  st.ses.clearCache().catch(() => {});
}

function purgeIfSiteChanged(nextUrl) {
  const leaving = pageUrl();
  if (!leaving) return;
  const leavingSite = P.siteOf(P.hostOf(leaving));
  const nextSite = P.siteOf(P.hostOf(nextUrl));
  if (!leavingSite || leavingSite === nextSite) return;
  clearAhead();
  if (st.allowedSites.has(leavingSite)) return;
  purgeOrigin(P.originOf(leaving));
}

function wipeAll() {
  dlQueue.cancelAll();
  dlQueue.clear();
  st.dlAllowed = false;
  st.dlAsking = true;
  st.dlQueueOpen = false;
  resetLine();
  clearAhead();
  st.allowHttp.clear();
  st.upgraded.clear();
  st.trusted.clear();
  st.allowedSites.clear();
  st.blockedSite = '';
  st.nextPopup = '';
  st.pendingCert = null;
  st.error = null;
  if (st.pendingFile) {
    const rec = st.pendingFile;
    st.pendingFile = null;
    try {
      rec.item.cancel();
    } catch {}
    rammaidFile(rec.file);
  }
  for (const name of fs.readdirSync(ram.sub.files)) {
    if (name === 'quarantine') continue;
    try {
      fs.rmSync(path.join(ram.sub.files, name), { recursive: true, force: true });
    } catch {}
  }
  st.watchdog = W.createWatchdog({ onFlag: watchdogFlag });
  st.pendingLeave = null;
  if (st.ses) {
    st.ses.clearStorageData().catch(() => {});
    st.ses.clearCache().catch(() => {});
    st.ses.clearAuthCache().catch(() => {});
    st.ses.clearHostResolverCache().catch(() => {});
  }
  if (st.view && !st.view.webContents.isDestroyed()) st.view.webContents.loadURL('about:blank').catch(() => {});
  say('Cleared: this run\'s pages, cookies, storage, cache, sign-ins, allowed sites and downloads. Kept: bookmarks and quarantined screenshots.');
}

function watchdogFlag(site, reason) {
  if (!site || st.allowedSites.has(site)) return;
  purgeOrigin(P.originOf(pageUrl()));
  say(`Watchdog: ${site} ${reason}, so it was cleared.`);
}

st.watchdog = W.createWatchdog({ onFlag: watchdogFlag });

const CPU_CORES = Math.max(os.cpus().length, 1);

function watchdogCpuPoll() {
  if (!st.view || st.view.webContents.isDestroyed()) return;
  const pid = st.view.webContents.getOSProcessId();
  const m = app.getAppMetrics().find((x) => x.pid === pid);
  if (!m) return;
  const idle = Date.now() - st.lastInput > W.CPU_IDLE_MS;
  st.watchdog.noteCpu(P.siteOf(P.hostOf(pageUrl())), idle, m.cpu.percentCPUUsage * CPU_CORES);
}

function readUserDirs() {
  try {
    return fs.readFileSync(path.join(REAL_HOME, '.config', 'user-dirs.dirs'), 'utf8');
  } catch {
    return '';
  }
}

function hardenPage(s) {
  s.setPermissionRequestHandler((wc, permission, callback) => callback(false));
  s.setPermissionCheckHandler(() => false);
  s.setDevicePermissionHandler(() => false);
  s.setSpellCheckerEnabled(false);
  s.setSpellCheckerLanguages([]);
  s.setUserAgent(P.chromiumUserAgent(s.getUserAgent()), pageLang());
  s.on('will-download', onDownload);
  s.webRequest.onBeforeRequest((details, callback) => {
    if (litterbugRequest(details)) return callback({ cancel: true });
    if (details.url.startsWith(`${S.SCHEME}://`)) return callback({});
    if (details.url !== 'about:blank' && !P.allowSubresource(details.url)) return callback({ cancel: true });
    if (details.resourceType === 'mainFrame') {
      const up = P.httpsUpgrade(details.url, st.allowHttp);
      if (up) {
        st.upgraded.add(up);
        return callback({ redirectURL: up });
      }
    } else if (!(details.webContentsId === undefined && own.has(details.url))) {
      st.watchdog.noteSubresource(P.siteOf(P.hostOf(topUrlOf(details))), P.hostOf(details.url));
    }
    if (details.webContentsId === pageId() && details.resourceType !== 'mainFrame') {
      const type = details.resourceType;
      if (type === 'image' && !line.images) return callback({ cancel: true });
      if (type === 'image' && ahead.has(details.url)) return callback({ redirectURL: serve(ahead.get(details.url)) });
      if (slowActive()) {
        if (type === 'font' || type === 'ping') return callback({ cancel: true });
        if (type === 'image' && details.method === 'GET' && /^https?:/i.test(details.url)) return holdImage(details, callback);
      }
    }
    if (details.webContentsId === pageId()) starts.set(details.id, Date.now());
    return callback({});
  });
  s.webRequest.onBeforeSendHeaders((details, callback) => {
    const page = details.webContentsId === pageId();
    if (page && details.resourceType !== 'mainFrame' && slowActive() && S.isPrefetch(details.requestHeaders)) return callback({ cancel: true });
    const strip = thirdParty(details);
    const addSave = line.saveData && (page || details.webContentsId === undefined);
    const minimal = P.minimalRequestHeaders(details.requestHeaders, details.url, pageLang());
    if (!strip && !addSave && !minimal.changed) return callback({});
    const requestHeaders = {};
    for (const [k, v] of Object.entries(minimal.headers)) if (!(strip && k.toLowerCase() === 'cookie')) requestHeaders[k] = v;
    if (addSave) requestHeaders['Save-Data'] = 'on';
    return callback({ requestHeaders });
  });
  s.webRequest.onResponseStarted((details) => {
    const t = starts.get(details.id);
    if (t === undefined || details.fromCache) return;
    meter.wait(Date.now() - t);
    lineChanged();
  });
  s.webRequest.onCompleted((details) => {
    const t = starts.get(details.id);
    starts.delete(details.id);
    if (t === undefined || details.fromCache) return;
    const len = Number(S.header(details.responseHeaders, 'content-length'));
    if (len > 0) {
      meter.transfer(len, Date.now() - t);
      lineChanged();
    }
    if (details.resourceType === 'mainFrame' || details.resourceType === 'image') setImmediate(pump);
  });
  s.webRequest.onErrorOccurred(lineErrored);
  s.webRequest.onHeadersReceived((details, callback) => {
    const doc = details.resourceType === 'mainFrame' || details.resourceType === 'subFrame';
    const asks = P.dropHintAsks(details.responseHeaders);
    if (asks) details = { ...details, responseHeaders: asks };
    const csp = doc ? S.cspHeaders(details.responseHeaders) : null;
    if (csp) details = { ...details, responseHeaders: csp };
    let headers = csp || asks;
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

function unstick(redo) {
  const wc = st.view.webContents;
  const id = ++st.leaving;
  const seen = st.commits;
  let answered = false;
  const frame = wc.mainFrame;
  if (!frame) return;
  frame.executeJavaScript('1').then(() => { answered = true; }, () => { answered = true; });
  setTimeout(() => {
      if (answered || id !== st.leaving || seen !== st.commits || wc.isDestroyed() || wc.isCrashed()) return;
      st.unsticking = redo;
    wc.forcefullyCrashRenderer();
  }, STUCK_MS).unref();
}

function askLeave(url) {
  const from = pageUrl();
  if (!P.leavesPage(from, url)) return false;
  const leaving = P.siteOf(P.hostOf(from));
  const cleared = st.allowedSites.has(leaving) ? '' : ' Its cookies and storage are cleared.';
  st.leaveSeq += 1;
  st.pendingLeave = { id: st.leaveSeq, url, text: `Leave ${P.hostOf(from)} for ${P.hostOf(url)}?${cleared}` };
  push();
  return true;
}

function load(url) {
  st.pendingLeave = null;
  st.error = null;
  st.pendingCert = null;
  st.view.webContents.loadURL(url).catch(() => {});
  unstick(() => st.view.webContents.loadURL(url).catch(() => {}));
  push();
}

function clipKey(input) {
  if (input.type !== 'keyDown' && input.type !== 'rawKeyDown' && input.type !== 'char') return false;
  const k = String(input.key).toLowerCase();
  if ((input.control || input.meta) && (k === 'c' || k === 'x' || k === 'v' || k === 'insert')) return true;
  return Boolean(input.shift) && (k === 'insert' || k === 'delete');
}

function noClipKeys(event, input) {
  if (clipKey(input)) event.preventDefault();
}

function onKey(event, input) {
  if (input.type === 'mouseDown' || input.type === 'keyDown') st.lastInput = Date.now();
  if (clipKey(input)) {
    event.preventDefault();
    return;
  }
  if (input.type !== 'keyDown') return;
  const k = String(input.key).toLowerCase();
  let act = null;
  if ((input.control || input.meta) && k === 'l') act = () => alive() && st.win.webContents.send('focus-address');
  else if ((input.control || input.meta) && k === 'r') act = () => (st.error ? retry() : st.view.webContents.reload());
  else if (input.alt && k === 'arrowleft') act = () => st.view.webContents.navigationHistory.goBack();
  else if (input.alt && k === 'arrowright') act = () => st.view.webContents.navigationHistory.goForward();
  else if (k === 'escape') act = () => st.view.webContents.stop();
  if (!act) return;
  event.preventDefault();
  setImmediate(act);
}

function retry() {
  const last = st.error && st.error.url;
  if (last) load(last);
  else st.view.webContents.reload();
}

function createView() {
  st.view = new WebContentsView({
    webPreferences: {
      session: st.ses,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: false,
      plugins: false,
      safeDialogs: true,
      navigateOnDragDrop: false,
      nodeIntegrationInSubFrames: true,
    },
  });
  st.win.contentView.addChildView(st.view);
  const wc = st.view.webContents;
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('will-prevent-unload', (ev) => ev.preventDefault());
  wc.on('before-input-event', onKey);
  wc.on('input-event', (ev, input) => {
    if (input && (input.type === 'mouseDown' || input.type === 'keyDown')) st.lastInput = Date.now();
  });
  for (const ev of ['did-start-loading', 'did-stop-loading', 'did-navigate', 'did-navigate-in-page', 'page-title-updated']) wc.on(ev, push);
  wc.on('did-stop-loading', () => {
    setImmediate(pump);
    scanFiles();
  });
  wc.on('did-start-navigation', (ev, url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) {
      st.pendingLeave = null;
      purgeIfSiteChanged(url);
      resetLine();
      st.error = null;
      st.pendingCert = null;
    }
  });
  wc.setWindowOpenHandler(({ url, disposition, features, frameName }) => {
    const tab = disposition === 'foreground-tab' || disposition === 'background-tab';
    const clicked = Date.now() - st.lastInput < GESTURE_MS;
    if (tab && clicked && !features && !frameName && P.allowPageUrl(url)) {
      if (!askLeave(url)) setImmediate(() => load(url));
      return { action: 'deny' };
    }
    const site = P.siteOf(P.hostOf(pageUrl()));
    if (site && st.allowedSites.has(site) && P.allowPageUrl(url)) {
      st.nextPopup = 'real';
      return { action: 'allow', outlivesOpener: false, overrideBrowserWindowOptions: realPopupOptions(features) };
    }
    if (site) {
      st.blockedSite = site;
      setImmediate(push);
    }
    if (st.litterbugIds.size >= MAX_LITTERBUGS) {
      st.watchdog.notePopupCapped(site);
      return { action: 'deny' };
    }
    st.nextPopup = 'litterbug';
    return { action: 'allow', outlivesOpener: false, overrideBrowserWindowOptions: LITTERBUG_OPTIONS };
  });
  wc.on('did-create-window', (child) => {
    const kind = st.nextPopup;
    st.nextPopup = '';
    if (kind === 'litterbug') litterbugSink(child);
    else if (kind === 'real') realPopup(child);
    else child.destroy();
  });
  wc.on('did-navigate', (ev, url) => {
    litterbugClose();
    const site = P.siteOf(P.hostOf(url));
    if (st.blockedSite && st.blockedSite !== site) st.blockedSite = '';
  });
  wc.on('will-navigate', (ev, url) => {
    if (!P.allowPageUrl(url)) {
      ev.preventDefault();
      say('Only web addresses (http and https) are opened here.');
      return;
    }
    if (askLeave(url)) ev.preventDefault();
  });
  wc.on('certificate-error', (event, url, err, cert, callback) => {
    const host = P.hostOf(url);
    const fp = fingerprint(cert);
    event.preventDefault();
    if (fp && st.trusted.has(`${host} ${fp}`)) return callback(true);
    st.pendingCert = { host, fingerprint: fp, shown: showFingerprint(fp), reason: err, trustable: P.certTrustable(host) };
    return callback(false);
  });
  wc.on('did-fail-load', (ev, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    if (st.pendingCert && st.pendingCert.host === P.hostOf(url)) {
      st.error = { kind: 'cert', url, message: desc, ...st.pendingCert };
    } else if (st.upgraded.has(url)) {
      const http = url.replace(/^https:/, 'http:');
      st.error = { kind: 'nohttps', url: http, host: P.hostOf(url), message: desc };
    } else {
      st.error = { kind: 'fail', url, message: desc, code };
    }
    push();
  });
  wc.on('did-navigate', () => {
    st.commits += 1;
  });
  wc.on('render-process-gone', (ev, details) => {
    if (st.unsticking) {
      const redo = st.unsticking;
      st.unsticking = null;
      redo();
      return;
    }
    const url = pageUrl();
    st.error = { kind: 'fail', url, message: `The page stopped working (${details.reason}).`, code: 0 };
    st.watchdog.noteCrash(P.siteOf(P.hostOf(url)));
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
  nodeIntegrationInSubFrames: true,
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
    if (st.litterbugIds.has(w.webContents.id)) w.destroy();
  }
}

function litterbugSink(child) {
  const id = child.webContents.id;
  st.litterbugIds.add(id);
  child.webContents.setAudioMuted(true);
  child.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  child.on('closed', () => st.litterbugIds.delete(id));
  setTimeout(() => {
    if (!child.isDestroyed()) child.destroy();
  }, LITTERBUG_MS).unref();
}

function realPopup(child) {
  const wc = child.webContents;
  child.setMenu(null);
  wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  wc.on('before-input-event', noClipKeys);
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
  return alive() && e.sender === st.win.webContents;
}

let shellReady = false;

function register() {
  ipcMain.on('nb-report', onReport);
  ipcMain.handle('dl-answer', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    st.dlAllowed = on === true;
    st.dlAsking = false;
    if (!st.dlAllowed) dlQueue.cancelAll();
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-ask', (e) => {
    if (!fromShell(e)) return { ok: false };
    st.dlAsking = true;
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-panel', async (e, on) => {
    if (!fromShell(e)) return { ok: false };
    st.dlPanelOpen = on === true && st.dlAllowed;
    st.dlWarn = false;
    if (st.dlPanelOpen) {
      st.dlQueueOpen = false;
      await scanFiles();
    }
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-queue-panel', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    st.dlQueueOpen = on === true;
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-warn', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    st.dlWarn = on === true && st.dlAllowed && st.dlList.length > 0;
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-all', (e) => {
    if (!fromShell(e) || !st.dlAllowed || st.dlList.length === 0) return { ok: false };
    dlQueue.add(st.dlList.map(({ href, kind, name, path: p, host }) => ({ href, kind, name, path: p, host })));
    st.dlWarn = false;
    st.dlPanelOpen = false;
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-one', (e, href) => {
    if (!fromShell(e) || !st.dlAllowed) return { ok: false };
    const f = entryOf(href);
    if (!f) return { ok: false };
    dlQueue.add([{ href: f.href, kind: f.kind, name: f.name, path: f.path, host: f.host }]);
    st.dlPanelOpen = false;
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-cancel', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    dlQueue.cancel(Number(id));
    return { ok: true };
  });
  ipcMain.handle('dl-cancel-all', (e) => {
    if (!fromShell(e)) return { ok: false };
    dlQueue.cancelAll();
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-remove', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    dlQueue.remove(Number(id));
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-clear', (e) => {
    if (!fromShell(e)) return { ok: false };
    dlQueue.clear();
    push();
    return { ok: true };
  });
  ipcMain.handle('dl-retry', async (e, id) => {
    if (!fromShell(e) || !st.dlAllowed) return { ok: false };
    const item = dlQueue.get(Number(id));
    if (!item || item.state !== 'login') return { ok: false };
    const cookies = await st.ses.cookies.get({ url: item.href }).catch(() => []);
    const header = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
    if (!header) {
      say('This site has no sign-in cookie to send, so the file was not fetched.');
      return { ok: false };
    }
    dlQueue.remove(item.id);
    dlQueue.add([{ href: item.href, kind: item.kind, name: item.name, path: item.path, host: item.host }], { cookie: header });
    return { ok: true };
  });
  ipcMain.on('nb-line-now', (e) => {
    e.returnValue = { active: Boolean(st.view && e.sender === st.view.webContents && slowActive()) };
  });
  ipcMain.handle('line-set', (e, key, value) => {
    if (!fromShell(e)) return { ok: false };
    return { ok: setLine(key, value) };
  });
  ipcMain.handle('screenshot', async (e) => {
    if (!fromShell(e)) return { ok: false };
    await makeShot(line.shotWindow);
    return { ok: true };
  });
  ipcMain.handle('shot-answer', (e, save) => {
    if (!fromShell(e) || !st.pendingShot || st.pendingShot.busy) return { ok: false };
    answerShot(Boolean(save));
    return { ok: true };
  });
  ipcMain.handle('stop-images', (e) => {
    if (!fromShell(e)) return { ok: false };
    stopImages();
    push();
    return { ok: true };
  });
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
      st.error = null;
      st.view.webContents.loadURL('about:blank').catch(() => {});
      unstick(() => st.view.webContents.loadURL('about:blank').catch(() => {}));
      push();
      return { ok: true };
    }
    load(r.url);
    return { ok: true };
  });
  ipcMain.handle('wipe-all', (e) => {
    if (!fromShell(e)) return { ok: false };
    wipeAll();
    return { ok: true };
  });
  ipcMain.handle('nav', (e, what) => {
    if (!fromShell(e)) return { ok: false };
    const wc = st.view.webContents;
    if (what === 'back' && wc.navigationHistory.canGoBack()) {
      const to = wc.navigationHistory.getEntryAtIndex(wc.navigationHistory.getActiveIndex() - 1);
      wc.navigationHistory.goBack();
      if (to) unstick(() => wc.loadURL(to.url).catch(() => {}));
    } else if (what === 'forward' && wc.navigationHistory.canGoForward()) {
      const to = wc.navigationHistory.getEntryAtIndex(wc.navigationHistory.getActiveIndex() + 1);
      wc.navigationHistory.goForward();
      if (to) unstick(() => wc.loadURL(to.url).catch(() => {}));
    } else if (what === 'reload') retry();
    else if (what === 'stop') wc.stop();
    else if (what === 'home') {
      st.error = null;
      wc.loadURL('about:blank').catch(() => {});
      unstick(() => wc.loadURL('about:blank').catch(() => {}));
    }
    push();
    return { ok: true };
  });
  ipcMain.handle('allow-http', (e) => {
    if (!fromShell(e) || !st.error || st.error.kind !== 'nohttps') return { ok: false };
    st.allowHttp.add(st.error.host);
    load(st.error.url);
    return { ok: true };
  });
  ipcMain.handle('leave-answer', (e, id, go) => {
    if (!fromShell(e) || !st.pendingLeave || st.pendingLeave.id !== id) return { ok: false };
    const { url } = st.pendingLeave;
    st.pendingLeave = null;
    if (go) load(url);
    else push();
    return { ok: true };
  });
  ipcMain.handle('file-answer', (e, id, open) => {
    if (!fromShell(e) || !st.pendingFile || st.pendingFile.id !== id || st.pendingFile.state !== 'ask') return { ok: false };
    answerFile(st.pendingFile, open);
    return { ok: true };
  });
  ipcMain.handle('allow-site', (e) => {
    if (!fromShell(e) || !st.blockedSite) return { ok: false };
    const site = st.blockedSite;
    st.allowedSites.add(site);
    st.blockedSite = '';
    say(`Pop-ups and sign-in cookies are allowed for ${site} until Null Browser closes.`);
    return { ok: true };
  });
  ipcMain.handle('dismiss-popup', (e) => {
    if (!fromShell(e)) return { ok: false };
    st.blockedSite = '';
    push();
    return { ok: true };
  });
  ipcMain.handle('trust-cert', (e) => {
    if (!fromShell(e) || !st.error || st.error.kind !== 'cert' || !st.error.trustable || !st.error.fingerprint) return { ok: false };
    st.trusted.add(`${st.error.host} ${st.error.fingerprint}`);
    load(st.error.url);
    return { ok: true };
  });
  ipcMain.handle('import-bookmarks', async (e) => {
    if (!fromShell(e)) return { ok: false };
    const res = await dialog.showOpenDialog(st.win, {
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
    const have = new Set(st.bookmarks.map((b) => b.url));
    let added = 0;
    let full = false;
    for (const f of found) {
      if (have.has(f.url)) continue;
      if (st.bookmarks.length >= B.MAX_BOOKMARKS) {
        full = true;
        continue;
      }
      have.add(f.url);
      st.bookmarkSeq += 1;
      st.bookmarks.push({ id: st.bookmarkSeq, url: f.url, title: f.title });
      added += 1;
    }
    if (added) say(`${added} bookmark${added === 1 ? '' : 's'} imported${full ? ' (the list is now full)' : ''}.`);
    else say(full ? 'The bookmarks list is full.' : found.length ? 'Those bookmarks were already imported.' : 'No bookmarks were found in that file.');
    push();
    return { ok: true };
  });
  ipcMain.handle('remove-bookmark', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    st.bookmarks = st.bookmarks.filter((b) => b.id !== id);
    push();
    return { ok: true };
  });
  ipcMain.handle('request-fast-js', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    if (Boolean(on) === fastJs) return { ok: true };
    st.pendingJs = Boolean(on);
    push();
    return { ok: true };
  });
  ipcMain.handle('cancel-fast-js', (e) => {
    if (!fromShell(e)) return { ok: false };
    st.pendingJs = null;
    push();
    return { ok: true };
  });
  ipcMain.handle('confirm-fast-js', (e) => {
    if (!fromShell(e) || st.pendingJs === null) return { ok: false };
    app.relaunch({ args: P.relaunchArgv(process.argv.slice(1), st.pendingJs) });
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
  st.win = new BrowserWindow({
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
  st.win.webContents.on('before-input-event', onKey);
  st.win.webContents.on('will-navigate', (e) => e.preventDefault());
  st.win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  st.win.on('resize', layout);
  st.win.on('closed', () => {
    st.win = null;
  });
  createView();
  st.win.webContents.once('did-finish-load', push);
  st.win.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));
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

Object.assign(shared, { MAX_BYTES, REAL_HOME, alive, pageUrl, push, ram, readUserDirs, say });

const primary = app.requestSingleInstanceLock();
if (!primary) {
  rammaid();
  app.exit(0);
}

app.on('second-instance', () => {
  if (alive()) {
    if (st.win.isMinimized()) st.win.restore();
    st.win.focus();
  }
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  app.userAgentFallback = P.chromiumUserAgent(app.userAgentFallback);
  hardenShell(session.defaultSession);
  hardenShell(shellSession());
  st.ses = session.fromPartition(`nullbrowser-${crypto.randomBytes(8).toString('hex')}`);
  hardenPage(st.ses);
  st.ses.protocol.handle(S.SCHEME, (req) => {
    let token = '';
    try {
      token = new URL(req.url).pathname.slice(1);
    } catch {
      token = '';
    }
    const hit = served.get(token);
    if (!hit) return new Response('', { status: 404 });
    return new Response(hit.buf, { headers: { 'content-type': hit.type || 'application/octet-stream', 'access-control-allow-origin': '*', 'cache-control': 'no-store' } });
  });
  st.ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'vieworder.js') });
  st.ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'lessinfo.js') });
  st.ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'noclip.js') });
  register();
  createWindow();
  setInterval(watchdogCpuPoll, W.CPU_IDLE_MS).unref();
});

app.on('window-all-closed', () => app.quit());

app.on('will-quit', () => {
  if (st.ses) {
    st.ses.clearStorageData().catch(() => {});
    st.ses.clearCache().catch(() => {});
  }
});

app.on('quit', rammaid);
process.on('exit', rammaid);
