const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const L = require('../src/layout');
const P = require('../src/presets');

const NODES = [{ id: 'a' }, { id: 'b' }];
const PAGES = [{ id: 'controller' }, { id: 'talker' }, { id: 'sysmon' }, { id: 'nodemon' }];

function built() {
  let s = L.emptyState();
  for (const [n, p] of [['a', 'controller'], ['a', 'talker'], ['b', 'sysmon'], ['b', 'nodemon']]) s = L.addTab(s, n, p);
  s = L.putInSlot(s, 'a:controller', 'left');
  s = L.putInSlot(s, 'b:nodemon', 'left');
  s = L.putInSlot(s, 'a:talker', 'right');
  s = L.putInSlot(s, 'b:sysmon', 'lower');
  s = L.openKey(s, 'a:controller');
  return L.setRatio(s, 0.4);
}

function tmp() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncp-')), 'splits.json');
}

const it = (n, p) => ({ nodeId: n, pageId: p });

test('a preset needs a name and two to twelve different pages', () => {
  const ok = { name: 'n', slots: { left: [it('a', 'x')], right: [it('a', 'y')], lower: [] } };
  assert.ok(P.normalizePreset(ok));
  assert.equal(P.normalizePreset({ ...ok, name: '   ' }), null);
  assert.equal(P.normalizePreset({ name: 'n', slots: { left: [it('a', 'x')], right: [], lower: [] } }), null);
  assert.equal(P.normalizePreset({ name: 'n', slots: { left: [it('a', 'x'), it('a', 'x')], right: [], lower: [] } }), null);
  assert.equal(P.normalizePreset({ name: 'n', slots: { left: [it('a', 'x')], right: [it('a', 'x')], lower: [] } }), null);
  assert.equal(P.normalizePreset({ name: 'n', slots: { left: [it('a', 'x'), { nodeId: 1 }], right: [it('a', 'y')], lower: [] } }), null);
  const many = Array.from({ length: 13 }, (_, i) => it('a', `p${i}`));
  assert.equal(P.normalizePreset({ name: 'n', slots: { left: many, right: [], lower: [] } }), null);
  assert.equal(P.normalizePreset(null), null);
  const p = P.normalizePreset({ ...ok, name: '  Shack  ', ratio: 7 });
  assert.deepEqual([p.name, p.ratio], ['Shack', 0.9]);
  assert.equal(P.normalizePreset({ ...ok, name: 'x'.repeat(100) }).name.length, P.NAME_MAX);
});

test('the selected page of each slot is kept, or the first one', () => {
  const p = P.normalizePreset({ name: 'n', slots: { left: [it('a', 'x'), it('a', 'y')], right: [it('b', 'z')], lower: [] }, sel: { left: it('a', 'y'), right: it('nope', 'q') } });
  assert.deepEqual(p.sel, { left: it('a', 'y'), right: it('b', 'z'), lower: null });
});

test('a 0.5.0 saved split (two or three pages) reads as left, right and lower', () => {
  const two = P.normalizePreset({ name: 'old', mode: 'cols', items: [it('a', 'x'), it('a', 'y')], ratio: 0.3 });
  assert.deepEqual(two.slots, { left: [it('a', 'x')], right: [it('a', 'y')], lower: [] });
  const three = P.normalizePreset({ name: 'old3', mode: 'trio', items: [it('a', 'x'), it('a', 'y'), it('b', 'x')] });
  assert.deepEqual(three.slots.lower, [it('b', 'x')]);
  assert.equal(P.count(three), 3);
});

test('saving takes the slots with their stacks, selections and divider position', () => {
  const r = P.fromState(built(), 'My slots');
  assert.deepEqual(r.preset.slots.left, [it('a', 'controller'), it('b', 'nodemon')]);
  assert.deepEqual(r.preset.slots.right, [it('a', 'talker')]);
  assert.deepEqual(r.preset.slots.lower, [it('b', 'sysmon')]);
  assert.deepEqual(r.preset.sel.left, it('a', 'controller'));
  assert.equal(r.preset.ratio, 0.4);
  assert.equal(P.count(r.preset), 4);
  const alone = L.showAlone(built(), 'a:talker');
  assert.equal(P.fromState(alone, 'Back').preset.slots.left.length, 2);
});

test('saving refuses with fewer than two pages in slots, or no name', () => {
  const one = L.putInSlot(L.openTab(L.emptyState(), 'a', 'controller'), 'a:controller', 'left');
  assert.match(P.fromState(one, 'x').error, /nothing to save/);
  assert.match(P.fromState(built(), '   ').error, /name/);
});

test('a split keeps its Last Heard panels by name and address, and applying it reopens them', () => {
  const lh = L.putInSlot(L.putInSlot(L.openLastHeard(L.addTab(L.emptyState(), 'a', 'talker'), 'a', 'https://lh.example/x', 'TGIF'), 'lh:tgif', 'left'), 'a:talker', 'right');
  const made = P.fromState(lh, 'Both');
  assert.equal(made.error, undefined);
  assert.deepEqual(made.preset.slots.left, [{ kind: 'lh', nodeId: 'a', name: 'TGIF', url: 'https://lh.example/x' }]);
  const list = P.put([], made.preset).list;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nc-splits-'));
  const store = P.createPresetStore(path.join(dir, 'splits.json'));
  store.save(list);
  const loaded = store.load();
  assert.deepEqual(loaded[0].slots.left, [{ kind: 'lh', nodeId: 'a', name: 'TGIF', url: 'https://lh.example/x' }]);
  const ok = (u) => u.startsWith('https://lh.example/');
  const r = P.apply(L.emptyState(), loaded[0], NODES, PAGES, ok);
  assert.equal(r.error, undefined);
  assert.equal(r.state.tabs.find((t) => t.key === 'lh:tgif').url, 'https://lh.example/x');
  assert.equal(r.state.sel.left, 'lh:tgif');
  const bad = P.apply(L.emptyState(), loaded[0], NODES, PAGES, () => false);
  assert.match(bad.error, /not allowed/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('saving under an existing name replaces it, and the list is capped', () => {
  const mk = (name) => P.fromState(built(), name).preset;
  let list = P.put([], mk('One')).list;
  const id = list[0].id;
  list = P.put(list, { ...mk('one'), ratio: 0.2 }).list;
  assert.equal(list.length, 1);
  assert.deepEqual([list[0].id, list[0].ratio], [id, 0.2]);
  for (let i = 0; i < P.MAX - 1; i += 1) list = P.put(list, mk(`n${i}`)).list;
  assert.equal(list.length, P.MAX);
  assert.match(P.put(list, mk('too many')).error, /20/);
});

test('applying opens the missing pages and shows the slots as saved', () => {
  const preset = P.fromState(built(), 'T').preset;
  const r = P.apply(L.openTab(L.emptyState(), 'a', 'controller'), preset, NODES, PAGES);
  assert.equal(r.state.view, 'slots');
  assert.deepEqual(r.state.slots.left, ['a:controller', 'b:nodemon']);
  assert.deepEqual(L.shown(r.state), ['a:controller', 'a:talker', 'b:sysmon']);
  assert.equal(r.state.ratio, 0.4);
  assert.equal(r.state.tabs.length, 4);
});

test('applying refuses a split that uses a deleted node or page', () => {
  const preset = P.fromState(built(), 'T').preset;
  assert.match(P.apply(L.emptyState(), preset, [{ id: 'a' }], PAGES).error, /deleted/);
  assert.match(P.apply(L.emptyState(), preset, NODES, [{ id: 'controller' }]).error, /does not exist/);
});

test('the file keeps splits across a restart and ignores a broken file or entries', () => {
  const f = tmp();
  const s = P.createPresetStore(f);
  assert.deepEqual(s.load(), []);
  const preset = P.fromState(built(), 'Keep').preset;
  s.save([preset]);
  assert.deepEqual(s.load(), [preset]);
  fs.writeFileSync(f, JSON.stringify({ splits: [preset, { name: 'bad' }, null, preset] }));
  assert.deepEqual(s.load(), [preset]);
  fs.writeFileSync(f, '{nope');
  assert.deepEqual(s.load(), []);
  fs.writeFileSync(f, JSON.stringify({ version: 1, splits: [{ id: 'x', name: 'old', mode: 'cols', items: [it('a', 'x'), it('a', 'y')], ratio: 0.5 }] }));
  assert.equal(s.load()[0].slots.right.length, 1);
});
