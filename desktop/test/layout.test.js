const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/layout');

const PAGES = [{ id: 'controller' }, { id: 'talker' }];
const NODES = [{ id: 'a' }, { id: 'b' }];

function two() {
  return L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'talker');
}

function three() {
  return L.openTab(two(), 'b', 'controller');
}

test('grid: sidebar is 3 of 15 units and the header is 1 unit', () => {
  for (const [w, sidebar, header] of [[1280, 256, 85], [1600, 320, 107], [1920, 384, 128], [1500, 300, 100]]) {
    const g = L.grid(w, 800);
    assert.equal(g.sidebar, sidebar, `sidebar at ${w}`);
    assert.equal(g.header, header, `header at ${w}`);
    assert.deepEqual(g.area, { x: sidebar, y: header, w: w - sidebar, h: 800 - header });
  }
});

test('grid never gives a negative area', () => {
  const g = L.grid(10, 1);
  assert.equal(g.area.h, 0);
  assert.ok(g.area.w >= 0);
});

test('opening a page makes a tab and shows it', () => {
  const s = L.openTab(L.emptyState(), 'a', 'controller');
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.deepEqual(s.panes, ['a:controller', null, null]);
});

test('opening the same page again does not duplicate the tab', () => {
  const s = L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'controller');
  assert.equal(s.tabs.length, 1);
});

test('in single mode a new tab replaces the shown one', () => {
  const s = two();
  assert.equal(s.tabs.length, 2);
  assert.deepEqual(s.panes, ['a:talker', null, null]);
});

test('a split needs as many tabs as panes', () => {
  const one = L.openTab(L.emptyState(), 'a', 'controller');
  assert.equal(L.setMode(one, 'cols').mode, 'single');
  assert.equal(L.setMode(one, 'trio').mode, 'single');
  assert.equal(L.setMode(two(), 'trio').mode, 'single');
  assert.equal(L.setMode(two(), 'cols').mode, 'cols');
  assert.equal(L.setMode(three(), 'trio').mode, 'trio');
});

test('rows is not a mode any more', () => {
  assert.deepEqual(L.MODES, ['single', 'cols', 'trio']);
  assert.equal(L.setMode(two(), 'rows').mode, 'single');
});

test('single to two pages follows tab order and keeps focus on the page you were on', () => {
  const s = L.setMode(two(), 'cols');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', null]);
  assert.equal(s.focus, 1);
});

test('single to three pages uses the first three tabs in order', () => {
  const s = L.setMode(three(), 'trio');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', 'b:controller']);
  assert.equal(s.focus, 2);
});

test('single to three pages keeps a shown page that is not among the first three', () => {
  let s = L.openTab(three(), 'b', 'talker');
  s = L.setMode(s, 'trio');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', 'b:talker']);
  assert.equal(s.focus, 2);
});

test('two pages to three keeps the top two and adds another tab below', () => {
  let s = L.setMode(three(), 'cols');
  assert.equal(s.mode, 'cols');
  s = L.setMode(s, 'trio');
  assert.equal(s.panes.length, 3);
  assert.equal(new Set(s.panes).size, 3);
  assert.deepEqual(s.panes.slice(0, 2), L.shown(L.setMode(three(), 'cols')));
});

test('three pages to two keeps the focused page', () => {
  let s = L.setMode(three(), 'trio');
  s = L.focusPane(s, 2);
  s = L.setMode(s, 'cols');
  assert.deepEqual(s.panes.slice(0, 2), ['a:controller', 'b:controller']);
  assert.equal(s.focus, 1);
  s = L.focusPane(L.setMode(three(), 'trio'), 0);
  s = L.setMode(s, 'cols');
  assert.deepEqual(s.panes.slice(0, 2), ['a:controller', 'a:talker']);
  assert.equal(s.focus, 0);
});

test('back to single keeps the focused pane tab', () => {
  let s = L.setMode(three(), 'trio');
  s = L.focusPane(s, 1);
  s = L.setMode(s, 'single');
  assert.deepEqual(s.panes, ['a:talker', null, null]);
  assert.equal(s.focus, 0);
});

test('in a split, opening a page goes into the focused pane', () => {
  let s = L.setMode(three(), 'cols');
  assert.deepEqual(L.shown(s), ['a:controller', 'b:controller']);
  s = L.focusPane(s, 0);
  s = L.openKey(s, 'a:talker');
  assert.deepEqual(L.shown(s), ['a:talker', 'b:controller']);
});

test('opening a tab already shown only moves focus', () => {
  let s = L.setMode(two(), 'cols');
  s = L.openKey(s, 'a:controller');
  assert.equal(s.focus, 0);
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', null]);
});

test('closing a tab in a split of two goes back to single', () => {
  let s = L.setMode(two(), 'cols');
  s = L.closeTab(s, 'a:talker');
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:controller', null, null]);
});

test('closing a tab in three pages goes to two with the others kept', () => {
  let s = L.setMode(three(), 'trio');
  s = L.closeTab(s, 'a:talker');
  assert.equal(s.mode, 'cols');
  assert.deepEqual(L.shown(s), ['a:controller', 'b:controller']);
});

test('closing a tab in three pages of four fills the pane with the other tab', () => {
  let s = L.setMode(L.openTab(three(), 'b', 'talker'), 'trio');
  s = L.closeTab(s, 'a:talker');
  assert.equal(s.mode, 'trio');
  assert.equal(new Set(s.panes).size, 3);
  assert.equal(s.panes.includes('a:talker'), false);
});

test('closing the last tab empties everything', () => {
  const s = L.closeTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a:controller');
  assert.deepEqual(s, { tabs: [], panes: [null, null, null], mode: 'single', ratio: 0.5, focus: 0 });
});

test('closing a node closes all its tabs', () => {
  let s = L.openTab(two(), 'b', 'talker');
  s = L.closeNode(s, 'a');
  assert.deepEqual(s.tabs.map((t) => t.key), ['b:talker']);
  assert.deepEqual(s.panes, ['b:talker', null, null]);
});

test('ratio is kept between 0.1 and 0.9 and ignores junk', () => {
  const s = L.emptyState();
  assert.equal(L.setRatio(s, 5).ratio, 0.9);
  assert.equal(L.setRatio(s, -1).ratio, 0.1);
  assert.equal(L.setRatio(s, 'x'), s);
});

test('focusPane stays within the shown panes and never lands on an empty one', () => {
  assert.equal(L.focusPane(two(), 1).focus, 0);
  assert.equal(L.focusPane(L.setMode(three(), 'trio'), 2).focus, 2);
  const cols = L.setMode(three(), 'cols');
  assert.equal(L.focusPane(cols, 2), cols);
  const t = three();
  assert.equal(L.focusPane(t, 'x'), t);
  assert.equal(L.focusPane(t, -1), t);
});

test('Last Heard in single mode opens beside the page and splits in two', () => {
  const s = L.openLastHeard(L.openTab(L.emptyState(), 'a', 'talker'), 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'cols');
  assert.deepEqual(L.shown(s), ['a:talker', 'lh']);
  assert.equal(s.focus, 1);
  assert.equal(s.tabs[1].url, 'https://lh.example/x');
});

test('Last Heard in a two page split goes to the bottom of a three page split', () => {
  const s = L.openLastHeard(L.setMode(two(), 'cols'), 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'trio');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', 'lh']);
});

test('Last Heard in a three page split replaces the bottom pane', () => {
  const s = L.openLastHeard(L.setMode(three(), 'trio'), 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'trio');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', 'lh']);
  assert.equal(s.tabs.length, 4);
});

test('a second Last Heard click reuses the tab and takes the new address', () => {
  let s = L.openLastHeard(L.setMode(three(), 'trio'), 'a', 'https://lh.example/1');
  s = L.openLastHeard(s, 'a', 'https://lh.example/2');
  assert.equal(s.tabs.filter((t) => t.key === 'lh').length, 1);
  assert.equal(s.tabs.find((t) => t.key === 'lh').url, 'https://lh.example/2');
  assert.deepEqual(s.panes, ['a:controller', 'a:talker', 'lh']);
});

test('Last Heard tab is not saved and closing it falls back', () => {
  let s = L.openLastHeard(L.setMode(three(), 'trio'), 'a', 'https://lh.example/x');
  const saved = L.serialize(s);
  assert.equal(saved.tabs.some((t) => t.pageId === 'lasthard'), false);
  assert.equal(saved.panes.includes('lh'), false);
  const back = L.restore(JSON.parse(JSON.stringify(saved)), NODES, PAGES);
  assert.equal(back.tabs.some((t) => t.key === 'lh'), false);
  s = L.closeTab(s, 'lh');
  assert.equal(s.mode, 'trio');
  s = L.closeTab(s, 'b:controller');
  assert.equal(s.mode, 'cols');
});

test('closing the source node closes its Last Heard tab too', () => {
  const s = L.closeNode(L.openLastHeard(L.setMode(three(), 'trio'), 'b', 'https://lh.example/x'), 'b');
  assert.equal(s.tabs.some((t) => t.key === 'lh'), false);
});

test('rects: one page fills the area', () => {
  const area = { x: 256, y: 85, w: 1024, h: 715 };
  assert.deepEqual(L.rects({ mode: 'single' }, area), { panes: [area], dividers: [] });
});

test('rects: two pages are 6 and 6 units with a gap, at 1280 wide', () => {
  const g = L.grid(1280, 800);
  const r = L.rects({ mode: 'cols', ratio: 0.5 }, g.area);
  assert.equal(r.panes[0].w + L.GAP + r.panes[1].w, 1024);
  assert.equal(r.panes[0].w, 509);
  assert.equal(r.panes[1].w, 509);
  assert.equal(r.panes[1].x, r.panes[0].x + r.panes[0].w + L.GAP);
  assert.deepEqual(r.dividers, [{ rect: { x: 256 + 509, y: 85, w: L.GAP, h: 715 }, axis: 'x', drag: true }]);
});

test('rects: three pages are two over one with equal rows', () => {
  const g = L.grid(1280, 800);
  const r = L.rects({ mode: 'trio', ratio: 0.5 }, g.area);
  const [a, b, c] = r.panes;
  assert.equal(a.y, b.y);
  assert.equal(a.h, b.h);
  assert.equal(c.x, g.area.x);
  assert.equal(c.w, g.area.w);
  assert.equal(c.y, a.y + a.h + L.GAP);
  assert.ok(Math.abs(c.h - a.h) <= 1);
  assert.equal(a.h + L.GAP + c.h, g.area.h);
  assert.deepEqual(r.dividers.map((d) => [d.axis, d.drag]), [['x', true], ['y', false]]);
  assert.deepEqual(r.dividers[1].rect, { x: g.area.x, y: a.y + a.h, w: g.area.w, h: L.GAP });
});

test('rects: the top row ratio moves only the vertical divider', () => {
  const g = L.grid(1280, 800);
  const r = L.rects({ mode: 'trio', ratio: 0.3 }, g.area);
  assert.ok(r.panes[0].w < r.panes[1].w);
  assert.equal(r.panes[2].w, g.area.w);
  assert.ok(Math.abs(r.panes[2].h - r.panes[0].h) <= 1);
});

test('rects: a pane never gets narrower than the minimum', () => {
  const area = { x: 0, y: 0, w: 1000, h: 700 };
  for (const mode of ['cols', 'trio']) {
    assert.ok(L.rects({ mode, ratio: 0.1 }, area).panes[0].w >= L.MIN_PANE);
    assert.ok(L.rects({ mode, ratio: 0.95 }, area).panes[1].w >= L.MIN_PANE);
  }
  const tiny = L.rects({ mode: 'cols', ratio: 0.9 }, { x: 0, y: 0, w: 400, h: 300 });
  assert.equal(tiny.panes[0].w, Math.floor(394 * 0.5));
});

test('serialize then restore gives the same layout', () => {
  let s = L.setRatio(L.setMode(three(), 'trio'), 0.3);
  s = L.focusPane(s, 1);
  const back = L.restore(JSON.parse(JSON.stringify(L.serialize(s))), NODES, PAGES);
  assert.deepEqual(back.tabs, s.tabs);
  assert.deepEqual([back.panes, back.mode, back.ratio, back.focus], [s.panes, s.mode, s.ratio, s.focus]);
});

test('restore drops tabs for missing nodes or pages and repairs the panes', () => {
  const saved = {
    tabs: [{ nodeId: 'a', pageId: 'controller' }, { nodeId: 'gone', pageId: 'talker' }, { nodeId: 'a', pageId: 'nope' }, { nodeId: 'a', pageId: 'controller' }],
    panes: ['gone:talker', 'a:controller', null],
    mode: 'trio',
    ratio: 7,
    focus: 2,
  };
  const s = L.restore(saved, NODES, PAGES);
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:controller', null, null]);
  assert.equal(s.ratio, 0.9);
  assert.equal(s.focus, 0);
});

test('restore of junk gives an empty layout', () => {
  assert.deepEqual(L.restore(null, NODES, PAGES), L.emptyState());
  assert.deepEqual(L.restore({ tabs: 5 }, NODES, PAGES), L.emptyState());
});

test('Last Heard goes left to right, then down, and never makes a fourth pane', () => {
  const four = L.openTab(three(), 'b', 'talker');
  assert.equal(four.tabs.length, 4);
  let s = L.openLastHeard(four, 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'cols');
  assert.equal(s.panes[1], 'lh');
  assert.equal(s.panes[2], null);
  s = L.openLastHeard(L.setMode(four, 'cols'), 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'trio');
  assert.equal(s.panes[2], 'lh');
  s = L.openLastHeard(L.setMode(four, 'trio'), 'a', 'https://lh.example/x');
  assert.equal(s.panes[2], 'lh');
  for (const m of L.MODES) assert.ok(L.COUNT[m] <= 3);
  assert.equal(L.shown(s).length, 3);
});

test('Last Heard from one page keeps that page on the left and puts itself on the right', () => {
  const one = L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'talker');
  const s = L.openLastHeard(one, 'a', 'https://lh.example/x');
  assert.deepEqual(L.shown(s), ['a:talker', 'lh']);
  assert.equal(L.rects(s, { x: 0, y: 0, w: 1000, h: 600 }).panes[1].x > L.rects(s, { x: 0, y: 0, w: 1000, h: 600 }).panes[0].x, true);
});

test('Last Heard from two pages keeps both on top and itself below', () => {
  const s = L.openLastHeard(L.setMode(three(), 'cols'), 'a', 'https://lh.example/x');
  const before = L.shown(L.setMode(three(), 'cols'));
  assert.deepEqual(s.panes.slice(0, 2), before);
  const r = L.rects(s, { x: 0, y: 0, w: 1000, h: 600 });
  assert.ok(r.panes[2].y > r.panes[0].y);
  assert.equal(r.panes[2].w, 1000);
});
