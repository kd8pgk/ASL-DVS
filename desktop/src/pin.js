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
    if (pinMatches(n.pin, req.certPem) || pinMatches(n.lanPin, req.certPem)) return { trust: true };
  }
  return {
    trust: false,
    refused: { hostname: host, fingerprint: certFingerprint(req.certPem), nodeIds: owners.map((n) => n.id) },
  };
}

module.exports = { certFingerprint, formatFingerprint, pinMatches, certDecision };
