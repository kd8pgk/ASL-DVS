const test = require('node:test');
const assert = require('node:assert/strict');
const { PAGES, normalizeNode } = require('../src/node');
const { createMonitor, targetsFor } = require('../src/status');

const talker = PAGES.find((p) => p.id === 'talker');
const controller = PAGES.find((p) => p.id === 'controller');

function node(extra) {
  return normalizeNode({ id: 'n1', host: 'pi.local', ...extra }).node;
}

function setup(nodes, upPorts) {
  const calls = [];
  const changes = [];
  const probe = async (t) => {
    calls.push(`${t.via}:${t.host}:${t.port}`);
    return upPorts.has(`${t.host}:${t.port}`);
  };
  const timers = [];
  const m = createMonitor({
    getNodes: () => nodes,
    getPages: () => PAGES,
    onChange: (s) => changes.push(s),
    probe,
    interval: 1000,
    setTimer: (fn, ms) => {
      const t = { fn, ms, cleared: false };
      timers.push(t);
      return t;
    },
    clearTimer: (t) => {
      t.cleared = true;
    },
  });
  return { m, calls, changes, timers };
}

test('a page is up when its port answers, down when it does not; unknown until the first look', async () => {
  const n = node();
  const s = setup([n], new Set(['pi.local:8989', 'pi.local:8993']));
  assert.equal(s.m.isDown('n1:controller'), false);
  assert.deepEqual(s.m.snapshot(), { down: [], known: [] });
  await s.m.refresh();
  assert.equal(s.m.isDown('n1:controller'), false);
  assert.equal(s.m.isDown('n1:talker'), false);
  assert.equal(s.m.isDown('n1:sysmon'), true);
  assert.equal(s.m.isDown('n1:instmon'), true);
  const snap = s.m.snapshot();
  assert.equal(snap.known.length, PAGES.length);
  assert.equal(snap.down.length, PAGES.length - 2);
  assert.ok(snap.down.includes('n1:sysmon'));
});

test('the change callback runs only when something changed', async () => {
  const up = new Set(['pi.local:8989']);
  const s = setup([node()], up);
  await s.m.refresh();
  assert.equal(s.changes.length, 1);
  await s.m.refresh();
  assert.equal(s.changes.length, 1);
  up.add('pi.local:9999');
  await s.m.refresh();
  assert.equal(s.changes.length, 2);
  assert.equal(s.m.isDown('n1:sysmon'), false);
  up.delete('pi.local:8989');
  await s.m.refresh();
  assert.equal(s.changes.length, 3);
  assert.ok(s.changes[2].down.includes('n1:controller'));
});

test('a page counts as up when the LAN or away address answers', async () => {
  const n = node({ lanIp: '192.168.1.5', awayHost: 'node.example.com', pins: ['ab'.repeat(32)], https: true });
  const s = setup([n], new Set(['192.168.1.5:8993', 'node.example.com:443']));
  await s.m.refresh();
  assert.equal(s.m.isDown('n1:talker'), false);
  assert.equal(s.m.isDown('n1:controller'), true);
  const only = setup([n], new Set(['node.example.com:443']));
  await only.m.refresh();
  assert.equal(only.m.isDown('n1:talker'), false);
  assert.equal(only.m.isDown('n1:controller'), true);
  assert.deepEqual(targetsFor(n, talker).map((t) => t.via), ['home', 'lan', 'away']);
  assert.deepEqual(targetsFor(n, controller).map((t) => t.via), ['home', 'lan']);
});

test('a node that is gone leaves the list on the next look', async () => {
  const nodes = [node(), normalizeNode({ id: 'n2', host: 'pi2.local' }).node];
  const s = setup(nodes, new Set());
  await s.m.refresh();
  assert.equal(s.m.snapshot().known.length, PAGES.length * 2);
  nodes.pop();
  await s.m.refresh();
  assert.equal(s.m.snapshot().known.length, PAGES.length);
  assert.equal(s.m.isDown('n2:controller'), false);
});

test('a look asked for during a look runs again afterwards, and never in parallel', async () => {
  let active = 0;
  let most = 0;
  let release;
  const gate = new Promise((r) => {
    release = r;
  });
  const n = node();
  const m = createMonitor({
    getNodes: () => [n],
    getPages: () => [controller],
    onChange: () => {},
    probe: async () => {
      active += 1;
      most = Math.max(most, active);
      await gate;
      active -= 1;
      return true;
    },
    setTimer: () => ({}),
    clearTimer: () => {},
  });
  const first = m.refresh();
  m.refresh();
  m.refresh();
  release();
  await first;
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(most, 1);
});

test('start looks at once and then on a timer, stop clears it, and it does not keep the app alive', async () => {
  const s = setup([node()], new Set(['pi.local:8989']));
  s.m.start();
  s.m.start();
  assert.equal(s.timers.length, 1);
  assert.equal(s.timers[0].ms, 1000);
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(s.m.isDown('n1:sysmon'), true);
  s.m.stop();
  assert.equal(s.timers[0].cleared, true);
  const real = createMonitor({ getNodes: () => [], getPages: () => [], onChange: () => {} });
  real.start();
  real.stop();
});
