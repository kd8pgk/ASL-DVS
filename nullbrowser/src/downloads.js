const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog, net, protocol } = require('electron');
const P = require('./policy');
const F = require('./files');
const S = require('./slow');
const SH = require('./shot');
const DL = require('./download');
const { st } = require('./state');
const shared = require('./ctx');
const { own } = require('./slowline');

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
    if (err) shared.say(`No app on this computer could open ${path.basename(file)}.`);
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
    shared.say(`${rec.name} is not really ${rec.kind === 'pdf' ? 'a PDF' : rec.kind}, so it was not opened.`);
    const from = (() => {
      try {
        return rec.item.getURL();
      } catch {
        return '';
      }
    })();
    st.watchdog.noteFakeFile(P.siteOf(P.hostOf(from || shared.pageUrl())));
    return;
  }
  openFile(rec.file);
  shared.push();
}

function endFile(rec) {
  if (st.pendingFile === rec) st.pendingFile = null;
  shared.push();
}

function finishFile(rec, st) {
  rec.done = st;
  if (st !== 'completed') {
    rammaidFile(rec.file);
    if (rec.tooBig) shared.say(`${rec.name} is too big to open from memory.`);
    else if (rec.answer === true) shared.say(`${rec.name} could not be fetched.`);
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
  shared.push();
}

function onDownload(event, item) {
  const name = F.safeName(item.getFilename());
  const kind = F.classify(item.getMimeType(), name);
  const total = item.getTotalBytes();
  if (!kind) {
    item.cancel();
    shared.say('Downloads are off in Null Browser.');
    return;
  }
  if (total > shared.MAX_BYTES) {
    item.cancel();
    shared.say(`${name} is too big to open from memory.`);
    return;
  }
  if (st.pendingFile) {
    item.cancel();
    shared.say('Answer the question about the other file first.');
    return;
  }
  st.fileSeq += 1;
  const rec = { id: st.fileSeq, item, file: path.join(shared.ram.sub.files, `${st.fileSeq}-${name}`), kind, name, text: F.question(name, kind, total), state: 'ask' };
  item.setSavePath(rec.file);
  item.on('updated', () => {
    if (rec.tooBig || item.getReceivedBytes() <= shared.MAX_BYTES) return;
    rec.tooBig = true;
    item.cancel();
  });
  item.once('done', (e, st) => finishFile(rec, st));
  st.pendingFile = rec;
  shared.push();
}

function dlDir() {
  const dir = path.join(shared.ram.sub.files, 'dlq');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function fsyncDir(dir) {
  try {
    const fd = fs.openSync(dir, 'r');
    try {
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
  } catch {}
}

function saveAtomic(dir, name, bytes, sha) {
  fs.mkdirSync(dir, { recursive: true });
  const tmp = path.join(dir, `.nb-partial-${crypto.randomBytes(6).toString('hex')}`);
  try {
    const fd = fs.openSync(tmp, 'wx', 0o644);
    try {
      let off = 0;
      while (off < bytes.length) off += fs.writeSync(fd, bytes, off, bytes.length - off);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    if (DL.sha256(fs.readFileSync(tmp)) !== sha) throw new Error('the file changed while it was saved');
    let candidate = DL.uniqueName(name, (n) => fs.existsSync(path.join(dir, n)));
    for (let i = 0; i < 50 && candidate; i += 1) {
      try {
        fs.linkSync(tmp, path.join(dir, candidate));
        fsyncDir(dir);
        return candidate;
      } catch (err) {
        if (err.code === 'EEXIST') {
          candidate = DL.uniqueName(candidate, (n) => fs.existsSync(path.join(dir, n)));
          continue;
        }
        if (err.code === 'EPERM' || err.code === 'ENOTSUP' || err.code === 'EXDEV' || err.code === 'EOPNOTSUPP') throw new Error('this folder does not support safe saves');
        throw err;
      }
    }
    throw new Error('no free file name');
  } finally {
    try {
      fs.rmSync(tmp, { force: true });
    } catch {}
  }
}

function fetchFile(item, cookie) {
  return new Promise((resolve) => {
    const chunks = [];
    let got = 0;
    let expected = -1;
    let validator = '';
    let serverName = '';
    let url = item.href;
    let hops = 0;
    let tries = 0;
    let settled = false;
    let req = null;
    let timer = null;
    const finish = (r) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve(r);
    };
    const retryFetch = () => {
      if (settled) return;
      tries += 1;
      if (tries > DL.MAX_TRIES) {
        finish({ ok: false, reason: 'the line dropped too many times' });
        return;
      }
      timer = setTimeout(start, W_BACKOFF(tries));
    };
    const start = () => {
      timer = null;
      if (settled) return;
      try {
        req = net.request({ method: 'GET', url, session: st.ses, credentials: 'omit', redirect: 'manual' });
      } catch {
        finish({ ok: false, reason: 'the address could not be opened' });
        return;
      }
      req.setHeader('Accept', '*/*');
      if (cookie) req.setHeader('Cookie', cookie);
      if (got > 0) {
        req.setHeader('Range', `bytes=${got}-`);
        if (validator) req.setHeader('If-Range', validator);
      }
      req.on('redirect', (statusCode, method, redirectUrl) => {
        let next;
        try {
          next = new URL(redirectUrl);
        } catch {
          finish({ ok: false, reason: 'the site sent a bad redirect' });
          try {
            req.abort();
          } catch {}
          return;
        }
        const was = new URL(url).protocol;
        hops += 1;
        if (hops > 5 || (next.protocol !== 'https:' && next.protocol !== 'http:') || (was === 'https:' && next.protocol === 'http:')) {
          finish({ ok: false, reason: 'the redirect is not followed' });
          try {
            req.abort();
          } catch {}
          return;
        }
        url = next.href;
        req.followRedirect();
      });
      req.on('response', (res) => {
        if (settled) return;
        const code = res.statusCode;
        const hdr = (name) => {
          const v = res.headers[name];
          return v === undefined ? '' : String([].concat(v)[0]);
        };
        if (code === 401 || code === 403) {
          finish(cookie ? { ok: false, reason: 'the sign-in was refused' } : { ok: false, login: true, reason: 'This site asks for a sign-in.' });
          return;
        }
        if (code === 206 && got > 0) {
          const m = /^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/i.exec(hdr('content-range').trim());
          if (!m || Number(m[1]) !== got) {
            got = 0;
            chunks.length = 0;
          } else if (m[3] !== '*') {
            expected = Number(m[3]);
          }
        } else if (code >= 200 && code < 300) {
          got = 0;
          chunks.length = 0;
          const len = Number(hdr('content-length'));
          expected = len > 0 ? len : -1;
        } else if (code >= 500 || code === 408 || code === 429) {
          retryFetch();
          return;
        } else {
          finish({ ok: false, reason: `the site answered ${code}` });
          return;
        }
        const cd = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(hdr('content-disposition'));
        if (cd) {
          try {
            serverName = decodeURIComponent(cd[1]);
          } catch {
            serverName = cd[1];
          }
        }
        validator = hdr('etag') || hdr('last-modified') || validator;
        res.on('data', (c) => {
          if (settled) return;
          got += c.length;
          if (got > DL.MAX_FILE_BYTES) {
            finish({ ok: false, reason: 'the file is too big' });
            try {
              req.abort();
            } catch {}
            return;
          }
          chunks.push(c);
        });
        res.on('end', () => {
          if (settled) return;
          if (expected > 0 && got < expected) {
            retryFetch();
            return;
          }
          finish({ ok: true, buf: Buffer.concat(chunks), serverName });
        });
        res.on('aborted', retryFetch);
        res.on('error', retryFetch);
      });
      req.on('error', retryFetch);
      req.end();
    };
    item.abort = () => {
      finish({ ok: false, reason: 'cancelled' });
      try {
        if (req) req.abort();
      } catch {}
    };
    start();
  });
}

const W_BACKOFF = (attempt) => S.backoffMs(attempt);

async function runDownload(item, ctx) {
  if (!st.dlAllowed) return { ok: false, reason: 'Downloads are off.' };
  const cookie = item.cookie || '';
  const got = await fetchFile(item, cookie);
  item.cookie = '';
  if (!got.ok) return got;
  if (ctx.batchBytes + got.buf.length > ctx.batchLimit) return { ok: false, reason: 'the 2 GB limit for one batch was reached', bytes: got.buf.length };
  const sha = DL.sha256(got.buf);
  const file = path.join(dlDir(), `${item.id}-${crypto.randomBytes(4).toString('hex')}.part`);
  try {
    fs.writeFileSync(file, got.buf, { mode: 0o600, flag: 'wx' });
    const back = fs.readFileSync(file);
    const check = DL.checkDownload(item.kind, back, sha);
    if (!check.ok) return { ok: false, reason: check.reason, bytes: got.buf.length };
    const dest = SH.downloadsFromUserDirs(shared.readUserDirs(), shared.REAL_HOME);
    const name = saveAtomic(dest, DL.safeName(got.serverName || item.name, item.kind), back, sha);
    return { ok: true, saved: name, bytes: got.buf.length };
  } catch (err) {
    return { ok: false, reason: err.message || 'could not be saved', bytes: got.buf.length };
  } finally {
    try {
      fs.rmSync(file, { force: true });
      fs.rmdirSync(path.dirname(file));
    } catch {}
  }
}

const FILE_SCAN = DL.scanScript();

const PROBE_BYTES = 512;
const PROBE_MS = 5000;
const PROBE_PARALLEL = 4;
const probesActive = new Set();
const probesQueued = [];
const probesInflight = new Set();
let probesRunning = 0;
let rescanTimer = null;

function sameDoc(a, b) {
  return String(a || '').split('#')[0] === String(b || '').split('#')[0];
}

function probeFile(href) {
  return new Promise((resolve) => {
    const chunks = [];
    let got = 0;
    let url = href;
    let hops = 0;
    let settled = false;
    let req = null;
    let timer = null;
    const held = new Set();
    const hold = (u) => {
      own.add(u);
      held.add(u);
    };
    const finish = (kind) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      for (const u of held) own.delete(u);
      probesActive.delete(stop);
      try {
        if (req) req.abort();
      } catch {}
      resolve(kind);
    };
    const stop = () => finish(null);
    probesActive.add(stop);
    timer = setTimeout(stop, PROBE_MS);
    hold(url);
    try {
      req = net.request({ method: 'GET', url, session: st.ses, credentials: 'omit', redirect: 'manual' });
    } catch {
      finish(null);
      return;
    }
    req.setHeader('Accept', '*/*');
    req.setHeader('Range', `bytes=0-${PROBE_BYTES - 1}`);
    req.on('redirect', (code, method, redirectUrl) => {
      let next;
      try {
        next = new URL(redirectUrl);
      } catch {
        finish('');
        return;
      }
      hops += 1;
      if (hops > 5 || (next.protocol !== 'https:' && next.protocol !== 'http:') || (new URL(url).protocol === 'https:' && next.protocol === 'http:')) {
        finish('');
        return;
      }
      url = next.href;
      hold(url);
      req.followRedirect();
    });
    req.on('response', (res) => {
      if (settled) return;
      if (res.statusCode !== 200 && res.statusCode !== 206) {
        finish('');
        return;
      }
      const ct = String([].concat(res.headers['content-type'] || '')[0] || '');
      if (/^(text|application\/(json|xml|javascript|xhtml))/i.test(ct.trim())) {
        finish('');
        return;
      }
      res.on('data', (c) => {
        if (settled) return;
        chunks.push(c);
        got += c.length;
        if (got >= PROBE_BYTES) finish(DL.kindOfProbe(Buffer.concat(chunks).subarray(0, PROBE_BYTES), ct));
      });
      res.on('end', () => finish(DL.kindOfProbe(Buffer.concat(chunks), ct)));
      res.on('error', stop);
      res.on('aborted', stop);
    });
    req.on('error', stop);
    req.end();
  });
}

function cancelProbes() {
  probesQueued.length = 0;
  for (const stop of [...probesActive]) stop();
  st.dlProbing = 0;
}

function mergeList() {
  const entries = new Map(st.dlKnown.map((e) => [e.href, e]));
  for (const href of st.dlCands) {
    const e = st.dlProbed.get(href);
    if (e && !entries.has(href)) entries.set(href, e);
  }
  const { list, total } = DL.sortCap(entries.values());
  st.dlList = list;
  st.dlTotal = total;
}

function pumpProbes(epoch) {
  while (probesRunning < PROBE_PARALLEL && probesQueued.length) {
    const href = probesQueued.shift();
    probesRunning += 1;
    probesInflight.add(href);
    probeFile(href).then((kind) => {
      probesRunning -= 1;
      probesInflight.delete(href);
      if (epoch === st.dlSeq) {
        if (kind !== null) st.dlProbed.set(href, kind ? DL.entryFor(href, kind) : null);
        st.dlProbing = probesQueued.length + probesRunning;
        mergeList();
        shared.push();
      }
      pumpProbes(epoch);
    });
  }
}

function startProbes(epoch) {
  probesQueued.length = 0;
  for (const h of st.dlCands) if (!st.dlProbed.has(h) && !probesInflight.has(h)) probesQueued.push(h);
  st.dlProbing = probesQueued.length + probesInflight.size;
  pumpProbes(epoch);
}

function resetDownloads() {
  st.dlSeq += 1;
  cancelProbes();
  if (rescanTimer) clearTimeout(rescanTimer);
  rescanTimer = null;
  st.dlList = [];
  st.dlKnown = [];
  st.dlCands = [];
  st.dlProbed = new Map();
  st.dlListFor = '';
  st.dlTotal = 0;
  st.dlSkipped = 0;
  st.dlScanError = '';
}

async function scanFiles(opts = {}) {
  if (!st.view || st.view.webContents.isDestroyed()) return;
  const probe = opts.probe === undefined ? st.dlPanelOpen && st.dlAllowed : opts.probe;
  const url = shared.pageUrl();
  st.dlScanSeq += 1;
  const seq = st.dlScanSeq;
  const epoch = st.dlSeq;
  if (!url || !/^https?:/.test(url)) {
    resetDownloads();
    shared.push();
    return;
  }
  const wc = st.view.webContents;
  const frames = [];
  try {
    for (const f of wc.mainFrame.framesInSubtree) {
      if (f.detached) continue;
      const isMain = f === wc.mainFrame;
      if (!isMain && (!f.url || f.url === 'about:blank')) continue;
      frames.push({ frame: f, main: isMain });
    }
  } catch {
    frames.length = 0;
  }
  if (!frames.length) frames.push({ frame: wc.mainFrame, main: true });
  const got = await DL.collectFrames(frames, (f) => f.frame.executeJavaScript(FILE_SCAN, false));
  if (seq !== st.dlScanSeq || epoch !== st.dlSeq || !sameDoc(shared.pageUrl(), url)) return;
  if (got.mainFailed) st.dlScanError = 'page';
  else if (got.failed) st.dlScanError = `frames:${got.failed}`;
  else st.dlScanError = '';
  const built = DL.buildScan(got.items, url);
  st.dlKnown = built.list;
  st.dlCands = built.candidates;
  st.dlSkipped = built.skipped;
  st.dlListFor = url;
  mergeList();
  if (!probe) {
    st.dlProbing = 0;
  } else {
    startProbes(epoch);
  }
  shared.push();
}

function scheduleRescan() {
  if (!st.dlPanelOpen || !st.dlAllowed) return;
  if (rescanTimer) clearTimeout(rescanTimer);
  rescanTimer = setTimeout(() => {
    rescanTimer = null;
    scanFiles({ probe: true });
  }, 500);
}

function entryOf(href) {
  if (!sameDoc(st.dlListFor, shared.pageUrl())) return null;
  return st.dlList.find((x) => x.href === href) || null;
}

function listIsCurrent() {
  return Boolean(st.dlListFor) && sameDoc(st.dlListFor, shared.pageUrl());
}

module.exports = { rammaidFile, openFile, checkAndOpen, endFile, finishFile, answerFile, onDownload, dlDir, fsyncDir, saveAtomic, fetchFile, W_BACKOFF, runDownload, FILE_SCAN, scanFiles, scheduleRescan, cancelProbes, resetDownloads, listIsCurrent, probeFile, entryOf };
