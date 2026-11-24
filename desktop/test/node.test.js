const test = require('node:test');
const assert = require('node:assert/strict');
const N = require('../src/node');

test('a bare host has no scheme or port', () => {
  assert.deepEqual(N.parseAddress('pi.local'), { host: 'pi.local', port: null, https: null, explicit: false });
});

test('https address with no port gets 443, http gets 80', () => {
  assert.deepEqual(N.parseAddress('https://node.example.com'), { host: 'node.example.com', port: 443, https: true, explicit: false });
  assert.deepEqual(N.parseAddress('http://pi.local'), { host: 'pi.local', port: 80, https: false, explicit: false });
});

test('host:port without a scheme is split', () => {
  assert.deepEqual(N.parseAddress('pi.local:8993'), { host: 'pi.local', port: 8993, https: null, explicit: true });
  assert.deepEqual(N.parseAddress('[::1]:9000'), { host: '::1', port: 9000, https: null, explicit: true });
});

test('path, query and login part are dropped', () => {
  assert.deepEqual(N.parseAddress('https://user:pw@pi.local:8993/x?y#z'), { host: 'pi.local', port: 8993, https: true, explicit: true });
});

test('a bad port or scheme is left for the host check to refuse', () => {
  assert.equal(N.validHost(N.parseAddress('pi.local:abc').host), false);
  assert.equal(N.validHost(N.parseAddress('ftp://pi.local').host), false);
  assert.equal(N.parseAddress('pi.local:abc').port, null);
});

test('validHost accepts names and IPs, refuses junk', () => {
  for (const h of ['pi.local', 'node-1', '192.168.1.5', '::1', 'fe80::1']) assert.equal(N.validHost(h), true, h);
  for (const h of ['', ' ', 'a b', '-bad', 'a/b', 'a@b']) assert.equal(N.validHost(h), false, h);
});

test('normalizeNode fills defaults and ports', () => {
  const r = N.normalizeNode({ name: ' Home ', host: 'pi.local' });
  assert.equal(r.node.name, 'Home');
  assert.equal(r.node.https, false);
  assert.deepEqual(r.node.ports, { controller: 8989, talker: 8993, sysmon: 9999, nodemon: 7777, recorder: 8995, wifimon: 8991, h44: 9997 });
  assert.ok(r.node.id);
});

test('a scheme in the address sets https', () => {
  assert.equal(N.normalizeNode({ host: 'https://pi.local' }).node.https, true);
  assert.equal(N.normalizeNode({ host: 'http://pi.local', https: true }).node.https, false);
});

test('a port in the address is refused', () => {
  assert.match(N.normalizeNode({ host: 'pi.local:8993' }).error, /ports/i);
  assert.match(N.normalizeNode({ host: 'https://pi.local:8993' }).error, /ports/i);
});

test('page ports are checked', () => {
  assert.match(N.normalizeNode({ host: 'pi.local', ports: { talker: '0' } }).error, /Node Talker port/);
  assert.match(N.normalizeNode({ host: 'pi.local', ports: { controller: 'x' } }).error, /Node Controller port/);
  assert.equal(N.normalizeNode({ host: 'pi.local', ports: { talker: '9000' } }).node.ports.talker, 9000);
});

test('away address defaults to https 443 and keeps a port', () => {
  const a = N.normalizeNode({ host: 'pi.local', awayHost: 'node.example.com' }).node;
  assert.deepEqual([a.awayHost, a.awayPort, a.awayHttps], ['node.example.com', 443, true]);
  const b = N.normalizeNode({ host: 'pi.local', awayHost: 'https://node.example.com:8443' }).node;
  assert.deepEqual([b.awayHost, b.awayPort, b.awayHttps], ['node.example.com', 8443, true]);
  assert.match(N.normalizeNode({ host: 'pi.local', awayHost: 'ftp://x' }).error, /Away/);
});

test('LAN address must be IPv4', () => {
  assert.equal(N.normalizeNode({ host: 'pi.local', lanIp: '192.168.1.5' }).node.lanIp, '192.168.1.5');
  assert.match(N.normalizeNode({ host: 'pi.local', lanIp: '300.1.1.1' }).error, /LAN/);
  assert.match(N.normalizeNode({ host: 'pi.local', lanIp: 'pi2.local' }).error, /LAN/);
});

test('a pin is kept only when it is a sha-256 hex string', () => {
  const hex = 'ab'.repeat(32);
  assert.equal(N.normalizeNode({ host: 'h', pin: hex.toUpperCase() }).node.pin, hex);
  assert.equal(N.normalizeNode({ host: 'h', pin: (hex.match(/../g)).join(':') }).node.pin, hex);
  assert.equal(N.normalizeNode({ host: 'h', pin: 'abc' }).node.pin, '');
});

test('targets: home, lan and away rules', () => {
  const talker = N.PAGES.find((p) => p.id === 'talker');
  const controller = N.PAGES.find((p) => p.id === 'controller');
  const n = N.normalizeNode({ host: 'pi.local', https: true, lanIp: '192.168.1.5', awayHost: 'node.example.com' }).node;
  assert.equal(N.originOf(N.homeTarget(n, talker)), 'https://pi.local:8993');
  assert.equal(N.lanTarget(n, talker), null);
  n.pin = 'cd'.repeat(32);
  assert.equal(N.originOf(N.lanTarget(n, talker)), 'https://192.168.1.5:8993');
  assert.equal(N.originOf(N.awayTarget(n, talker)), 'https://node.example.com:443');
  assert.equal(N.awayTarget(n, controller), null);
  const plain = N.normalizeNode({ host: 'pi.local', lanIp: '192.168.1.5' }).node;
  assert.equal(N.originOf(N.lanTarget(plain, talker)), 'http://192.168.1.5:8993');
  assert.equal(N.lanTarget(N.normalizeNode({ host: '192.168.1.5', lanIp: '192.168.1.5' }).node, talker), null);
});

test('sameOrigin compares scheme, host and port', () => {
  const t = { host: 'pi.local', port: 8993, https: true };
  assert.equal(N.sameOrigin('https://pi.local:8993/api/x', t), true);
  assert.equal(N.sameOrigin('http://pi.local:8993/', t), false);
  assert.equal(N.sameOrigin('https://pi.local:8989/', t), false);
  assert.equal(N.sameOrigin('https://other.example/', t), false);
  assert.equal(N.sameOrigin('not a url', t), false);
});

test('matchPage finds the hardwired page a link points at, on any of the node addresses', () => {
  const a = N.normalizeNode({ id: 'a', host: 'pi.local', https: true, ports: { controller: 8989, talker: 8993 }, lanIp: '192.168.1.5', awayHost: 'node.example.com', pin: 'ab'.repeat(32) }).node;
  const b = N.normalizeNode({ id: 'b', host: '10.1.1.1' }).node;
  const nodes = [a, b];
  assert.deepEqual(N.matchPage('https://pi.local:8993/', nodes), { nodeId: 'a', pageId: 'talker' });
  assert.deepEqual(N.matchPage('https://pi.local:8989/x?y=1', nodes), { nodeId: 'a', pageId: 'controller' });
  assert.deepEqual(N.matchPage('https://192.168.1.5:8993/', nodes), { nodeId: 'a', pageId: 'talker' });
  assert.deepEqual(N.matchPage('https://node.example.com/', nodes), { nodeId: 'a', pageId: 'talker' });
  assert.deepEqual(N.matchPage('http://10.1.1.1:8989/', nodes), { nodeId: 'b', pageId: 'controller' });
});

test('matchPage ignores other tools, other schemes and other hosts', () => {
  const a = N.normalizeNode({ id: 'a', host: 'pi.local', https: true }).node;
  for (const u of ['https://pi.local:9998/', 'https://pi.local:8990/', 'http://pi.local:8993/', 'https://other.example:8993/', 'https://pi.local.evil.example:8993/', 'ftp://pi.local:8993/', 'junk', '']) {
    assert.equal(N.matchPage(u, [a]), null, u);
  }
  assert.equal(N.matchPage('https://node.example.com/', [a]), null);
});

test('the hardwired pages and their default ports; only 44helper is single-only', () => {
  assert.deepEqual(N.PAGES.map((p) => [p.id, p.label, p.port, p.away, Boolean(p.single)]), [
    ['controller', 'Node Controller', 8989, false, false],
    ['talker', 'Node Talker', 8993, true, false],
    ['sysmon', 'SysMon', 9999, false, false],
    ['nodemon', 'Node Monitor', 7777, false, false],
    ['recorder', 'Node Recorder', 8995, false, false],
    ['wifimon', 'WifiMon', 8991, false, false],
    ['h44', '44helper', 9997, false, true],
  ]);
});

test('a node saved before SysMon and Node Monitor existed gets their default ports', () => {
  const n = N.normalizeNode({ id: 'old', host: 'pi.local', ports: { controller: 8989, talker: 8993 } }).node;
  assert.equal(n.ports.sysmon, 9999);
  assert.equal(n.ports.nodemon, 7777);
  assert.deepEqual([n.ports.recorder, n.ports.wifimon, n.ports.h44], [8995, 8991, 9997]);
});

test('ports of the new pages are checked and used', () => {
  assert.match(N.normalizeNode({ host: 'pi.local', ports: { sysmon: '0' } }).error, /SysMon port/);
  assert.match(N.normalizeNode({ host: 'pi.local', ports: { nodemon: 'x' } }).error, /Node Monitor port/);
  const n = N.normalizeNode({ id: 'a', host: 'pi.local', ports: { sysmon: '9100', nodemon: '7700' } }).node;
  assert.deepEqual(N.matchPage('http://pi.local:9100/', [n]), { nodeId: 'a', pageId: 'sysmon' });
  assert.deepEqual(N.matchPage('http://pi.local:7700/', [n]), { nodeId: 'a', pageId: 'nodemon' });
  assert.equal(N.matchPage('http://pi.local:9999/', [n]), null);
});

test('only Node Talker can use the away address', () => {
  const n = N.normalizeNode({ id: 'a', host: 'pi.local', awayHost: 'node.example.com' }).node;
  for (const p of N.PAGES) assert.equal(Boolean(N.awayTarget(n, p)), p.id === 'talker', p.id);
});

test('links to the new pages stay in the app, on any of the node addresses', () => {
  const n = N.normalizeNode({ id: 'a', host: 'pi.local' }).node;
  assert.deepEqual(N.matchPage('http://pi.local:8995/', [n]), { nodeId: 'a', pageId: 'recorder' });
  assert.deepEqual(N.matchPage('http://pi.local:8991/', [n]), { nodeId: 'a', pageId: 'wifimon' });
  assert.deepEqual(N.matchPage('http://pi.local:9997/', [n]), { nodeId: 'a', pageId: 'h44' });
  assert.equal(N.matchPage('http://pi.local:8990/', [n]), null);
});
