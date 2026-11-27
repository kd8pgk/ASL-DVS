const path = require('node:path');
const crypto = require('node:crypto');

const MAX_FILE_BYTES = 512 * 1024 * 1024;
const MAX_BATCH_FILES = 200;
const MAX_BATCH_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_TRIES = 5;

const KINDS = {
  pdf: { ext: '.pdf', mimes: ['application/pdf'], label: 'PDF' },
  mp3: { ext: '.mp3', mimes: ['audio/mpeg', 'audio/mp3'], label: 'MP3' },
  wav: { ext: '.wav', mimes: ['audio/wav', 'audio/x-wav', 'audio/wave'], label: 'WAV' },
  webm: { ext: '.webm', mimes: ['video/webm', 'audio/webm'], label: 'WebM' },
  mp4: { ext: '.mp4', mimes: ['video/mp4'], label: 'MP4' },
  jpg: { ext: '.jpg', mimes: ['image/jpeg'], label: 'JPG' },
  mpeg: { ext: '.mpeg', mimes: ['video/mpeg'], label: 'MPEG' },
  webp: { ext: '.webp', mimes: ['image/webp'], label: 'WebP' },
};

const EXT_KIND = {
  '.pdf': 'pdf',
  '.mp3': 'mp3',
  '.wav': 'wav',
  '.webm': 'webm',
  '.mp4': 'mp4',
  '.jpg': 'jpg',
  '.jpeg': 'jpg',
  '.mpeg': 'mpeg',
  '.mpg': 'mpeg',
  '.webp': 'webp',
};

const DYNAMIC_EXTS = ['php', 'asp', 'aspx', 'jsp', 'cgi', 'do', 'action', 'pl', 'py', 'cfm', 'ashx', 'axd'];
const MAX_PROBES = 60;
const MAX_LIST = MAX_BATCH_FILES;

function kindOfPath(pathname) {
  const ext = path.extname(String(pathname || '')).toLowerCase();
  return EXT_KIND[ext] || '';
}

function kindOfMime(mime) {
  const m = String(mime || '').split(';')[0].trim().toLowerCase();
  if (!m) return '';
  for (const [kind, k] of Object.entries(KINDS)) if (k.mimes.includes(m)) return kind;
  return '';
}

function kindOfQuery(u) {
  for (const v of u.searchParams.values()) {
    const k = kindOfPath(v.split(/[?#]/)[0]);
    if (k) return k;
  }
  return '';
}

function kindOfHint(l, u) {
  return kindOfPath(u.pathname) || kindOfPath(String(l.name || '')) || kindOfMime(l.type) || kindOfQuery(u);
}

function kindOfHead(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 12) return '';
  if (startsWith(buf, Buffer.from('%PDF-'))) return 'pdf';
  if (startsWith(buf, [0x1a, 0x45, 0xdf, 0xa3])) return buf.subarray(0, 64).toString('latin1').includes('webm') ? 'webm' : '';
  if (startsWith(buf, Buffer.from('ftyp'), 4)) return 'mp4';
  if (startsWith(buf, Buffer.from('RIFF'))) {
    if (startsWith(buf, Buffer.from('WAVE'), 8)) return 'wav';
    if (startsWith(buf, Buffer.from('WEBP'), 8)) return 'webp';
    return '';
  }
  if (startsWith(buf, [0xff, 0xd8, 0xff])) return 'jpg';
  if (startsWith(buf, [0, 0, 1, 0xba]) || startsWith(buf, [0, 0, 1, 0xb3])) return 'mpeg';
  if (startsWith(buf, Buffer.from('ID3'))) return 'mp3';
  if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return 'mp3';
  return '';
}

function startsWith(buf, bytes, at = 0) {
  if (buf.length < at + bytes.length) return false;
  for (let i = 0; i < bytes.length; i += 1) if (buf[at + i] !== bytes[i]) return false;
  return true;
}

function mp4Boxes(buf) {
  const seen = new Set();
  let at = 0;
  while (at + 8 <= buf.length) {
    let size = buf.readUInt32BE(at);
    const type = buf.toString('latin1', at + 4, at + 8);
    if (size === 1) {
      if (at + 16 > buf.length) return null;
      size = Number(buf.readBigUInt64BE(at + 8));
    } else if (size === 0) {
      size = buf.length - at;
    }
    if (size < 8 || at + size > buf.length) return null;
    seen.add(type);
    at += size;
  }
  if (at !== buf.length) return null;
  return seen;
}

function structureOk(kind, buf) {
  if (!buf || buf.length < 16) return { ok: false, reason: 'the file is too small' };
  if (kind === 'pdf') {
    if (!startsWith(buf, Buffer.from('%PDF-'))) return { ok: false, reason: 'it does not start like a PDF' };
    if (!buf.subarray(Math.max(0, buf.length - 1024)).toString('latin1').includes('%%EOF')) return { ok: false, reason: 'it does not end like a PDF' };
    const pages = (buf.toString('latin1').match(/\/Type\s*\/Page(?!s)/g) || []).length;
    if (pages < 1) return { ok: false, reason: 'it has no readable page' };
    return { ok: true };
  }
  if (kind === 'mp3') {
    let at = 0;
    if (startsWith(buf, Buffer.from('ID3'))) {
      const s = buf.subarray(6, 10);
      if (s.some((b) => b & 0x80)) return { ok: false, reason: 'its tag is damaged' };
      at = 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]);
    }
    if (at + 2 > buf.length || buf[at] !== 0xff || (buf[at + 1] & 0xe0) !== 0xe0) return { ok: false, reason: 'it has no audio frames' };
    return { ok: true };
  }
  if (kind === 'wav') {
    if (!startsWith(buf, Buffer.from('RIFF')) || !startsWith(buf, Buffer.from('WAVE'), 8)) return { ok: false, reason: 'it is not a WAV file' };
    if (buf.readUInt32LE(4) + 8 !== buf.length) return { ok: false, reason: 'its size does not match its header' };
    return { ok: true };
  }
  if (kind === 'webm') {
    if (!startsWith(buf, [0x1a, 0x45, 0xdf, 0xa3])) return { ok: false, reason: 'it does not start like a WebM file' };
    if (!buf.subarray(0, 64).toString('latin1').includes('webm')) return { ok: false, reason: 'its type is not WebM' };
    return { ok: true };
  }
  if (kind === 'mp4') {
    const boxes = mp4Boxes(buf);
    if (!boxes || !boxes.has('ftyp')) return { ok: false, reason: 'its boxes do not add up' };
    if (!boxes.has('moov') && !boxes.has('mdat')) return { ok: false, reason: 'it has no video' };
    return { ok: true };
  }
  if (kind === 'jpg') {
    if (!startsWith(buf, [0xff, 0xd8, 0xff])) return { ok: false, reason: 'it does not start like a JPG' };
    if (!startsWith(buf, [0xff, 0xd9], buf.length - 2)) return { ok: false, reason: 'it does not end like a JPG' };
    return { ok: true };
  }
  if (kind === 'webp') {
    if (!startsWith(buf, Buffer.from('RIFF')) || !startsWith(buf, Buffer.from('WEBP'), 8)) return { ok: false, reason: 'it is not a WebP file' };
    if (buf.readUInt32LE(4) + 8 > buf.length) return { ok: false, reason: 'it is cut short' };
    const chunk = buf.toString('latin1', 12, 16);
    if (chunk !== 'VP8 ' && chunk !== 'VP8L' && chunk !== 'VP8X') return { ok: false, reason: 'it has no image data' };
    return { ok: true };
  }
  if (kind === 'mpeg') {
    const head = buf.subarray(0, 64);
    const found = [0xba, 0xb3].some((code) => head.indexOf(Buffer.from([0, 0, 1, code])) >= 0);
    if (!found) return { ok: false, reason: 'it has no MPEG start code' };
    return { ok: true };
  }
  return { ok: false, reason: 'the type is not allowed' };
}

const PROGRAM_PATTERNS = [
  Buffer.from([0x7f, 0x45, 0x4c, 0x46]),
  Buffer.from([0xfe, 0xed, 0xfa, 0xce]),
  Buffer.from([0xfe, 0xed, 0xfa, 0xcf]),
  Buffer.from([0xce, 0xfa, 0xed, 0xfe]),
  Buffer.from([0xcf, 0xfa, 0xed, 0xfe]),
];

const WEB_TAGS = ['script', 'html', 'iframe', 'object', 'embed'].flatMap((t) => [Buffer.from(`<${t}`), Buffer.from(`<${t.toUpperCase()}`), Buffer.from(`<${t[0].toUpperCase()}${t.slice(1)}`)]);

function peAt(buf, at) {
  if (at + 0x40 > buf.length) return false;
  const lfanew = buf.readUInt32LE(at + 0x3c);
  if (lfanew < 0x40 || lfanew > 0x1000) return false;
  const pe = at + lfanew;
  return pe + 4 <= buf.length && buf[pe] === 0x50 && buf[pe + 1] === 0x45 && buf[pe + 2] === 0 && buf[pe + 3] === 0;
}

function hiddenCodeReason(kind, buf) {
  for (const pat of PROGRAM_PATTERNS) if (buf.indexOf(pat) >= 0) return 'it contains a program';
  let at = buf.indexOf('MZ');
  while (at >= 0) {
    if (peAt(buf, at)) return 'it contains a Windows program';
    at = buf.indexOf('MZ', at + 1);
  }
  if (buf.indexOf('#!/') >= 0) return 'it contains a script';
  for (const tag of WEB_TAGS) if (buf.indexOf(tag) >= 0) return 'it contains web page code';
  if (kind === 'pdf') {
    const text = buf.toString('latin1');
    if (/\/(JavaScript|JS|Launch|EmbeddedFile)(?![A-Za-z])/.test(text)) return 'it contains a PDF action that runs code';
  }
  return '';
}

function checkDownload(kind, buf, recordedSha) {
  if (!KINDS[kind]) return { ok: false, reason: 'the type is not allowed' };
  if (!Buffer.isBuffer(buf) || buf.length === 0) return { ok: false, reason: 'the file is empty' };
  if (buf.length > MAX_FILE_BYTES) return { ok: false, reason: 'the file is too big' };
  const hidden = hiddenCodeReason(kind, buf);
  if (hidden) return { ok: false, reason: hidden };
  const shape = structureOk(kind, buf);
  if (!shape.ok) return { ok: false, reason: `not really a ${KINDS[kind].label}: ${shape.reason}` };
  if (!recordedSha || sha256(buf) !== recordedSha) return { ok: false, reason: 'the file changed after it was checked' };
  return { ok: true };
}

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function safeName(serverName, kind) {
  const base = path.posix.basename(String(serverName || '')).replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g, '_').replace(/^\.+/, '').trim();
  const want = KINDS[kind] ? KINDS[kind].ext : '';
  let name = base || `download${want}`;
  const ext = path.extname(name).toLowerCase();
  name = `${name.slice(0, name.length - ext.length)}${want}`;
  if (name.length > 140) name = `${name.slice(0, 136)}${want}`;
  return name;
}

function uniqueName(name, exists) {
  if (!exists(name)) return name;
  const ext = path.extname(name);
  const stem = name.slice(0, name.length - ext.length);
  for (let i = 2; i < 1000; i += 1) {
    const next = `${stem}-${i}${ext}`;
    if (!exists(next)) return next;
  }
  return null;
}

function displayOf(url) {
  const u = new URL(url);
  let pathname = u.pathname;
  try {
    pathname = decodeURIComponent(pathname);
  } catch {}
  pathname = pathname.replace(/[\x00-\x1f\x7f]/g, '?');
  const name = path.posix.basename(pathname) || pathname;
  return { name: name.slice(0, 140), path: pathname.slice(0, 300), host: u.host };
}

function byPath(a, b) {
  return a.path < b.path ? -1 : a.path > b.path ? 1 : a.href < b.href ? -1 : a.href > b.href ? 1 : 0;
}

function sortCap(entries) {
  const all = [...entries].sort(byPath);
  return { list: all.slice(0, MAX_LIST), total: all.length };
}

function skippedExt(pathname) {
  const m = /\.([A-Za-z][A-Za-z0-9]{1,4})$/.exec(pathname);
  return Boolean(m) && !DYNAMIC_EXTS.includes(m[1].toLowerCase());
}

function sameSite(a, b) {
  const root = (h) => h.split('.').slice(-2).join('.');
  return root(a.hostname) === root(b.hostname);
}

function buildScan(links, pageUrl) {
  let base;
  try {
    base = new URL(pageUrl);
  } catch {
    return { list: [], total: 0, candidates: [], skipped: 0 };
  }
  const known = new Map();
  const cands = new Map();
  for (const l of Array.isArray(links) ? links : []) {
    if (!l || typeof l.href !== 'string' || l.href.length > 4096) continue;
    let u;
    try {
      u = new URL(l.href, base);
    } catch {
      continue;
    }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') continue;
    u.hash = '';
    const key = u.href;
    if (known.has(key)) continue;
    const kind = kindOfHint(l, u);
    if (kind) {
      const shown = displayOf(key);
      const named = !kindOfPath(u.pathname) && kindOfPath(String(l.name || '')) ? path.posix.basename(String(l.name)).slice(0, 140) : '';
      known.set(key, { href: key, kind, ...shown, ...(named ? { name: named } : {}) });
      cands.delete(key);
      continue;
    }
    if (cands.has(key) || key === base.href.split('#')[0]) continue;
    if (!l.media && !l.name && !l.type && !u.search && skippedExt(u.pathname)) continue;
    const tier = l.media ? 0 : sameSite(u, base) ? 1 : 2;
    cands.set(key, { href: key, tier, order: cands.size });
  }
  const ranked = [...cands.values()].sort((a, b) => a.tier - b.tier || a.order - b.order);
  const { list, total } = sortCap(known.values());
  return { list, total, candidates: ranked.slice(0, MAX_PROBES).map((c) => c.href), skipped: Math.max(0, ranked.length - MAX_PROBES) };
}

function buildList(links, pageUrl) {
  return buildScan(links, pageUrl).list;
}

function entryFor(href, kind) {
  return { href, kind, ...displayOf(href) };
}

function withTimeout(promise, ms) {
  let timer;
  const limit = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('timeout')), ms);
  });
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer));
}

async function collectFrames(frames, runFrame, ms = 3000) {
  const out = [];
  let failed = 0;
  let mainFailed = false;
  const results = await Promise.all(frames.map((f) => withTimeout(Promise.resolve().then(() => runFrame(f)), ms).then((r) => ({ f, r }), () => ({ f, r: null }))));
  for (const { f, r } of results) {
    if (r && Array.isArray(r.items)) {
      for (const it of r.items) out.push(it);
    } else if (f.main) {
      mainFailed = true;
    } else {
      failed += 1;
    }
  }
  return { items: out, failed, mainFailed };
}

function scanFn(E, D, doc) {
  var seen = {};
  var media = [];
  var strong = [];
  var weak = [];
  var visited = 0;
  var nodes = doc.querySelectorAll('a[href],audio,video,source,img,object,embed');
  function ext(p) {
    var m = /\.([A-Za-z][A-Za-z0-9]{1,4})$/.exec(p);
    return m ? m[1].toLowerCase() : '';
  }
  function take(arr, cap, href, name, type, isMedia) {
    if (!href || typeof href !== 'string' || href.length > 4096 || arr.length >= cap) return;
    var u;
    try {
      u = new URL(href, doc.baseURI);
    } catch (e) {
      return;
    }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return;
    u.hash = '';
    if (seen[u.href]) return;
    seen[u.href] = 1;
    arr.push({ href: u.href, name: name || '', type: type || '', media: isMedia });
  }
  for (var i = 0; i < nodes.length && visited < 20000; i++) {
    var e = nodes[i];
    visited++;
    var tag = String(e.tagName || '').toUpperCase();
    if (tag === 'A') {
      var h = e.href;
      var dn = e.getAttribute('download') || '';
      var ty = e.getAttribute('type') || '';
      var p = '';
      var q = '';
      try {
        var uu = new URL(h);
        p = uu.pathname;
        q = uu.search;
      } catch (err) {
        continue;
      }
      var x = ext(p);
      var hinted = E.indexOf(x) >= 0 || Boolean(dn) || Boolean(ty);
      if (!hinted && q) {
        var vals = Array.from(uu.searchParams.values());
        for (var k = 0; k < vals.length && !hinted; k++) hinted = E.indexOf(ext(vals[k].split(/[?#]/)[0])) >= 0;
      }
      if (hinted) take(strong, 1000, h, dn, ty, false);
      else if (!x || D.indexOf(x) >= 0 || q) take(weak, 400, h, '', '', false);
      continue;
    }
    var ts = e.getAttribute('type') || '';
    take(media, 600, e.currentSrc || e.src || e.data || '', '', ts, true);
    if (tag === 'IMG' || tag === 'SOURCE') {
      var ss = e.getAttribute('srcset') || '';
      var parts = ss.split(',');
      for (var j = 0; j < parts.length && j < 20; j++) take(media, 600, parts[j].trim().split(/\s+/)[0], '', '', true);
    }
    if (tag === 'VIDEO') take(media, 600, e.poster || '', '', '', true);
  }
  return { items: media.concat(strong, weak), visited: visited };
}

function scanScript() {
  const exts = Object.keys(EXT_KIND).map((e) => e.slice(1));
  return `(${scanFn.toString()})(${JSON.stringify(exts)},${JSON.stringify(DYNAMIC_EXTS)},document)`;
}

function kindOfProbe(head, contentType) {
  const byHead = kindOfHead(head);
  if (!byHead) return '';
  const byMime = kindOfMime(contentType);
  if (byMime && byMime !== byHead) return '';
  return byHead;
}

function createQueue(run) {
  const items = [];
  let seq = 0;
  let running = false;
  let batchBytes = 0;
  let batchId = 0;
  const listeners = new Set();

  function notify() {
    for (const fn of listeners) fn();
  }

  async function loop() {
    if (running) return;
    running = true;
    while (true) {
      const next = items.find((i) => i.state === 'waiting');
      if (!next) break;
      next.state = 'downloading';
      notify();
      let result;
      try {
        result = await run(next, { batchBytes, batchLimit: MAX_BATCH_BYTES });
      } catch (err) {
        result = { ok: false, reason: 'the download failed' };
      }
      if (result.bytes) batchBytes += result.bytes;
      if (next.state === 'cancelled') continue;
      if (result.ok) {
        next.state = 'done';
        next.saved = result.saved;
      } else if (result.login) {
        next.state = 'login';
        next.reason = result.reason || 'this site asks for a sign-in';
      } else {
        next.state = 'refused';
        next.reason = result.reason || 'refused';
      }
      notify();
    }
    running = false;
    batchBytes = 0;
    batchId += 1;
    notify();
  }

  return {
    add(entries, opts = {}) {
      const added = [];
      for (const e of entries) {
        const item = { id: (seq += 1), ...e, state: 'waiting', reason: '', saved: '', cookie: opts.cookie || '', batch: batchId };
        items.push(item);
        added.push(item);
      }
      notify();
      loop();
      return added;
    },
    cancel(id) {
      const item = items.find((i) => i.id === id);
      if (!item) return false;
      if (item.state === 'waiting' || item.state === 'login' || item.state === 'refused') item.state = 'cancelled';
      else if (item.state === 'downloading') {
        item.state = 'cancelled';
        if (item.abort) item.abort();
      }
      notify();
      return true;
    },
    cancelAll() {
      for (const item of items) {
        if (item.state === 'waiting') item.state = 'cancelled';
        if (item.state === 'downloading') {
          item.state = 'cancelled';
          if (item.abort) item.abort();
        }
      }
      notify();
    },
    remove(id) {
      const i = items.findIndex((x) => x.id === id);
      if (i < 0 || items[i].state === 'downloading') return false;
      items.splice(i, 1);
      notify();
      return true;
    },
    clear() {
      for (let i = items.length - 1; i >= 0; i -= 1) {
        const s = items[i].state;
        if (s !== 'downloading') items.splice(i, 1);
      }
      notify();
    },
    snapshot() {
      return items.map(({ abort, cookie, ...rest }) => rest);
    },
    get(id) {
      return items.find((i) => i.id === id) || null;
    },
    busy() {
      return running;
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

module.exports = {
  KINDS,
  MAX_FILE_BYTES,
  MAX_BATCH_FILES,
  MAX_BATCH_BYTES,
  MAX_TRIES,
  kindOfPath,
  structureOk,
  hiddenCodeReason,
  checkDownload,
  sha256,
  safeName,
  uniqueName,
  displayOf,
  buildList,
  buildScan,
  sortCap,
  entryFor,
  collectFrames,
  scanFn,
  scanScript,
  kindOfHead,
  kindOfMime,
  kindOfProbe,
  skippedExt,
  EXT_KIND,
  DYNAMIC_EXTS,
  MAX_PROBES,
  MAX_LIST,
  createQueue,
};
