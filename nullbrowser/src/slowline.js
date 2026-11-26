const crypto = require('node:crypto');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog, net, protocol } = require('electron');
const S = require('./slow');
const { st } = require('./state');
const shared = require('./ctx');

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
  return st.view && !st.view.webContents.isDestroyed() ? st.view.webContents.id : -1;
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
    shared.push();
  }, 400);
}

function tellPage(extra = {}) {
  if (!st.view || st.view.webContents.isDestroyed()) return;
  try {
    st.view.webContents.send('nb-line', { active: slowActive(), ...extra });
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
  st.dlList = [];
  st.dlWarn = false;
  st.dlPanelOpen = false;
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
  queue.push({ id: details.id, url: details.url, referrer: details.referrer || shared.pageUrl(), cb: callback, seq: (seqNo += 1), gen: pageGen, late: false });
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
      req = net.request({ url, session: st.ses, useSessionCookies: true, credentials: 'include', redirect: 'follow', method: 'GET' });
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
  const wc = st.view && !st.view.webContents.isDestroyed() ? st.view.webContents : null;
  if (!wc || wc.isLoading() || !shared.pageUrl() || aheadFor === shared.pageUrl()) return;
  aheadFor = shared.pageUrl();
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
    referrer: shared.pageUrl(),
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
  if (!st.view || e.sender !== st.view.webContents || e.senderFrame !== e.sender.mainFrame) return;
  if (!r || typeof r !== 'object') return;
  const items = Array.isArray(r.items) ? r.items.slice(0, 500).filter((i) => i && typeof i.src === 'string').map((i) => ({ src: i.src.slice(0, 4096), top: Number(i.top) || 0, x: Number(i.x) || 0, w: Number(i.w) || 0, h: Number(i.h) || 0 })) : [];
  report = { vh: Number(r.vh) || 0, vw: Number(r.vw) || 0, items };
  setImmediate(pump);
  if (Array.isArray(r.links) && line.readAhead && aheadFor === shared.pageUrl()) {
    const links = r.links.slice(0, 300).filter((l) => l && typeof l.href === 'string').map((l) => ({ rel: String(l.rel || '').slice(0, 100), href: l.href.slice(0, 4096), text: String(l.text || '').slice(0, 40) }));
    readAheadFrom(S.pickNextLink(links, shared.pageUrl()));
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
  shared.push();
  return true;
}

function lineErrored(details) {
  starts.delete(details.id);
  const before = queue.length;
  queue = queue.filter((e) => e.id !== details.id || e.gen !== pageGen);
  if (queue.length !== before) {
    imgDone += before - queue.length;
    linePush();
  }
}

module.exports = { line, meter, starts, served, ahead, own, pageId, slowActive, lineState, linePush, tellPage, lineChanged, askReport, serve, resetLine, clearAhead, stopImages, holdImage, fetchBytes, pump, maybeReadAhead, readAheadFrom, onReport, setLine, lineErrored };
