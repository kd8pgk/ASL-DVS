const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../src/policy');

test('typed addresses: a bare name gets https, other schemes and spaces are refused, blank is blank', () => {
  assert.deepEqual(P.normalizeInput('example.com'), { url: 'https://example.com/' });
  assert.deepEqual(P.normalizeInput('  example.com/a?b=1 '), { url: 'https://example.com/a?b=1' });
  assert.deepEqual(P.normalizeInput('localhost:3000/x'), { url: 'https://localhost:3000/x' });
  assert.deepEqual(P.normalizeInput('http://example.com'), { url: 'http://example.com/' });
  assert.deepEqual(P.normalizeInput(''), { blank: true });
  assert.deepEqual(P.normalizeInput('about:blank'), { blank: true });
  assert.match(P.normalizeInput('two words').error, /no search box/);
  assert.match(P.normalizeInput('file:///etc/passwd').error, /file addresses are not opened/);
  assert.match(P.normalizeInput('javascript:alert(1)').error, /javascript addresses/);
  assert.match(P.normalizeInput('https://user:pw@example.com/').error, /user name or password/);
});

test('https first: public http is upgraded, private addresses and allowed hosts are not', () => {
  assert.equal(P.httpsUpgrade('http://example.com/a', new Set()), 'https://example.com/a');
  assert.equal(P.httpsUpgrade('http://example.com:8080/', new Set()), 'https://example.com:8080/');
  assert.equal(P.httpsUpgrade('http://example.com/a', new Set(['example.com'])), null);
  assert.equal(P.httpsUpgrade('https://example.com/', new Set()), null);
  for (const u of ['http://192.168.1.5/', 'http://10.0.0.1/', 'http://router.lan/', 'http://pi.local/', 'http://localhost/', 'http://printer/']) assert.equal(P.httpsUpgrade(u, new Set()), null, u);
});

test('private hosts are the LAN ones', () => {
  for (const h of ['192.168.0.196', '10.1.2.3', '172.20.0.1', '127.0.0.1', 'magicbox.local', 'nas.lan', 'localhost', '::1', 'fd00::1', 'printer']) assert.equal(P.isPrivateHost(h), true, h);
  for (const h of ['example.com', '8.8.8.8', '172.32.0.1', '2001:4860::8888']) assert.equal(P.isPrivateHost(h), false, h);
  assert.equal(P.certTrustable('192.168.1.1'), true);
  assert.equal(P.certTrustable('example.com'), false);
});

test('third parties: a different site is third party, subdomains of the same site are not', () => {
  assert.equal(P.siteOf('www.example.com'), 'example.com');
  assert.equal(P.siteOf('a.b.example.co.uk'), 'example.co.uk');
  assert.equal(P.siteOf('user.github.io'), 'user.github.io');
  assert.equal(P.isThirdParty('https://cdn.example.com/x.js', 'https://www.example.com/'), false);
  assert.equal(P.isThirdParty('https://tracker.net/p.gif', 'https://www.example.com/'), true);
  assert.equal(P.isThirdParty('https://a.github.io/', 'https://b.github.io/'), true);
  assert.equal(P.isThirdParty('https://x.com/', ''), false);
});

test('a page\'s origin is its scheme, host and port, with no path, query or fragment; a bad url has none', () => {
  assert.equal(P.originOf('https://example.com/a/b?x=1#y'), 'https://example.com');
  assert.equal(P.originOf('http://example.com:8080/'), 'http://example.com:8080');
  assert.equal(P.originOf('about:blank'), 'null');
  assert.equal(P.originOf('not a url'), '');
  assert.equal(P.originOf(''), '');
});

test('pages may only be http(s); subresources also ws, data and blob', () => {
  assert.equal(P.allowPageUrl('https://example.com/'), true);
  assert.equal(P.allowPageUrl('about:blank'), true);
  for (const u of ['file:///etc', 'chrome://gpu', 'devtools://x', 'javascript:1', 'data:text/html,hi']) assert.equal(P.allowPageUrl(u), false, u);
  for (const u of ['wss://x/', 'data:image/png;base64,AA', 'blob:https://x/1']) assert.equal(P.allowSubresource(u), true, u);
  for (const u of ['file:///etc', 'chrome://gpu', 'ftp://x/']) assert.equal(P.allowSubresource(u), false, u);
});

test('third-party cookies are dropped from a response, other headers stay', () => {
  const r = P.stripCookieHeaders({ 'Set-Cookie': ['a=1'], 'set-cookie': ['b=2'], 'Content-Type': ['text/html'] });
  assert.equal(r.removed, true);
  assert.deepEqual(r.headers, { 'Content-Type': ['text/html'] });
  assert.equal(P.stripCookieHeaders({ 'Content-Type': ['x'] }).removed, false);
});

test('the user agent says Chromium, not Electron or Null Browser, and nothing else is invented', () => {
  const ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) null-browser/0.1.0 Chrome/140.0.0.0 Electron/44.11.5 Safari/537.36';
  assert.equal(P.chromiumUserAgent(ua), 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36');
});

test('JIT is off, and the packaged app refuses debugging and certificate switches', () => {
  assert.equal(P.JS_FLAGS, '--jitless');
  assert.deepEqual(P.unsafeSwitches(['--remote-debugging-port=9222', '--ignore-certificate-errors', '--js-flags=--expose-gc', '--disable-gpu']), ['remote-debugging-port', 'ignore-certificate-errors', 'js-flags']);
  assert.ok(P.SWITCHES.includes('disable-background-networking'));
  assert.ok(P.SWITCHES.includes('dns-over-https-mode=off'), 'no automatic DNS-over-HTTPS probe to Google at idle');
  assert.ok(P.DISABLED_FEATURES.includes('DnsOverHttpsUpgrade'));
  assert.ok(P.DISABLED_FEATURES.includes('AsyncDns'));
});

test('the faster-JavaScript marker is added or removed from the relaunch args without disturbing the rest, and never duplicated', () => {
  assert.deepEqual(P.relaunchArgv(['--no-sandbox', '.'], true), ['--no-sandbox', '.', P.FAST_JS_ARG]);
  assert.deepEqual(P.relaunchArgv(['--no-sandbox', '.', P.FAST_JS_ARG], false), ['--no-sandbox', '.']);
  assert.deepEqual(P.relaunchArgv(['--no-sandbox', '.', P.FAST_JS_ARG], true), ['--no-sandbox', '.', P.FAST_JS_ARG]);
  assert.deepEqual(P.relaunchArgv([], false), []);
  assert.ok(P.unsafeSwitches([P.FAST_JS_ARG]).length === 0, 'the marker itself is never treated as an unsafe switch');
});
