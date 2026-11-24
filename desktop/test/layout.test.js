const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/layout');

const PAGES = [{ id: 'controller' }, { id: 'talker' }];
const NODES = [{ id: 'a' }, { id: 'b' }];

function two() {
  let s = L.emptyState();
  s = L.openTab(s, 'a', 'controller');
  s = L.openTab(s, 'a', 'talker');
  return s;
}

test('opening a page makes a tab and shows it', () => {
  const s = L.openTab(L.emptyState(), 'a', 'controller');
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.deepEqual(s.panes, ['a:controller', null]);
});

test('opening the same page again does not duplicate the tab', () => {
  const s = L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'controller');
  assert.equal(s.tabs.length, 1);
});

test('in single mode a new tab replaces the shown one', () => {
  const s = two();
  assert.equal(s.tabs.length, 2);
  assert.deepEqual(s.panes, ['a:talker', null]);
});

test('split needs two tabs', () => {
  const one = L.openTab(L.emptyState(), 'a', 'controller');
  assert.equal(L.setMode(one, 'cols').mode, 'single');
  const s = L.setMode(two(), 'cols');
  assert.equal(s.mode, 'cols');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker']);
  assert.equal(s.focus, 1);
});

test('in a split, opening a page goes into the focused pane', () => {
  let s = L.setMode(two(), 'cols');
  s = L.openTab(s, 'b', 'talker');
  assert.deepEqual(s.panes, ['a:controller', 'b:talker']);
  s = L.focusPane(s, 0);
  s = L.openKey(s, 'a:talker');
  assert.deepEqual(s.panes, ['a:talker', 'b:talker']);
});

test('opening a tab already shown only moves focus', () => {
  let s = L.setMode(two(), 'rows');
  s = L.openKey(s, 'a:controller');
  assert.equal(s.focus, 0);
  assert.deepEqual(s.panes, ['a:controller', 'a:talker']);
});

test('back to single keeps the focused pane tab', () => {
  let s = L.setMode(two(), 'cols');
  s = L.focusPane(s, 0);
  s = L.setMode(s, 'single');
  assert.deepEqual(s.panes, ['a:controller', null]);
  assert.equal(s.focus, 0);
});

test('closing a tab in a split of two goes back to single', () => {
  let s = L.setMode(two(), 'cols');
  s = L.closeTab(s, 'a:talker');
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:controller', null]);
});

test('closing a tab in a split of three fills the pane with another tab', () => {
  let s = L.openTab(L.setMode(two(), 'cols'), 'b', 'talker');
  s = L.closeTab(s, 'b:talker');
  assert.equal(s.mode, 'cols');
  assert.deepEqual(s.panes.slice().sort(), ['a:controller', 'a:talker']);
  s = L.openTab(s, 'b', 'talker');
  s = L.closeTab(s, 'a:controller');
  assert.equal(s.mode, 'cols');
  assert.equal(s.panes.includes(null), false);
});

test('closing the last tab empties everything', () => {
  const s = L.closeTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a:controller');
  assert.deepEqual(s, { tabs: [], panes: [null, null], mode: 'single', ratio: 0.5, focus: 0 });
});

test('closing a node closes all its tabs', () => {
  let s = L.openTab(two(), 'b', 'talker');
  s = L.closeNode(s, 'a');
  assert.deepEqual(s.tabs.map((t) => t.key), ['b:talker']);
  assert.deepEqual(s.panes, ['b:talker', null]);
});

test('ratio is kept between 0.1 and 0.9 and ignores junk', () => {
  const s = L.emptyState();
  assert.equal(L.setRatio(s, 5).ratio, 0.9);
  assert.equal(L.setRatio(s, -1).ratio, 0.1);
  assert.equal(L.setRatio(s, 'x'), s);
});

test('focusPane in single mode stays on pane 0, and an empty pane cannot be focused', () => {
  assert.equal(L.focusPane(two(), 1).focus, 0);
  const s = L.openTab(L.emptyState(), 'a', 'controller');
  assert.equal(L.focusPane(s, 1).focus, 0);
});

test('rects: single, columns and rows with a gap', () => {
  const area = { x: 300, y: 48, w: 1000, h: 700 };
  assert.deepEqual(L.rects({ mode: 'single' }, area), { panes: [area], divider: null });
  const c = L.rects({ mode: 'cols', ratio: 0.5 }, area);
  assert.equal(c.panes[0].w + L.GAP + c.panes[1].w, 1000);
  assert.equal(c.panes[1].x, c.panes[0].x + c.panes[0].w + L.GAP);
  assert.deepEqual(c.divider, { x: c.panes[0].x + c.panes[0].w, y: 48, w: L.GAP, h: 700 });
  const r = L.rects({ mode: 'rows', ratio: 0.25 }, area);
  assert.equal(r.panes[0].h + L.GAP + r.panes[1].h, 700);
  assert.equal(r.panes[0].w, 1000);
});

test('rects: a pane never gets narrower than the minimum', () => {
  const area = { x: 0, y: 0, w: 1000, h: 700 };
  const c = L.rects({ mode: 'cols', ratio: 0.1 }, area);
  assert.ok(c.panes[0].w >= L.MIN_PANE);
  const d = L.rects({ mode: 'cols', ratio: 0.95 }, area);
  assert.ok(d.panes[1].w >= L.MIN_PANE);
  const tiny = L.rects({ mode: 'cols', ratio: 0.9 }, { x: 0, y: 0, w: 400, h: 300 });
  assert.equal(tiny.panes[0].w, Math.floor(394 * 0.5));
});

test('serialize then restore gives the same layout', () => {
  let s = L.setRatio(L.setMode(two(), 'rows'), 0.3);
  s = L.focusPane(s, 1);
  const back = L.restore(JSON.parse(JSON.stringify(L.serialize(s))), NODES, PAGES);
  assert.deepEqual(back.tabs, s.tabs);
  assert.deepEqual([back.panes, back.mode, back.ratio, back.focus], [s.panes, s.mode, s.ratio, s.focus]);
});

test('restore drops tabs for missing nodes or pages and repairs the panes', () => {
  const saved = {
    tabs: [{ nodeId: 'a', pageId: 'controller' }, { nodeId: 'gone', pageId: 'talker' }, { nodeId: 'a', pageId: 'nope' }, { nodeId: 'a', pageId: 'controller' }],
    panes: ['gone:talker', 'a:controller'],
    mode: 'cols',
    ratio: 7,
    focus: 1,
  };
  const s = L.restore(saved, NODES, PAGES);
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:controller', null]);
  assert.equal(s.ratio, 0.9);
});

test('restore of junk gives an empty layout', () => {
  assert.deepEqual(L.restore(null, NODES, PAGES), L.emptyState());
  assert.deepEqual(L.restore({ tabs: 5 }, NODES, PAGES), L.emptyState());
});
