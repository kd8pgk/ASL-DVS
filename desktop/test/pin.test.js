const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { certFingerprint, formatFingerprint, pinMatches, certDecision } = require('../src/pin');
const { normalizeNode } = require('../src/node');

const der = crypto.randomBytes(300);
const pem = `-----BEGIN CERTIFICATE-----\n${der.toString('base64').replace(/.{64}/g, '$&\n')}\n-----END CERTIFICATE-----\n`;
const hex = crypto.createHash('sha256').update(der).digest('hex');

function nodes(extra) {
  return [normalizeNode({ id: 'a', host: 'pi.local', https: true, lanIp: '192.168.1.5', ...extra }).node];
}

test('the fingerprint is the sha-256 of the DER bytes', () => {
  assert.equal(certFingerprint(pem), hex);
  assert.equal(certFingerprint(''), '');
});

test('fingerprints are shown as upper-case pairs', () => {
  assert.equal(formatFingerprint('abcd01'), 'AB:CD:01');
});

test('pinMatches accepts colons and case, refuses a different cert', () => {
  assert.equal(pinMatches(formatFingerprint(hex), pem), true);
  assert.equal(pinMatches('00'.repeat(32), pem), false);
  assert.equal(pinMatches('', pem), false);
});

test('a host that is not a saved node is never trusted and is not reported', () => {
  assert.deepEqual(certDecision({ hostname: 'example.org', certPem: pem }, nodes({})), { trust: false });
});

test('an unknown certificate on a node is refused and reported with its fingerprint', () => {
  const d = certDecision({ hostname: 'PI.local', certPem: pem }, nodes({}));
  assert.equal(d.trust, false);
  assert.deepEqual(d.refused, { hostname: 'pi.local', fingerprint: hex, nodeIds: ['a'] });
});

test('the pinned certificate is trusted on the host name and the LAN address', () => {
  const n = nodes({ pin: hex });
  assert.equal(certDecision({ hostname: 'pi.local', certPem: pem }, n).trust, true);
  assert.equal(certDecision({ hostname: '192.168.1.5', certPem: pem }, n).trust, true);
});

test('a different certificate than the pinned one is refused', () => {
  const n = nodes({ pin: '11'.repeat(32) });
  assert.equal(certDecision({ hostname: 'pi.local', certPem: pem }, n).trust, false);
});

test('the away address is never pinned', () => {
  const n = nodes({ pin: hex, awayHost: 'node.example.com' });
  assert.deepEqual(certDecision({ hostname: 'node.example.com', certPem: pem }, n), { trust: false });
});
