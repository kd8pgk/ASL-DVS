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

const TOOLBAR = 44;
const BAR = 34;
const GESTURE_MS = 1000;
const LITTERBUG_MS = 3000;
const STUCK_MS = 2000;
const MAX_LITTERBUGS = 3;

let win = null;
let view = null;
let ses = null;
let lastInput = 0;
let commits = 0;
let leaving = 0;
let unsticking = null;
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
let pendingShot = null;
let shotSeq = 0;
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
    line: lineState(),
    shot: pendingShot ? { text: pendingShot.text, busy: pendingShot.busy } : null,
  };
}

function lineRows(l) {
  return (l.open ? 1 : 0) + ((l.active && (l.busy || l.retrying)) || l.ahead ? 1 : 0);
}

function bars() {
  const s = state();
  return (s.notice ? 1 : 0) + (s.ask ? 1 : 0) + (s.popup ? 1 : 0) + (s.jsAsk === null ? 0 : 1) + (s.shot ? 1 : 0) + lineRows(s.line);
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
  if (!leavingSite || leavingSite === nextSite) return;
  clearAhead();
  if (allowedSites.has(leavingSite)) return;
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

const line = { mode: 'auto', images: true, saveData: false, readAhead: false, open: false, shotWindow: false };
const meter = S.createMeter();
const starts = new Map();
const served = new Map();
const ahead = new Map();
const own = new Set();
let lineWasActive = false;
let queue = [];
let current = null;
let report = null;
let seqNo = 0;
let pageGen = 0;
let imgDone = 0;
let imgTotal = 0;
let stopped = false;
let aheadBytes = 0;
let aheadFor = '';
let aheadNote = '';
let aheadJobs = [];
let lineTimer = null;
let askTimer = null;
let reportDeadline = 0;

function pageId() {
  return view && !view.webContents.isDestroyed() ? view.webContents.id : -1;
}

function slowActive() {
  return S.isActive(line.mode, meter.isSlow());
}

function lineState() {
  return {
    mode: line.mode,
    active: slowActive(),
    images: line.images,
    saveData: line.saveData,
    readAhead: line.readAhead,
    open: line.open,
    shotWindow: line.shotWindow,
    rate: meter.rate() ? S.sizeLabel(meter.rate()) : '',
    done: imgDone,
    total: imgTotal,
    busy: Boolean(current && current.kind === 'image') || queue.length > 0,
    retrying: Boolean(current && current.waiting),
    stopped,
    ahead: aheadNote,
  };
}

function linePush() {
  if (lineTimer) return;
  lineTimer = setTimeout(() => {
    lineTimer = null;
    push();
  }, 400);
}

function tellPage(extra = {}) {
  if (!view || view.webContents.isDestroyed()) return;
  try {
    view.webContents.send('nb-line', { active: slowActive(), ...extra });
  } catch {}
}

function lineChanged() {
  const now = slowActive();
  if (now !== lineWasActive) {
    lineWasActive = now;
    tellPage();
    if (!now) {
      const waiting = queue;
      queue = [];
      for (const e of waiting) e.cb({});
    }
  }
  linePush();
}

function askReport(links = false) {
  if (links) return tellPage({ report: true, links: true });
  if (askTimer) return;
  askTimer = setTimeout(() => {
    askTimer = null;
    tellPage({ report: true });
  }, 150);
}

function serve(hit) {
  const token = crypto.randomBytes(16).toString('hex');
  served.set(token, hit);
  return `${S.SCHEME}://i/${token}`;
}

function resetLine() {
  pageGen += 1;
  for (const e of queue) e.cb({ cancel: true });
  queue = [];
  if (current) {
    current.abandon();
    current = null;
  }
  aheadJobs = [];
  report = null;
  stopped = false;
  imgDone = 0;
  imgTotal = 0;
  served.clear();
  linePush();
}

function clearAhead() {
  ahead.clear();
  aheadBytes = 0;
  aheadFor = '';
  aheadNote = '';
  aheadJobs = [];
}

function stopImages() {
  stopped = true;
  for (const e of queue) e.cb({ cancel: true });
  imgDone += queue.length;
  queue = [];
  if (current && current.kind === 'image') {
    current.entry.cb({ cancel: true });
    imgDone += 1;
    current.abandon();
    current = null;
  }
  linePush();
  pump();
}

function holdImage(details, callback) {
  if (stopped) return callback({ cancel: true });
  if (!report && !queue.length && !current) reportDeadline = Date.now() + 600;
  queue.push({ id: details.id, url: details.url, referrer: details.referrer || pageUrl(), cb: callback, seq: (seqNo += 1), gen: pageGen, late: false });
  imgTotal += 1;
  askReport();
  linePush();
  setImmediate(pump);
  return undefined;
}

function fetchBytes(job) {
  const url = job.url;
  let got = 0;
  let total = 0;
  let type = '';
  let validator = '';
  let chunks = [];
  let tries = 0;
  let req = null;
  let dead = false;
  let timer = null;
  own.add(url);
  const finish = (fn) => {
    if (dead) return;
    dead = true;
    own.delete(url);
    if (timer) clearTimeout(timer);
    fn();
  };
  const retry = () => {
    if (dead) return;
    if (req) {
      try {
        req.abort();
      } catch {}
      req = null;
    }
    tries += 1;
    if (tries > S.RETRIES) return finish(() => job.fail());
    job.waiting = true;
    linePush();
    timer = setTimeout(() => {
      timer = null;
      job.waiting = false;
      attempt();
    }, S.backoffMs(tries));
  };
  const attempt = () => {
    if (dead) return;
    const t0 = Date.now();
    let bytesNow = 0;
    try {
      req = net.request({ url, session: ses, useSessionCookies: true, credentials: 'include', redirect: 'follow', method: 'GET' });
    } catch {
      return finish(() => job.fail());
    }
    if (job.referrer) {
      try {
        req.setHeader('Referer', job.referrer);
      } catch {}
    }
    req.setHeader('Accept', job.accept || '*/*');
    if (line.saveData) req.setHeader('Save-Data', 'on');
    if (got > 0) {
      req.setHeader('Range', `bytes=${got}-`);
      if (validator) req.setHeader('If-Range', validator);
    }
    req.on('response', (res) => {
      if (dead) return;
      meter.wait(Date.now() - t0);
      lineChanged();
      const h = res.headers || {};
      const status = res.statusCode;
      if (status === 206 && got > 0) {
        const cr = S.parseContentRange(S.header(h, 'content-range'));
        if (!cr || cr.start !== got) {
          got = 0;
          chunks = [];
          return retry();
        }
        if (cr.total) total = cr.total;
      } else if (status >= 200 && status < 300) {
        got = 0;
        chunks = [];
        const len = Number(S.header(h, 'content-length'));
        total = len > 0 ? len : 0;
      } else if (status >= 500 || status === 408 || status === 429) {
        return retry();
      } else {
        return finish(() => job.fail());
      }
      if (total > job.max) return finish(() => job.fail());
      type = S.header(h, 'content-type') || type;
      validator = S.header(h, 'etag') || S.header(h, 'last-modified') || validator;
      res.on('data', (c) => {
        if (dead) return;
        chunks.push(c);
        got += c.length;
        bytesNow += c.length;
        if (got > job.max) {
          try {
            req.abort();
          } catch {}
          finish(() => job.fail());
        }
      });
      res.on('end', () => {
        if (dead) return;
        meter.transfer(bytesNow, Date.now() - t0);
        lineChanged();
        if (total && got < total) return retry();
        const buf = Buffer.concat(chunks);
        finish(() => job.done({ buf, type }));
      });
      res.on('aborted', retry);
      res.on('error', retry);
    });
    req.on('error', retry);
    req.end();
  };
  job.abandon = () => finish(() => {
    if (req) {
      try {
        req.abort();
      } catch {}
    }
  });
  attempt();
}

function pump() {
  if (current) return;
  if (queue.length && !report && Date.now() < reportDeadline) {
    setTimeout(pump, reportDeadline - Date.now() + 10);
    return;
  }
  if (queue.length) {
    const entry = S.pickNext(queue, report);
    queue = queue.filter((e) => e !== entry);
    const gen = pageGen;
    const job = {
      kind: 'image',
      url: entry.url,
      referrer: entry.referrer,
      accept: 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
      max: S.MAX_IMAGE_BYTES,
      entry,
      waiting: false,
      done(hit) {
        current = null;
        if (gen === pageGen) {
          entry.cb({ redirectURL: serve(hit) });
          imgDone += 1;
        }
        linePush();
        pump();
      },
      fail() {
        current = null;
        if (gen === pageGen) {
          if (!entry.late) {
            entry.late = true;
            queue.push(entry);
          } else {
            entry.cb({ cancel: true });
            imgDone += 1;
          }
        }
        linePush();
        pump();
      },
    };
    current = job;
    linePush();
    fetchBytes(job);
    return;
  }
  if (aheadJobs.length) {
    const next = aheadJobs.shift();
    current = next;
    fetchBytes(next);
    return;
  }
  maybeReadAhead();
}

function maybeReadAhead() {
  if (!line.readAhead || current || queue.length || stopped || !line.images) return;
  const wc = view && !view.webContents.isDestroyed() ? view.webContents : null;
  if (!wc || wc.isLoading() || !pageUrl() || aheadFor === pageUrl()) return;
  aheadFor = pageUrl();
  askReport(true);
}

function readAheadFrom(nextUrl) {
  if (!nextUrl || !line.readAhead) return;
  const gen = pageGen;
  aheadNote = 'Reading ahead the next page…';
  linePush();
  const pageJob = {
    kind: 'ahead',
    url: nextUrl,
    referrer: pageUrl(),
    accept: 'text/html,application/xhtml+xml,*/*;q=0.8',
    max: 4 * 1024 * 1024,
    waiting: false,
    done(hit) {
      current = null;
      if (gen === pageGen) {
        const urls = S.imageUrlsIn(hit.buf.toString('utf8'), nextUrl).filter((u) => !ahead.has(u));
        for (const u of urls) {
          aheadJobs.push({
            kind: 'ahead',
            url: u,
            referrer: nextUrl,
            accept: 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            max: S.MAX_IMAGE_BYTES,
            waiting: false,
            done(img) {
              current = null;
              if (aheadBytes + img.buf.length <= S.READ_AHEAD_BYTES) {
                ahead.set(u, img);
                aheadBytes += img.buf.length;
              }
              aheadNote = aheadJobs.length ? `Reading ahead: ${ahead.size} image(s) of the next page ready` : `Next page ready (${ahead.size} image(s))`;
              linePush();
              pump();
            },
            fail() {
              current = null;
              pump();
            },
          });
        }
        aheadNote = urls.length ? 'Reading ahead the next page…' : 'Next page ready';
      }
      linePush();
      pump();
    },
    fail() {
      current = null;
      aheadNote = '';
      linePush();
      pump();
    },
  };
  aheadJobs.unshift(pageJob);
  pump();
}

function onReport(e, r) {
  if (!view || e.sender !== view.webContents || e.senderFrame !== e.sender.mainFrame) return;
  if (!r || typeof r !== 'object') return;
  const items = Array.isArray(r.items) ? r.items.slice(0, 500).filter((i) => i && typeof i.src === 'string').map((i) => ({ src: i.src.slice(0, 4096), top: Number(i.top) || 0, x: Number(i.x) || 0, w: Number(i.w) || 0, h: Number(i.h) || 0 })) : [];
  report = { vh: Number(r.vh) || 0, vw: Number(r.vw) || 0, items };
  setImmediate(pump);
  if (Array.isArray(r.links) && line.readAhead && aheadFor === pageUrl()) {
    const links = r.links.slice(0, 300).filter((l) => l && typeof l.href === 'string').map((l) => ({ rel: String(l.rel || '').slice(0, 100), href: l.href.slice(0, 4096), text: String(l.text || '').slice(0, 40) }));
    readAheadFrom(S.pickNextLink(links, pageUrl()));
  }
}

function setLine(key, value) {
  if (key === 'mode' && ['auto', 'on', 'off'].includes(value)) line.mode = value;
  else if (key === 'images' && typeof value === 'boolean') {
    line.images = value;
    if (!value) stopImages();
    else {
      stopped = false;
      tellPage({ reloadImages: true });
    }
  } else if ((key === 'saveData' || key === 'readAhead' || key === 'open' || key === 'shotWindow') && typeof value === 'boolean') line[key] = value;
  else return false;
  if (key === 'readAhead' && value) {
    aheadFor = '';
    setImmediate(pump);
  }
  lineChanged();
  push();
  return true;
}

function shotDir() {
  const dir = path.join(ram.sub.files, 'quarantine');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function discardShot() {
  if (!pendingShot) return;
  const file = pendingShot.file;
  pendingShot = null;
  try {
    fs.rmSync(file, { force: true });
    fs.rmdirSync(path.dirname(file));
  } catch {}
}

async function printPage(wc) {
  return wc.printToPDF({ printBackground: true, pageSize: 'A4' });
}

async function windowPdf() {
  const img = await win.webContents.capturePage();
  const size = img.getSize();
  const png = img.toPNG().toString('base64');
  const html = `<!doctype html><html><head><style>@page{margin:0}html,body{margin:0;padding:0}img{display:block;width:${size.width}px;height:${size.height}px}</style></head><body><img src="data:image/png;base64,${png}"></body></html>`;
  const shot = new BrowserWindow({ show: false, width: size.width, height: size.height, webPreferences: { session: ses, sandbox: true, contextIsolation: true, nodeIntegration: false, webviewTag: false, plugins: false, spellcheck: false } });
  try {
    await shot.loadURL(`data:text/html;base64,${Buffer.from(html).toString('base64')}`);
    return await shot.webContents.printToPDF({ printBackground: true, pageSize: { width: size.width / 96, height: size.height / 96 } });
  } finally {
    shot.destroy();
  }
}

async function makeShot(withWindow) {
  if (pendingShot || !alive() || !view || view.webContents.isDestroyed()) return;
  shotSeq += 1;
  const file = path.join(shotDir(), `shot-${shotSeq}.pdf`);
  pendingShot = { id: shotSeq, file, sha: '', text: 'Making the screenshot…', busy: true };
  push();
  let buf;
  try {
    buf = withWindow ? await windowPdf() : await printPage(view.webContents);
  } catch {
    buf = null;
  }
  if (!buf) {
    pendingShot = null;
    say('The screenshot could not be made.');
    return;
  }
  const sha = SH.sha256(buf);
  fs.writeFileSync(file, buf, { mode: 0o600 });
  const back = fs.readFileSync(file);
  const check = SH.checkPdf(back, sha);
  if (!check.ok) {
    discardShot();
    say(`The screenshot was not saved: ${check.reason}.`);
    return;
  }
  pendingShot = { id: shotSeq, file, sha, text: `Save the screenshot (PDF, ${Math.max(1, Math.round(back.length / 1024))} KB, ${check.pages} page${check.pages === 1 ? '' : 's'}) to your Downloads folder?`, busy: false };
  push();
}

function answerShot(save) {
  const rec = pendingShot;
  if (!save) {
    discardShot();
    push();
    return;
  }
  pendingShot = { ...rec, text: 'Saving…', busy: true };
  push();
  try {
    const buf = fs.readFileSync(rec.file);
    const check = SH.checkPdf(buf, rec.sha);
    if (!check.ok) throw new Error(check.reason);
    const dir = SH.downloadsFromUserDirs(readUserDirs(), REAL_HOME);
    fs.mkdirSync(dir, { recursive: true });
    const name = SH.uniqueName(SH.shotName(new Date()), (n) => fs.existsSync(path.join(dir, n)));
    if (!name) throw new Error('no free file name');
    fs.writeFileSync(path.join(dir, name), buf, { flag: 'wx', mode: 0o644 });
    discardShot();
    say(`Saved ${name} to your Downloads folder.`);
  } catch (err) {
    discardShot();
    say(`The screenshot was not saved: ${err.message}.`);
  }
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
      const up = P.httpsUpgrade(details.url, allowHttp);
      if (up) {
        upgraded.add(up);
        return callback({ redirectURL: up });
      }
    } else if (!(details.webContentsId === undefined && own.has(details.url))) {
      watchdog.noteSubresource(P.siteOf(P.hostOf(topUrlOf(details))), P.hostOf(details.url));
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
  s.webRequest.onErrorOccurred((details) => {
    starts.delete(details.id);
    const before = queue.length;
    queue = queue.filter((e) => e.id !== details.id || e.gen !== pageGen);
    if (queue.length !== before) {
      imgDone += before - queue.length;
      linePush();
    }
  });
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

let langCache = '';

function pageLang() {
  if (!langCache) langCache = P.firstLanguage(app.getPreferredSystemLanguages ? app.getPreferredSystemLanguages() : [], app.getLocale());
  return langCache;
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

function unstick(redo) {
  const wc = view.webContents;
  const id = ++leaving;
  const seen = commits;
  let answered = false;
  const frame = wc.mainFrame;
  if (!frame) return;
  frame.executeJavaScript('1').then(() => { answered = true; }, () => { answered = true; });
  setTimeout(() => {
      if (answered || id !== leaving || seen !== commits || wc.isDestroyed() || wc.isCrashed()) return;
      unsticking = redo;
    wc.forcefullyCrashRenderer();
  }, STUCK_MS).unref();
}

function load(url) {
  error = null;
  pendingCert = null;
  view.webContents.loadURL(url).catch(() => {});
  unstick(() => view.webContents.loadURL(url).catch(() => {}));
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
  if (input.type === 'mouseDown' || input.type === 'keyDown') lastInput = Date.now();
  if (clipKey(input)) {
    event.preventDefault();
    return;
  }
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
      nodeIntegrationInSubFrames: true,
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
  wc.on('did-stop-loading', () => setImmediate(pump));
  wc.on('did-start-navigation', (ev, url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) {
      purgeIfSiteChanged(url);
      resetLine();
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
  wc.on('did-navigate', () => {
    commits += 1;
  });
  wc.on('render-process-gone', (ev, details) => {
    if (unsticking) {
      const redo = unsticking;
      unsticking = null;
      redo();
      return;
    }
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
  return alive() && e.sender === win.webContents;
}

let shellReady = false;

function register() {
  ipcMain.on('nb-report', onReport);
  ipcMain.on('nb-line-now', (e) => {
    e.returnValue = { active: Boolean(view && e.sender === view.webContents && slowActive()) };
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
    if (!fromShell(e) || !pendingShot || pendingShot.busy) return { ok: false };
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
      error = null;
      view.webContents.loadURL('about:blank').catch(() => {});
      unstick(() => view.webContents.loadURL('about:blank').catch(() => {}));
      push();
      return { ok: true };
    }
    load(r.url);
    return { ok: true };
  });
  ipcMain.handle('nav', (e, what) => {
    if (!fromShell(e)) return { ok: false };
    const wc = view.webContents;
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
      error = null;
      wc.loadURL('about:blank').catch(() => {});
      unstick(() => wc.loadURL('about:blank').catch(() => {}));
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
  app.userAgentFallback = P.chromiumUserAgent(app.userAgentFallback);
  hardenShell(session.defaultSession);
  hardenShell(shellSession());
  ses = session.fromPartition(`nullbrowser-${crypto.randomBytes(8).toString('hex')}`);
  hardenPage(ses);
  ses.protocol.handle(S.SCHEME, (req) => {
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
  ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'vieworder.js') });
  ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'lessinfo.js') });
  ses.registerPreloadScript({ type: 'frame', filePath: path.join(__dirname, 'noclip.js') });
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
