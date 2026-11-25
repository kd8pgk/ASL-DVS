const KB = 1024;
const SLOW_BPS = 16 * KB;
const FAST_BPS = 48 * KB;
const SLOW_TTFB_MS = 3000;
const MIN_SAMPLE_BYTES = 8 * KB;
const SAMPLES = 3;
const SMALL_PX = 100 * 100;
const MAX_IMAGE_BYTES = 64 * 1024 * 1024;
const RETRIES = 5;
const READ_AHEAD_BYTES = 64 * 1024 * 1024;
const SCHEME = 'nbimg';

function createMeter() {
  const rates = [];
  const waits = [];
  let slow = false;
  let lastRate = 0;
  function median(list) {
    if (!list.length) return 0;
    const s = [...list].sort((a, b) => a - b);
    return s[Math.floor(s.length / 2)];
  }
  function decide() {
    const r = rates.length >= SAMPLES ? median(rates) : 0;
    const w = waits.length ? waits[waits.length - 1] : 0;
    if (!slow && ((r && r < SLOW_BPS) || w > SLOW_TTFB_MS)) slow = true;
    else if (slow && r >= FAST_BPS && w <= SLOW_TTFB_MS) slow = false;
  }
  return {
    transfer(bytes, ms) {
      if (!(bytes >= MIN_SAMPLE_BYTES) || !(ms > 0)) return;
      lastRate = (bytes * 1000) / ms;
      rates.push(lastRate);
      if (rates.length > SAMPLES) rates.shift();
      decide();
    },
    wait(ms) {
      if (!(ms >= 0)) return;
      waits.push(ms);
      if (waits.length > SAMPLES) waits.shift();
      decide();
    },
    isSlow: () => slow,
    rate: () => Math.round(lastRate),
    reset() {
      rates.length = 0;
      waits.length = 0;
      slow = false;
      lastRate = 0;
    },
  };
}

function isActive(mode, meterSlow) {
  if (mode === 'on') return true;
  if (mode === 'off') return false;
  return Boolean(meterSlow);
}

function mainColumn(report) {
  const items = (report && Array.isArray(report.items)) ? report.items : [];
  let best = null;
  for (const i of items) {
    const area = (Number(i.w) || 0) * (Number(i.h) || 0);
    if (area > 0 && (!best || area > best.area)) best = { area, left: Number(i.x) || 0, width: Number(i.w) || 0 };
  }
  return best;
}

function placeOf(entry, report, main = mainColumn(report)) {
  const vh = report && report.vh > 0 ? report.vh : 0;
  const vw = report && report.vw > 0 ? report.vw : 0;
  const items = (report && Array.isArray(report.items)) ? report.items : [];
  if (entry.late) return { tier: 5, key: entry.seq };
  const hit = items.find((i) => i && i.src === entry.url);
  if (!hit || !vh) return { tier: 3, key: entry.seq };
  const w = Number(hit.w) || 0;
  const h = Number(hit.h) || 0;
  const x = Number(hit.x) || 0;
  const top = Number(hit.top) || 0;
  const small = w > 0 && h > 0 && w * h < SMALL_PX;
  const center = x + w / 2;
  const side = w > 0 && (main
    ? (center < main.left || center > main.left + main.width) && w < main.width * 0.6
    : vw > 0 && w < vw * 0.3 && (center < vw * 0.25 || center > vw * 0.75));
  if (small || side) return { tier: 4, key: entry.seq };
  const bottom = top + Math.max(h, 1);
  if (top < vh && bottom > 0) return { tier: 0, key: top };
  if (top >= vh) return { tier: 1, key: top };
  return { tier: 2, key: -top };
}

function pickNext(entries, report) {
  let best = null;
  let bestPlace = null;
  const main = mainColumn(report);
  for (const e of entries) {
    const p = placeOf(e, report, main);
    if (!best || p.tier < bestPlace.tier || (p.tier === bestPlace.tier && (p.key < bestPlace.key || (p.key === bestPlace.key && e.seq < best.seq)))) {
      best = e;
      bestPlace = p;
    }
  }
  return best;
}

function addSchemeToCsp(value) {
  const parts = String(value).split(';').map((p) => p.trim()).filter(Boolean);
  const find = (name) => parts.findIndex((p) => p.toLowerCase().split(/\s+/)[0] === name);
  const img = find('img-src');
  if (img >= 0) {
    parts[img] = `${parts[img]} ${SCHEME}:`;
    return parts.join('; ');
  }
  const def = find('default-src');
  if (def >= 0) {
    const sources = parts[def].split(/\s+/).slice(1).join(' ');
    parts.push(`img-src ${sources} ${SCHEME}:`.replace(/\s+/g, ' '));
    return parts.join('; ');
  }
  return parts.join('; ');
}

function cspHeaders(headers) {
  let changed = false;
  const out = {};
  for (const [k, v] of Object.entries(headers || {})) {
    if (k.toLowerCase() === 'content-security-policy') {
      out[k] = [].concat(v).map((x) => addSchemeToCsp(x));
      changed = true;
    } else {
      out[k] = v;
    }
  }
  return changed ? out : null;
}

function header(headers, name) {
  const n = name.toLowerCase();
  for (const [k, v] of Object.entries(headers || {})) if (k.toLowerCase() === n) return String([].concat(v)[0]);
  return '';
}

function isPrefetch(requestHeaders) {
  const p = `${header(requestHeaders, 'Sec-Purpose')} ${header(requestHeaders, 'Purpose')} ${header(requestHeaders, 'X-Purpose')} ${header(requestHeaders, 'X-Moz')}`;
  return /prefetch|prerender|preview/i.test(p);
}

function parseContentRange(value) {
  const m = /^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/i.exec(String(value || '').trim());
  if (!m) return null;
  return { start: Number(m[1]), end: Number(m[2]), total: m[3] === '*' ? 0 : Number(m[3]) };
}

function backoffMs(attempt) {
  return Math.min(32000, 2000 * 2 ** Math.max(0, attempt - 1));
}

const NEXT_TEXT = /^\s*(next(\s+(page|comic|chapter|strip|episode))?|›|»|>|>>|→)\s*[›»>→]?\s*$/i;

function pickNextLink(links, pageUrl) {
  let base;
  try {
    base = new URL(pageUrl);
  } catch {
    return '';
  }
  const ok = (href) => {
    try {
      const u = new URL(href, base);
      if (u.protocol !== base.protocol || u.host !== base.host) return '';
      if (u.href.split('#')[0] === base.href.split('#')[0]) return '';
      return u.href;
    } catch {
      return '';
    }
  };
  const list = Array.isArray(links) ? links : [];
  for (const l of list) if (l && /(^|\s)next(\s|$)/i.test(String(l.rel || '')) && ok(l.href)) return ok(l.href);
  for (const l of list) if (l && NEXT_TEXT.test(String(l.text || '')) && ok(l.href)) return ok(l.href);
  return '';
}

function imageUrlsIn(html, pageUrl) {
  const out = [];
  const seen = new Set();
  const re = /<img\b[^>]*?\ssrc\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/gi;
  let m;
  while ((m = re.exec(String(html))) && out.length < 200) {
    const raw = (m[2] || m[3] || m[4] || '').replace(/&amp;/g, '&');
    try {
      const u = new URL(raw, pageUrl);
      if ((u.protocol === 'https:' || u.protocol === 'http:') && !seen.has(u.href)) {
        seen.add(u.href);
        out.push(u.href);
      }
    } catch {}
  }
  return out;
}

function sizeLabel(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB/s`;
  return `${(bytes / 1024).toFixed(1)} KB/s`;
}

module.exports = {
  SLOW_BPS,
  FAST_BPS,
  SLOW_TTFB_MS,
  MAX_IMAGE_BYTES,
  RETRIES,
  READ_AHEAD_BYTES,
  SCHEME,
  createMeter,
  isActive,
  placeOf,
  mainColumn,
  pickNext,
  addSchemeToCsp,
  cspHeaders,
  header,
  isPrefetch,
  parseContentRange,
  backoffMs,
  pickNextLink,
  imageUrlsIn,
  sizeLabel,
};
