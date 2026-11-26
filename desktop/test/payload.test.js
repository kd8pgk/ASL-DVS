const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/layout');
const { labelOf, shortLabel, buildPayload } = require('../src/payload');

const nodes = [{ id: 'a', name: 'magicbox', host: 'magicbox.local' }, { id: 'b', name: '', host: 'pi.local' }];
const grid = L.grid(1280, 800);

function base(extra = {}) {
  let ls = L.emptyState();
  ls = L.openTab(ls, 'a', 'controller');
  return { ls, nodes, splits: [], rt: new Map(), grid, down: [], overlay: false, restart: false, ...extra };
}

test('labels name the node (or its host) and the page; Last Heard is named for its network', () => {
  assert.equal(labelOf({ nodeId: 'a', pageId: 'talker' }, nodes), 'magicbox · Node Talker');
  assert.equal(labelOf({ nodeId: 'b', pageId: 'sysmon' }, nodes), 'pi.local · SysMon');
  assert.equal(labelOf({ nodeId: 'gone', pageId: 'nope' }, nodes), '? · ?');
  assert.equal(labelOf({ kind: 'lh', name: 'TGIF' }, nodes), 'TGIF');
  const ls = L.openTab(L.emptyState(), 'a', 'nodemon');
  assert.equal(shortLabel(ls, ls.tabs[0].key), 'Node Monitor');
  assert.equal(shortLabel(ls, 'missing'), '');
});

test('one open page: a single pane, the tab shown and focused, loading until the view says otherwise', () => {
  const p = buildPayload(base());
  assert.deepEqual(p.grid, { sidebar: grid.sidebar, header: grid.header, strip: grid.strip });
  assert.equal(p.tabs.length, 1);
  assert.deepEqual([p.tabs[0].label, p.tabs[0].shown, p.tabs[0].focused, p.tabs[0].status, p.tabs[0].idle], ['magicbox · Node Controller', true, true, 'idle', true]);
  assert.equal(p.panes.length, 1);
  assert.equal(p.panes[0].status, 'loading');
  assert.equal(p.panes[0].error, null);
  assert.equal(p.strips, false);
  assert.equal(p.canSave, false);
});

test('the view state, errors, splits and flags pass through', () => {
  const b = base({ overlay: true, restart: true, down: ['a:sysmon'], splits: [{ id: 's1', name: 'Mine', slots: { left: [{}], right: [{}], lower: [] } }] });
  const key = b.ls.tabs[0].key;
  b.rt.set(key, { status: 'failed', idle: false, via: 'lan', error: { message: 'nope' } });
  const p = buildPayload(b);
  assert.deepEqual([p.overlay, p.restart, p.down], [true, true, ['a:sysmon']]);
  assert.deepEqual(p.splits, [{ id: 's1', name: 'Mine', count: 2 }]);
  assert.deepEqual([p.tabs[0].status, p.tabs[0].idle, p.tabs[0].via], ['failed', false, 'lan']);
  assert.deepEqual(p.panes[0].error, { message: 'nope' });
});

test('three slots give three panes with strips, stacks and dividers', () => {
  let ls = L.emptyState();
  for (const [pg, sl] of [['controller', 'left'], ['talker', 'right'], ['nodemon', 'lower']]) {
    ls = L.addTab(ls, 'a', pg);
    ls = L.putInSlot(ls, L.keyOf('a', pg), sl);
  }
  const p = buildPayload({ ...base(), ls });
  assert.equal(p.panes.length, 3);
  assert.equal(p.strips, true);
  assert.equal(p.canSave, true);
  assert.deepEqual(p.slots.map((s) => s.pages.length), [1, 1, 1]);
  assert.ok(p.dividers.length >= 1);
  assert.ok(p.panes.every((x) => x.zoom > 0 && x.zoom <= 1));
});
