const crypto = require('node:crypto');
const { normalizePin } = require('./node');

function pinHosts(n) {
  return [n.host, n.lanIp].filter(Boolean).map((h) => h.toLowerCase());
}

function certFingerprint(pem) {
  const body = String(pem == null ? '' : pem)
    .replace(/-----[A-Z ]+-----/g, '')
    .replace(/\s+/g, '');
  const der = Buffer.from(body, 'base64');
  if (!der.length) return '';
  return crypto.createHash('sha256').update(der).digest('hex');
}

function formatFingerprint(hex) {
  return (String(hex).toUpperCase().match(/.{1,2}/g) || []).join(':');
}

function pinMatches(pin, pem) {
  const p = normalizePin(pin);
  return p !== '' && p === certFingerprint(pem);
}

function certDecision(req, nodes) {
  const host = String(req.hostname || '').toLowerCase();
  const owners = nodes.filter((n) => pinHosts(n).includes(host));
  if (!owners.length) return { trust: false };
  for (const n of owners) {
    if (n.pins.some((p) => pinMatches(p, req.certPem))) return { trust: true };
  }
  return {
    trust: false,
    refused: { hostname: host, fingerprint: certFingerprint(req.certPem), nodeIds: owners.map((n) => n.id) },
  };
}

function refusedKey(host, port, https) {
  const p = Number(port) || (https === false ? 80 : 443);
  return `${String(host || '').toLowerCase().replace(/^\[|\]$/g, '')}:${p}`;
}

function refusedKeyOfUrl(url) {
  try {
    const u = new URL(url);
    return refusedKey(u.hostname, u.port, u.protocol !== 'http:');
  } catch {
    return '';
  }
}

module.exports = { certFingerprint, formatFingerprint, pinMatches, certDecision, refusedKey, refusedKeyOfUrl };
