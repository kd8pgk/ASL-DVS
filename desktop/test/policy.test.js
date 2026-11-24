const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const P = require('../src/policy');
const { normalizeNode } = require('../src/node');

const hosts = P.hostsOfNode(normalizeNode({ host: 'Pi.local', lanIp: '192.168.1.5', awayHost: 'node.example.com' }).node);

test('hosts of a node are its address, LAN address and away address, lower-case', () => {
  assert.deepEqual(hosts, ['pi.local', '192.168.1.5', 'node.example.com']);
});

test('only the microphone, speaker choice and clipboard writes can be granted', () => {
  assert.deepEqual([...P.ALLOWED_PERMISSIONS].sort(), ['clipboard-sanitized-write', 'media', 'speaker-selection']);
  assert.equal(P.allowPermission('media', 'https://pi.local:8993', hosts, ['audio']), true);
  assert.equal(P.allowPermission('media', 'https://pi.local:8993', hosts, 'audio'), true);
  assert.equal(P.allowPermission('clipboard-sanitized-write', 'http://192.168.1.5:8993', hosts), true);
  assert.equal(P.allowPermission('speaker-selection', 'https://pi.local:8993', hosts), true);
});

test('video, mixed and unknown media is refused', () => {
  assert.equal(P.allowPermission('media', 'https://pi.local', hosts, ['audio', 'video']), false);
  assert.equal(P.allowPermission('media', 'https://pi.local', hosts, ['video']), false);
  assert.equal(P.allowPermission('media', 'https://pi.local', hosts, 'unknown'), false);
  assert.equal(P.allowPermission('media', 'https://pi.local', hosts, undefined), false);
  assert.equal(P.allowPermission('media', 'https://pi.local', hosts, []), false);
});

test('every other permission is refused, even on the node', () => {
  for (const p of ['geolocation', 'notifications', 'clipboard-read', 'midi', 'midiSysex', 'display-capture', 'fullscreen', 'openExternal', 'idle-detection', 'unknown', 'fileSystem', 'pointerLock', 'keyboardLock', 'window-management', 'storage-access']) {
    assert.equal(P.allowPermission(p, 'https://pi.local', hosts, ['audio']), false, p);
  }
});

test('a permission is refused for an origin that is not the node', () => {
  assert.equal(P.allowPermission('media', 'https://evil.example', hosts, ['audio']), false);
  assert.equal(P.allowPermission('media', 'not a url', hosts, ['audio']), false);
  assert.equal(P.allowPermission('media', '', hosts, ['audio']), false);
});

test('requests go only to the node, and data or blob', () => {
  for (const u of ['https://pi.local:8993/x', 'http://192.168.1.5/y', 'wss://node.example.com/ws', 'ws://pi.local:8993/ws', 'data:text/plain,hi', 'blob:https://pi.local/abc']) {
    assert.equal(P.allowRequest(u, hosts), true, u);
  }
  for (const u of ['https://example.org/', 'http://pi.local.evil.example/', 'file:///etc/passwd', 'ftp://pi.local/', 'chrome://gpu', 'devtools://devtools/', 'junk', 'https://pi.local@evil.example/']) {
    assert.equal(P.allowRequest(u, hosts), false, u);
  }
});

test('the shell may read only its own files', () => {
  assert.equal(P.allowShellRequest('file:///app/ui/index.html'), true);
  assert.equal(P.allowShellRequest('data:image/png;base64,AA'), true);
  assert.equal(P.allowShellRequest('https://example.org/'), false);
  assert.equal(P.allowShellRequest('ws://127.0.0.1/'), false);
  assert.equal(P.allowShellRequest('devtools://devtools/'), false);
});

test('the shell page keeps a strict content security policy', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');
  assert.match(html, /default-src 'none'/);
  const loads = html.replace(/placeholder="[^"]*"/g, '');
  assert.doesNotMatch(loads, /unsafe-inline|unsafe-eval|https?:\/\//);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)/);
});

test('no source file turns off a Chromium or Electron protection or reaches the network by itself', () => {
  const dir = path.join(__dirname, '..', 'src');
  const banned = [
    /nodeIntegration:\s*true/,
    /contextIsolation:\s*false/,
    /sandbox:\s*false/,
    /webSecurity:\s*false/,
    /allowRunningInsecureContent/,
    /webviewTag:\s*true/,
    /enableRemoteModule/,
    /ignore-certificate-errors/,
    /disable-web-security/,
    /remote-debugging/,
    /--inspect/,
    /openDevTools/,
    /autoUpdater/,
    /crashReporter/,
    /require\(['"]node:(https?|dgram|dns|tls|child_process|worker_threads)['"]\)/,
    /require\(['"](https?|dgram|dns|tls|child_process|worker_threads)['"]\)/,
    /\bfetch\(/,
    /net\.request|net\.fetch/,
    /XMLHttpRequest/,
    /executeJavaScript/,
    /\beval\(/,
    /new Function\(/,
  ];
  const listed = /remote-debugging|--inspect|ignore-certificate-errors|disable-web-security|allow-running-insecure-content/;
  for (const f of fs.readdirSync(dir)) {
    const text = fs.readFileSync(path.join(dir, f), 'utf8');
    for (const re of banned) {
      if (f === 'policy.js' && listed.test(re.source)) continue;
      assert.doesNotMatch(text, re, `${f} contains ${re}`);
    }
  }
});

test('only the route probe opens sockets', () => {
  const dir = path.join(__dirname, '..', 'src');
  const users = fs.readdirSync(dir).filter((f) => /require\(['"]node:net['"]\)|require\(['"]net['"]\)/.test(fs.readFileSync(path.join(dir, f), 'utf8')));
  assert.deepEqual(users, ['route.js']);
});

test('debugging and security-weakening switches are found, in any spelling', () => {
  assert.deepEqual(P.unsafeSwitches(['--remote-debugging-port=9222']), ['remote-debugging-port']);
  assert.deepEqual(P.unsafeSwitches(['--inspect', '--Remote-Debugging-Pipe', '-disable-web-security']), ['inspect', 'remote-debugging-pipe', 'disable-web-security']);
  assert.deepEqual(P.unsafeSwitches(['--js-flags=--expose-gc', '--proxy-server=x:1', '--user-data-dir=/tmp/x']), ['js-flags', 'proxy-server', 'user-data-dir']);
  assert.deepEqual(P.unsafeSwitches(['--ignore-certificate-errors']), ['ignore-certificate-errors']);
});

test('ordinary arguments are not flagged', () => {
  assert.deepEqual(P.unsafeSwitches([]), []);
  assert.deepEqual(P.unsafeSwitches(['--no-sandbox', '--disable-gpu', '/home/u/file.json', '--inspector-not-a-switch']), []);
});
