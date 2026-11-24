const test = require('node:test');
const assert = require('node:assert/strict');
const { PAGES, normalizeNode } = require('../src/node');
const { createRouter, KEEP_MS } = require('../src/route');

const talker = PAGES.find((p) => p.id === 'talker');
const controller = PAGES.find((p) => p.id === 'controller');

function setup(up) {
  let t = 1000;
  const calls = [];
  const probe = async (target) => {
    calls.push(target.via);
    return up.includes(target.via);
  };
  const router = createRouter({ probe, now: () => t });
  return { router, calls, tick: (ms) => { t += ms; } };
}

function node(extra) {
  return normalizeNode({ id: 'n1', host: 'pi.local', ...extra }).node;
}

test('a node with no fallback is never probed', async () => {
  const s = setup([]);
  const t = await s.router.pick(node({}), talker);
  assert.equal(t.via, 'home');
  assert.deepEqual(s.calls, []);
});

test('home answers: home is used and no other address is tried', async () => {
  const s = setup(['home']);
  const t = await s.router.pick(node({ lanIp: '192.168.1.5', awayHost: 'node.example.com' }), talker);
  assert.equal(t.via, 'home');
  assert.deepEqual(s.calls, ['home']);
});

test('home down, LAN answers: LAN is used', async () => {
  const s = setup(['lan']);
  const t = await s.router.pick(node({ lanIp: '192.168.1.5', awayHost: 'node.example.com' }), talker);
  assert.equal(t.via, 'lan');
  assert.deepEqual(s.calls, ['home', 'lan']);
});

test('home and LAN down: away is used', async () => {
  const s = setup([]);
  const t = await s.router.pick(node({ lanIp: '192.168.1.5', awayHost: 'node.example.com' }), talker);
  assert.equal(t.via, 'away');
});

test('the away address is only for pages that allow it', async () => {
  const s = setup([]);
  const t = await s.router.pick(node({ awayHost: 'node.example.com' }), controller);
  assert.equal(t.via, 'home');
  assert.deepEqual(s.calls, []);
});

test('the answer is kept for 30 seconds, then asked again', async () => {
  const s = setup(['lan']);
  const n = node({ lanIp: '192.168.1.5' });
  await s.router.pick(n, talker);
  s.tick(KEEP_MS - 1);
  await s.router.pick(n, talker);
  assert.equal(s.calls.length, 2);
  s.tick(2);
  await s.router.pick(n, talker);
  assert.equal(s.calls.length, 4);
});

test('forget makes the next pick ask again', async () => {
  const s = setup(['home']);
  const n = node({ awayHost: 'node.example.com' });
  await s.router.pick(n, talker);
  s.router.forget('n1');
  await s.router.pick(n, talker);
  assert.equal(s.calls.length, 2);
});

test('each page keeps its own answer', async () => {
  const s = setup(['home']);
  const n = node({ lanIp: '192.168.1.5', awayHost: 'node.example.com' });
  await s.router.pick(n, talker);
  await s.router.pick(n, controller);
  assert.equal(s.calls.length, 2);
  await s.router.pick(n, talker);
  await s.router.pick(n, controller);
  assert.equal(s.calls.length, 2);
});
