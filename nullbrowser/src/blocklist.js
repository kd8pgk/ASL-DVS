const MAX_RULES = 20000;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_LINES = 100000;
const MAX_SELECTOR = 500;
const MAX_CSS = 200 * 1024;

const HOST_RE = /^(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z][a-z0-9-]{1,23}$/;
const IPV4_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/;

function cleanHost(value) {
  let h = String(value || '').trim().toLowerCase();
  h = h.replace(/^\|\|/, '').replace(/^\*\./, '').replace(/^\./, '');
  h = h.replace(/\$.*$/, '').replace(/\^.*$/, '').replace(/\/.*$/, '').replace(/:\d+$/, '').replace(/\.$/, '');
  if (!h || h.length > 253 || h === 'localhost') return '';
  if (IPV4_RE.test(h)) return h.split('.').every((n) => Number(n) <= 255) ? h : '';
  return HOST_RE.test(h) ? h : '';
}

function validSelector(sel) {
  const s = String(sel || '').trim();
  if (!s || s.length > MAX_SELECTOR) return '';
  if (/[{};@\\\n\r,<]/.test(s) || /url\s*\(|expression\s*\(|\/\*/i.test(s)) return '';
  if ((s.match(/"/g) || []).length % 2 || (s.match(/'/g) || []).length % 2) return '';
  if ((s.match(/\(/g) || []).length !== (s.match(/\)/g) || []).length) return '';
  if ((s.match(/\[/g) || []).length !== (s.match(/\]/g) || []).length) return '';
  if (/^(html|body|head|\*|:root)$/i.test(s)) return '';
  return s;
}

function labels(host) {
  const out = [];
  let h = host;
  while (h) {
    out.push(h);
    const i = h.indexOf('.');
    if (i < 0) break;
    h = h.slice(i + 1);
  }
  return out;
}

function createBlocklist() {
  const hosts = new Set();
  const elements = new Map();
  const cssCache = new Map();
  let elementCount = 0;

  function size() {
    return hosts.size + elementCount;
  }

  function hostBlocked(host) {
    const h = String(host || '').toLowerCase();
    if (!h || !hosts.size) return '';
    for (const l of labels(h)) {
      if (l.includes('.') && hosts.has(l)) return l;
    }
    return '';
  }

  function addHost(value) {
    const h = cleanHost(value);
    if (!h) return { ok: false, reason: 'not a host name' };
    if (hosts.has(h)) return { ok: true, host: h, added: false };
    if (size() >= MAX_RULES) return { ok: false, reason: 'the list is full' };
    hosts.add(h);
    return { ok: true, host: h, added: true };
  }

  function addElement(host, selector) {
    const h = cleanHost(host);
    const sel = validSelector(selector);
    if (!h) return { ok: false, reason: 'not a host name' };
    if (!sel) return { ok: false, reason: 'that selector is not allowed' };
    let set = elements.get(h);
    if (set && set.has(sel)) return { ok: true, host: h, selector: sel, added: false };
    if (size() >= MAX_RULES) return { ok: false, reason: 'the list is full' };
    if (!set) {
      set = new Set();
      elements.set(h, set);
    }
    set.add(sel);
    elementCount += 1;
    cssCache.clear();
    return { ok: true, host: h, selector: sel, added: true };
  }

  function removeHost(value) {
    return hosts.delete(String(value || ''));
  }

  function removeElement(host, selector) {
    const set = elements.get(String(host || ''));
    if (!set || !set.delete(String(selector || ''))) return false;
    if (!set.size) elements.delete(String(host));
    elementCount -= 1;
    cssCache.clear();
    return true;
  }

  function cssFor(host) {
    const h = String(host || '').toLowerCase();
    if (!h || !elementCount) return '';
    if (cssCache.has(h)) return cssCache.get(h);
    const picked = [];
    for (const l of labels(h)) {
      const set = elements.get(l);
      if (set) for (const s of set) picked.push(`${s}{display:none!important}`);
    }
    let css = picked.join('\n');
    if (css.length > MAX_CSS) css = css.slice(0, css.lastIndexOf('\n', MAX_CSS));
    cssCache.set(h, css);
    return css;
  }

  function parseLine(raw) {
    const line = String(raw).trim();
    if (!line || line.startsWith('!') || line.startsWith('[') || (line.startsWith('#') && !line.includes('##'))) return null;
    const hide = line.indexOf('##');
    if (hide > 0) return { kind: 'element', host: line.slice(0, hide), selector: line.slice(hide + 2) };
    if (hide === 0 || line.includes('#@#') || line.includes('#?#') || line.startsWith('@@')) return { kind: 'skip' };
    const parts = line.split(/\s+/);
    if (parts.length >= 2 && /^(0\.0\.0\.0|127\.0\.0\.1|::1?)$/.test(parts[0])) return { kind: 'host', host: parts[1] };
    if (parts.length === 1) return { kind: 'host', host: parts[0] };
    return { kind: 'skip' };
  }

  function importText(text) {
    const lines = String(text || '').split(/\r?\n/).slice(0, MAX_LINES);
    const out = { hosts: 0, elements: 0, skipped: 0, full: false };
    for (const raw of lines) {
      const p = parseLine(raw);
      if (!p) continue;
      if (p.kind === 'skip') {
        out.skipped += 1;
        continue;
      }
      const r = p.kind === 'host' ? addHost(p.host) : addElement(p.host, p.selector);
      if (!r.ok) {
        if (r.reason === 'the list is full') out.full = true;
        out.skipped += 1;
      } else if (r.added) {
        out[p.kind === 'host' ? 'hosts' : 'elements'] += 1;
      }
    }
    return out;
  }

  function snapshot(limit = 100) {
    const els = [];
    for (const [h, set] of elements) for (const s of set) els.push({ host: h, selector: s });
    return { hostCount: hosts.size, elementCount, hosts: [...hosts].sort().slice(0, limit), elements: els.slice(0, limit) };
  }

  function clear() {
    hosts.clear();
    elements.clear();
    cssCache.clear();
    elementCount = 0;
  }

  return { hostBlocked, addHost, addElement, removeHost, removeElement, cssFor, importText, snapshot, clear, size, hasElements: () => elementCount > 0 };
}

module.exports = { MAX_RULES, MAX_FILE_BYTES, MAX_LINES, MAX_SELECTOR, cleanHost, validSelector, createBlocklist };
