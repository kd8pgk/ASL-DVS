const crypto = require('node:crypto');

const PAGES = [
  { id: 'controller', label: 'Node Controller', port: 8989, away: false },
  { id: 'talker', label: 'Node Talker', port: 8993, away: true },
  { id: 'sysmon', label: 'SysMon', port: 9999, away: false },
  { id: 'nodemon', label: 'Node Monitor', port: 7777, away: false },
  { id: 'recorder', label: 'Node Recorder', port: 8995, away: false },
  { id: 'wifimon', label: 'WifiMon', port: 8991, away: false },
  { id: 'h44', label: '44helper', port: 9997, away: false, single: true },
  { id: 'instmon', label: 'Install Monitor', port: 8990, away: false, single: true },
  { id: 'termon', label: 'Terminal Monitor', port: 7878, away: false, single: true },
  { id: 'piper', label: 'Pi-Piper', port: 8765, away: false, external: true },
  { id: 'pibrary', label: 'Pibrary', port: 9000, away: false, external: true },
];

const HOST_RE = /^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$|^[0-9A-Fa-f:.]{2,45}$/;
const IPV4_RE = /^\d{1,3}(\.\d{1,3}){3}$/;
const PIN_RE = /^[0-9a-f]{64}$/;
const MAX_PINS = 8;

function validHost(h) {
  return typeof h === 'string' && HOST_RE.test(h);
}

function parseAddress(text) {
  let t = String(text == null ? '' : text).trim();
  const original = t;
  let https = null;
  const sep = t.indexOf('://');
  if (sep >= 0) {
    const scheme = t.slice(0, sep).toLowerCase();
    if (scheme === 'https') https = true;
    else if (scheme === 'http') https = false;
    else return { host: original, port: null, https: null, explicit: false };
    t = t.slice(sep + 3);
  }
  const cut = t.search(/[/?#]/);
  if (cut >= 0) t = t.slice(0, cut);
  const at = t.lastIndexOf('@');
  if (at >= 0) t = t.slice(at + 1);
  let host = t;
  let port = null;
  let explicit = false;
  if (t.startsWith('[')) {
    const end = t.indexOf(']');
    if (end > 0) {
      host = t.slice(1, end);
      const rest = t.slice(end + 1);
      if (rest.startsWith(':')) port = toPort(rest.slice(1));
      explicit = port !== null;
    }
  } else if ((t.match(/:/g) || []).length === 1) {
    const p = toPort(t.slice(t.indexOf(':') + 1));
    if (p !== null) {
      host = t.slice(0, t.indexOf(':'));
      port = p;
      explicit = true;
    }
  }
  if (port === null && https !== null) port = https ? 443 : 80;
  return { host: host.replace(/^\[|\]$/g, ''), port, https, explicit };
}

function toPort(v) {
  if (typeof v === 'number') return Number.isInteger(v) && v >= 1 && v <= 65535 ? v : null;
  if (!/^\d{1,5}$/.test(String(v).trim())) return null;
  const n = Number.parseInt(v, 10);
  return n >= 1 && n <= 65535 ? n : null;
}

function normalizePin(v) {
  const s = String(v == null ? '' : v).trim().toLowerCase().replace(/[:\s]/g, '');
  return PIN_RE.test(s) ? s : '';
}

function blank() {
  return {
    id: '',
    name: '',
    host: '',
    https: false,
    ports: Object.fromEntries(PAGES.map((p) => [p.id, p.port])),
    pins: [],
    awayHost: '',
    awayPort: 443,
    awayHttps: true,
    lanIp: '',
  };
}

function normalizeNode(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const out = blank();
  out.id = typeof r.id === 'string' && r.id ? r.id : crypto.randomUUID();
  out.name = String(r.name == null ? '' : r.name).trim().slice(0, 80);

  const addr = parseAddress(r.host);
  if (!validHost(addr.host)) return { error: 'Enter a valid host name or address.' };
  if (addr.explicit) return { error: 'Set ports on the page lines, not in the address.' };
  out.host = addr.host;
  out.https = addr.https !== null ? addr.https : Boolean(r.https);

  for (const page of PAGES) {
    const v = r.ports && r.ports[page.id];
    if (v === undefined || v === null || v === '') continue;
    const p = toPort(v);
    if (p === null) return { error: `${page.label} port must be 1 to 65535.` };
    out.ports[page.id] = p;
  }

  const pins = [];
  for (const v of [...(Array.isArray(r.pins) ? r.pins : []), r.pin, r.lanPin]) {
    const p = normalizePin(v);
    if (p && !pins.includes(p)) pins.push(p);
  }
  out.pins = pins.slice(-MAX_PINS);

  const lan = String(r.lanIp == null ? '' : r.lanIp).trim();
  if (lan) {
    if (!IPV4_RE.test(lan) || !lan.split('.').every((o) => Number(o) <= 255)) return { error: 'LAN address must be an IPv4 address.' };
    out.lanIp = lan;
  }

  const away = String(r.awayHost == null ? '' : r.awayHost).trim();
  if (away) {
    const a = parseAddress(away);
    if (!validHost(a.host)) return { error: 'Away address is not valid.' };
    out.awayHost = a.host;
    out.awayHttps = a.https !== null ? a.https : r.awayHttps !== false;
    out.awayPort = a.port !== null ? a.port : toPort(r.awayPort) || (out.awayHttps ? 443 : 80);
  }
  return { node: out };
}

function originOf(target) {
  const host = target.host.includes(':') ? `[${target.host}]` : target.host;
  return `${target.https ? 'https' : 'http'}://${host}:${target.port}`;
}

function sameOrigin(url, target) {
  try {
    return new URL(url).origin === new URL(originOf(target)).origin;
  } catch {
    return false;
  }
}

function homeTarget(node, page) {
  return { host: node.host, port: node.ports[page.id], https: node.https, pins: node.pins, via: 'home' };
}

function lanTarget(node, page) {
  const ip = node.lanIp;
  if (!ip || !IPV4_RE.test(ip) || !validHost(ip)) return null;
  if (ip.toLowerCase() === node.host.toLowerCase()) return null;
  if (node.https && !node.pins.length) return null;
  return { host: ip, port: node.ports[page.id], https: node.https, pins: node.pins, via: 'lan' };
}

function awayTarget(node, page) {
  if (!page.away || !node.awayHost || !validHost(node.awayHost)) return null;
  if (!(node.awayPort >= 1 && node.awayPort <= 65535)) return null;
  return { host: node.awayHost, port: node.awayPort, https: node.awayHttps, pins: [], via: 'away' };
}

function matchPage(url, nodes) {
  for (const node of nodes) {
    for (const page of PAGES) {
      for (const t of [homeTarget(node, page), lanTarget(node, page), awayTarget(node, page)]) {
        if (t && sameOrigin(url, t)) return { nodeId: node.id, pageId: page.id };
      }
    }
  }
  return null;
}

module.exports = {
  PAGES,
  MAX_PINS,
  validHost,
  parseAddress,
  normalizePin,
  normalizeNode,
  originOf,
  sameOrigin,
  homeTarget,
  lanTarget,
  awayTarget,
  matchPage,
};
