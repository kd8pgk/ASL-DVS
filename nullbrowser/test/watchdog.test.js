const test = require('node:test');
const assert = require('node:assert/strict');
const W = require('../src/watchdog');

function clock(start = 0) {
  let t = start;
  return { now: () => t, advance: (ms) => { t += ms; } };
}

test('a site that crashes twice inside the window is flagged, not once, and the count resets after', () => {
  const flags = [];
  const c = clock();
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]), now: c.now });
  w.noteCrash('bad.test');
  assert.deepEqual(flags, []);
  c.advance(1000);
  w.noteCrash('bad.test');
  assert.deepEqual(flags, [['bad.test', 'crashed repeatedly']]);
  c.advance(1000);
  w.noteCrash('bad.test');
  assert.equal(flags.length, 1, 'the count was reset after flagging, so a single further crash does not re-flag');
});

test('a crash outside the window does not count toward the one before it', () => {
  const flags = [];
  const c = clock();
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]), now: c.now });
  w.noteCrash('x.test');
  c.advance(W.CRASH_WINDOW_MS + 1);
  w.noteCrash('x.test');
  assert.deepEqual(flags, [], 'the first crash aged out of the window');
});

test('crash counts are kept separately per site', () => {
  const flags = [];
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]) });
  w.noteCrash('a.test');
  w.noteCrash('b.test');
  assert.deepEqual(flags, []);
});

test('fake files flag after two within the window', () => {
  const flags = [];
  const c = clock();
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]), now: c.now });
  w.noteFakeFile('evil.test');
  assert.deepEqual(flags, []);
  w.noteFakeFile('evil.test');
  assert.deepEqual(flags, [['evil.test', 'sent disguised files repeatedly']]);
});

test('the pop-up cap flags after three hits within the window', () => {
  const flags = [];
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]) });
  w.notePopupCapped('ads.test');
  w.notePopupCapped('ads.test');
  assert.deepEqual(flags, []);
  w.notePopupCapped('ads.test');
  assert.deepEqual(flags, [['ads.test', 'kept opening pop-ups after being capped']]);
});

test('fan-out flags once enough distinct hosts are seen for one site inside the window, then starts over', () => {
  const flags = [];
  const c = clock();
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]), now: c.now });
  for (let i = 0; i < W.FANOUT_HOSTS - 1; i += 1) w.noteSubresource('many.test', `h${i}.test`);
  assert.deepEqual(flags, []);
  w.noteSubresource('many.test', 'last.test');
  assert.deepEqual(flags, [['many.test', 'contacted many different hosts at once']]);
  w.noteSubresource('many.test', 'one-more.test');
  assert.equal(flags.length, 1, 'the set was cleared after flagging');
});

test('fan-out counts only the current site, and only within the window', () => {
  const flags = [];
  const c = clock();
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]), now: c.now });
  for (let i = 0; i < W.FANOUT_HOSTS - 1; i += 1) w.noteSubresource('one.test', `h${i}.test`);
  w.noteSubresource('two.test', 'other.test');
  assert.deepEqual(flags, [], 'a different site in between does not carry the count over');
  for (let i = 0; i < W.FANOUT_HOSTS - 1; i += 1) w.noteSubresource('one.test', `k${i}.test`);
  c.advance(W.FANOUT_WINDOW_MS + 1);
  w.noteSubresource('one.test', 'late.test');
  assert.deepEqual(flags, [], 'the window elapsed, so the count started over');
});

test('CPU flags after enough consecutive idle, high samples for one site; a busy or low sample resets it', () => {
  const flags = [];
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]) });
  for (let i = 0; i < W.CPU_SAMPLES - 1; i += 1) w.noteCpu('miner.test', true, 90);
  assert.deepEqual(flags, []);
  w.noteCpu('miner.test', false, 90);
  w.noteCpu('miner.test', true, 90);
  assert.deepEqual(flags, [], 'a not-idle sample in between reset the streak');
  for (let i = 0; i < W.CPU_SAMPLES - 1; i += 1) w.noteCpu('miner.test', true, 90);
  w.noteCpu('miner.test', true, 90);
  assert.deepEqual(flags, [['miner.test', 'used heavy CPU while idle']]);
});

test('an empty site never flags anything', () => {
  const flags = [];
  const w = W.createWatchdog({ onFlag: (site, reason) => flags.push([site, reason]) });
  for (let i = 0; i < 10; i += 1) {
    w.noteCrash('');
    w.noteFakeFile('');
    w.notePopupCapped('');
    w.noteSubresource('', 'h.test');
    w.noteCpu('', true, 99);
  }
  assert.deepEqual(flags, []);
});
