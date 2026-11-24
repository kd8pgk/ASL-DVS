const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const L = require('../src/layout');
const P = require('../src/presets');

const NODES = [{ id: 'a' }, { id: 'b' }];
const PAGES = [{ id: 'controller' }, { id: 'talker' }, { id: 'sysmon' }];

function trio() {
  let s = L.emptyState();
  for (const [n, p] of [['a', 'controller'], ['a', 'talker'], ['b', 'sysmon']]) s = L.addTab(s, n, p);
  return L.applyArrangement(s, 'trio', ['a:controller', 'a:talker', 'b:sysmon'], 0.4);
}

function tmp() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncp-')), 'splits.json');
}

test('a preset needs a name and two or three different pages', () => {
  const item = (n, p) => ({ nodeId: n, pageId: p });
  assert.equal(P.normalizePreset({ name: '', items: [item('a', 'x'), item('a', 'y')] }), null);
  assert.equal(P.normalizePreset({ name: 'n', items: [item('a', 'x')] }), null);
  assert.equal(P.normalizePreset({ name: 'n', items: [item('a', 'x'), item('a', 'x')] }), null);
  assert.equal(P.normalizePreset({ name: 'n', items: [item('a', 'x'), item('a', 'y'), item('b', 'x'), item('b', 'y')] }), null);
  assert.equal(P.normalizePreset({ name: 'n', items: [item('a', 'x'), { nodeId: 1 }] }), null);
  assert.equal(P.normalizePreset(null), null);
  const ok = P.normalizePreset({ name: '  Shack  ', items: [item('a', 'x'), item('a', 'y')], ratio: 7 });
  assert.deepEqual([ok.name, ok.mode, ok.ratio], ['Shack', 'cols', 0.9]);
  assert.equal(P.normalizePreset({ name: 'n', items: [item('a', 'x'), item('a', 'y'), item('b', 'x')] }).mode, 'trio');
  assert.equal(P.normalizePreset({ name: 'x'.repeat(100), items: [item('a', 'x'), item('a', 'y')] }).name.length, P.NAME_MAX);
});

test('saving takes the split on screen, or the one to come back to', () => {
  const s = trio();
  const r = P.fromState(s, 'My trio');
  assert.deepEqual(r.preset.items.map((i) => `${i.nodeId}:${i.pageId}`), ['a:controller', 'a:talker', 'b:sysmon']);
  assert.equal(r.preset.mode, 'trio');
  assert.equal(r.preset.ratio, 0.4);
  const alone = L.showAlone(s, 'a:talker');
  assert.equal(P.fromState(alone, 'Back').preset.items.length, 3);
});

test('saving refuses when there is no split, no name, or Last Heard is in it', () => {
  const one = L.openTab(L.emptyState(), 'a', 'controller');
  assert.match(P.fromState(one, 'x').error, /no split/);
  assert.match(P.fromState(trio(), '   ').error, /name/);
  const withLh = L.dropKey(L.openLastHeard(L.addTab(L.emptyState(), 'a', 'talker'), 'a', 'https://lh.example/x'), 'a:talker', 'right');
  assert.match(P.fromState(withLh, 'x').error, /Last Heard/);
});

test('saving under an existing name replaces it, and the list is capped', () => {
  const mk = (name) => P.fromState(trio(), name).preset;
  let list = [];
  list = P.put(list, mk('One')).list;
  const id = list[0].id;
  list = P.put(list, { ...mk('one'), ratio: 0.2 }).list;
  assert.equal(list.length, 1);
  assert.equal(list[0].id, id);
  assert.equal(list[0].ratio, 0.2);
  for (let i = 0; i < P.MAX - 1; i += 1) list = P.put(list, mk(`n${i}`)).list;
  assert.equal(list.length, P.MAX);
  assert.match(P.put(list, mk('too many')).error, /20/);
});

test('applying opens the missing tabs, shows the split and sets the ratio', () => {
  const preset = P.fromState(trio(), 'T').preset;
  const r = P.apply(L.openTab(L.emptyState(), 'a', 'controller'), preset, NODES, PAGES);
  assert.equal(r.state.mode, 'trio');
  assert.deepEqual(r.state.panes, ['a:controller', 'a:talker', 'b:sysmon']);
  assert.equal(r.state.ratio, 0.4);
  assert.equal(r.state.tabs.length, 3);
});

test('applying refuses a split that uses a deleted node or page', () => {
  const preset = P.fromState(trio(), 'T').preset;
  assert.match(P.apply(L.emptyState(), preset, [{ id: 'a' }], PAGES).error, /deleted/);
  assert.match(P.apply(L.emptyState(), preset, NODES, [{ id: 'controller' }]).error, /does not exist/);
});

test('the file keeps splits across a restart and ignores a broken file or entries', () => {
  const f = tmp();
  const s = P.createPresetStore(f);
  assert.deepEqual(s.load(), []);
  const preset = P.fromState(trio(), 'Keep').preset;
  s.save([preset]);
  assert.deepEqual(s.load(), [preset]);
  fs.writeFileSync(f, JSON.stringify({ splits: [preset, { name: 'bad' }, null, preset] }));
  assert.deepEqual(s.load(), [preset]);
  fs.writeFileSync(f, '{nope');
  assert.deepEqual(s.load(), []);
});
