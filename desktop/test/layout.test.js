const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/layout');

const PAGES = [{ id: 'controller' }, { id: 'talker' }, { id: 'sysmon' }, { id: 'nodemon' }];
const NODES = [{ id: 'a' }, { id: 'b' }];
const AREA = { x: 256, y: 85, w: 1024, h: 715 };

function two() {
  return L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'talker');
}

function three() {
  return L.openTab(two(), 'a', 'sysmon');
}

function split3() {
  let s = three();
  s = L.dropKey(s, 'a:controller', 'right');
  return L.dropKey(s, 'a:talker', 'below');
}

test('grid: sidebar is 3 of 15 units and the header is 1 unit', () => {
  for (const [w, sidebar, header] of [[1280, 256, 85], [1600, 320, 107], [1920, 384, 128], [1500, 300, 100]]) {
    const g = L.grid(w, 800);
    assert.equal(g.sidebar, sidebar, `sidebar at ${w}`);
    assert.equal(g.header, header, `header at ${w}`);
    assert.equal(g.strip, 28);
    assert.deepEqual(g.area, { x: sidebar, y: header, w: w - sidebar, h: 800 - header });
  }
});

test('grid never gives a negative area', () => {
  const g = L.grid(10, 1);
  assert.equal(g.area.h, 0);
  assert.ok(g.area.w >= 0);
});

test('every opened page is a single page tab', () => {
  const s = two();
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller', 'a:talker']);
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:talker', null, null]);
  assert.equal(L.openTab(s, 'a', 'talker').tabs.length, 2);
});

test('dropping a tab on the right of a single page makes two pages: shown page left, dropped page right', () => {
  const s = L.dropKey(two(), 'a:controller', 'right');
  assert.equal(s.mode, 'cols');
  assert.deepEqual(L.shown(s), ['a:talker', 'a:controller']);
  assert.equal(s.focus, 1);
});

test('dropping on the shown page itself does nothing to a single page', () => {
  const s = two();
  assert.equal(L.dropKey(s, 'a:talker', 'right'), s);
});

test('dropping below two pages makes three, with the two on top kept', () => {
  const two2 = L.dropKey(three(), 'a:controller', 'right');
  const s = L.dropKey(two2, 'a:talker', 'below');
  assert.equal(s.mode, 'trio');
  assert.deepEqual(s.panes.slice(0, 2), two2.panes.slice(0, 2));
  assert.equal(s.panes[2], 'a:talker');
  assert.equal(new Set(s.panes).size, 3);
  assert.equal(s.focus, 2);
});

test('dropping below with a page that is already showing is refused', () => {
  const s = L.dropKey(two(), 'a:controller', 'right');
  assert.equal(L.dropKey(s, 'a:talker', 'below'), s);
});

test('dropping on a pane replaces it, or swaps when the page is already in another pane', () => {
  let s = split3();
  const before = [...s.panes];
  s = L.dropKey(s, before[2], 'pane0');
  assert.deepEqual(s.panes, [before[2], before[1], before[0]]);
  assert.equal(s.focus, 0);
  const t = L.addTab(split3(), 'b', 'controller');
  const u = L.dropKey(t, 'b:controller', 'pane1');
  assert.equal(u.panes[1], 'b:controller');
  assert.equal(u.mode, 'trio');
});

test('dropping on the pane the page is already in only moves focus', () => {
  const s = split3();
  const r = L.dropKey(s, s.panes[1], 'pane1');
  assert.deepEqual(r.panes, s.panes);
  assert.equal(r.focus, 1);
});

test('three pages are the most: a fourth place does not exist and unknown places are refused', () => {
  const s = split3();
  assert.deepEqual(L.zoneIds(s), ['pane0', 'pane1', 'pane2']);
  assert.deepEqual(L.zoneIds(L.dropKey(two(), 'a:controller', 'right')), ['pane0', 'pane1', 'below']);
  assert.deepEqual(L.zoneIds(two()), ['pane0', 'right']);
  assert.equal(L.dropKey(s, 'a:controller', 'right'), s);
  assert.equal(L.dropKey(s, 'a:controller', 'pane3'), s);
  assert.equal(L.dropKey(s, 'nope', 'pane0'), s);
});

test('clicking a tab inside the split shows the whole split and focuses that pane', () => {
  let s = split3();
  const keys = [...s.panes];
  s = L.showAlone(s, 'a:talker' === keys[0] ? keys[1] : keys[0]);
  assert.equal(s.mode, 'single');
  s = L.openKey(s, keys[2]);
  assert.equal(s.mode, 'trio');
  assert.deepEqual(s.panes, keys);
  assert.equal(s.focus, 2);
});

test('clicking a tab that is not in the split shows it alone and keeps the split to come back to', () => {
  let s = L.openTab(split3(), 'b', 'nodemon');
  s = L.openKey(s, 'b:nodemon');
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['b:nodemon', null, null]);
  assert.equal(L.canBack(s), true);
  const back = L.backToSplit(s);
  assert.equal(back.mode, 'trio');
  assert.equal(L.canBack(back), false);
  assert.equal(L.canBack(L.emptyState()), false);
  assert.equal(L.backToSplit(back), back);
});

test('clicking a tab that is already shown only moves focus', () => {
  const s = split3();
  const r = L.openKey(s, s.panes[1]);
  assert.equal(r.focus, 1);
  assert.equal(r.mode, 'trio');
  assert.deepEqual(r.panes, s.panes);
});

test('Last Heard opens as its own single page and Back to split returns', () => {
  const s0 = split3();
  const s = L.openLastHeard(s0, 'a', 'https://lh.example/x');
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['lh', null, null]);
  assert.equal(s.tabs.find((t) => t.key === 'lh').url, 'https://lh.example/x');
  assert.equal(L.canBack(s), true);
  assert.deepEqual(L.backToSplit(s).panes, s0.panes);
});

test('a second Last Heard click reuses the tab and takes the new address', () => {
  let s = L.openLastHeard(split3(), 'a', 'https://lh.example/1');
  s = L.openLastHeard(s, 'a', 'https://lh.example/2');
  assert.equal(s.tabs.filter((t) => t.key === 'lh').length, 1);
  assert.equal(s.tabs.find((t) => t.key === 'lh').url, 'https://lh.example/2');
  assert.equal(s.mode, 'single');
});

test('Last Heard can be stacked into a split like any tab', () => {
  let s = L.openLastHeard(two(), 'a', 'https://lh.example/x');
  s = L.dropKey(s, 'a:talker', 'right');
  assert.deepEqual(L.shown(s), ['lh', 'a:talker']);
  s = L.dropKey(L.addTab(s, 'a', 'sysmon'), 'a:sysmon', 'below');
  assert.equal(s.mode, 'trio');
  assert.equal(s.panes[2], 'a:sysmon');
});

test('closing the Last Heard page returns to the split', () => {
  const s0 = split3();
  const s = L.closeTab(L.openLastHeard(s0, 'a', 'https://lh.example/x'), 'lh');
  assert.equal(s.mode, 'trio');
  assert.deepEqual(s.panes, s0.panes);
});

test('closing a shown tab in a split compacts it, and a pair becomes a single page', () => {
  let s = L.closeTab(split3(), split3().panes[1]);
  assert.equal(s.mode, 'cols');
  assert.equal(s.panes.filter(Boolean).length, 2);
  s = L.closeTab(s, s.panes[0]);
  assert.equal(s.mode, 'single');
  assert.equal(s.panes.filter(Boolean).length, 1);
});

test('closing a tab that is only in the saved split shrinks the split to come back to', () => {
  let s = L.openTab(split3(), 'b', 'nodemon');
  s = L.openKey(s, 'b:nodemon');
  s = L.closeTab(s, split3().panes[2]);
  const back = L.backToSplit(s);
  assert.equal(back.mode, 'cols');
  const gone = L.closeTab(s, split3().panes[1]);
  assert.equal(L.canBack(gone), false);
});

test('closing the last tab empties everything', () => {
  const s = L.closeTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a:controller');
  assert.deepEqual(s, { tabs: [], panes: [null, null, null], mode: 'single', saved: null, ratio: 0.5, focus: 0 });
});

test('closing a node closes all its tabs, Last Heard from it included', () => {
  let s = L.openTab(L.openLastHeard(two(), 'a', 'https://lh.example/x'), 'b', 'talker');
  s = L.closeNode(s, 'a');
  assert.deepEqual(s.tabs.map((t) => t.key), ['b:talker']);
  assert.deepEqual(s.panes, ['b:talker', null, null]);
});

test('removing a pane shrinks the split and the last pair becomes one page', () => {
  let s = L.removePane(split3(), 2);
  assert.equal(s.mode, 'cols');
  s = L.removePane(s, 0);
  assert.equal(s.mode, 'single');
  assert.equal(L.removePane(s, 0), s);
  assert.equal(L.removePane(split3(), 5).mode, 'trio');
});

test('1 page keeps the focused tab and the split to come back to; 2 and 3 pages restore a matching split', () => {
  let s = split3();
  const keys = [...s.panes];
  s = L.focusPane(s, 1);
  s = L.setMode(s, 'single');
  assert.deepEqual(s.panes, [keys[1], null, null]);
  s = L.setMode(s, 'trio');
  assert.deepEqual(s.panes, keys);
  assert.equal(s.focus, 1);
});

test('a mode needs as many tabs as panes', () => {
  const one = L.openTab(L.emptyState(), 'a', 'controller');
  assert.equal(L.setMode(one, 'cols'), one);
  assert.equal(L.setMode(one, 'trio'), one);
  assert.equal(L.setMode(two(), 'trio').mode, 'single');
  assert.equal(L.setMode(two(), 'cols').mode, 'cols');
  assert.equal(L.setMode(three(), 'trio').mode, 'trio');
  assert.equal(L.setMode(two(), 'rows').mode, 'single');
});

test('2 pages from one page uses the first tabs in tab order and focuses the page you were on', () => {
  const s = L.setMode(two(), 'cols');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:talker']);
  assert.equal(s.focus, 1);
  const t = L.setMode(three(), 'trio');
  assert.deepEqual(t.panes, ['a:controller', 'a:talker', 'a:sysmon']);
  assert.equal(t.focus, 2);
});

test('3 pages to 2 keeps the focused page, 2 to 3 adds another tab below', () => {
  let s = L.focusPane(L.setMode(three(), 'trio'), 2);
  s = L.setMode(s, 'cols');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:sysmon']);
  assert.equal(s.focus, 1);
  const c = L.setMode(L.addTab(L.setMode(two(), 'cols'), 'b', 'talker'), 'trio');
  assert.equal(c.mode, 'trio');
  assert.deepEqual(c.panes, ['a:controller', 'a:talker', 'b:talker']);
});

test('Ctrl+click adds a page to the next free place: right, then below, then the bottom', () => {
  let s = L.openTab(L.openTab(L.openTab(L.openTab(L.emptyState(), 'a', 'controller'), 'a', 'talker'), 'a', 'sysmon'), 'a', 'nodemon');
  s = L.showAlone(s, 'a:controller');
  s = L.addNext(s, 'a:talker');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:talker']);
  s = L.addNext(s, 'a:sysmon');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:talker', 'a:sysmon']);
  s = L.addNext(s, 'a:nodemon');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:talker', 'a:nodemon']);
  const f = L.addNext(s, 'a:controller');
  assert.equal(f.focus, 0);
});

test('applyArrangement sets a split of the right size from existing tabs only', () => {
  const s = three();
  const a = L.applyArrangement(s, 'trio', ['a:sysmon', 'a:talker', 'a:controller'], 0.3);
  assert.deepEqual(a.panes, ['a:sysmon', 'a:talker', 'a:controller']);
  assert.equal(a.ratio, 0.3);
  assert.equal(L.applyArrangement(s, 'cols', ['a:sysmon'], 0.5), s);
  assert.equal(L.applyArrangement(s, 'cols', ['a:sysmon', 'a:sysmon'], 0.5), s);
  assert.equal(L.applyArrangement(s, 'cols', ['a:sysmon', 'b:talker'], 0.5), s);
  assert.equal(L.applyArrangement(s, 'single', ['a:sysmon'], 0.5), s);
});

test('ratio is kept between 0.1 and 0.9 and ignores junk', () => {
  const s = L.emptyState();
  assert.equal(L.setRatio(s, 5).ratio, 0.9);
  assert.equal(L.setRatio(s, -1).ratio, 0.1);
  assert.equal(L.setRatio(s, 'x'), s);
});

test('focusPane stays within the shown panes and never lands on an empty one', () => {
  assert.equal(L.focusPane(two(), 1).focus, 0);
  const s = split3();
  assert.equal(L.focusPane(s, 2).focus, 2);
  assert.equal(L.focusPane(s, 'x'), s);
  assert.equal(L.focusPane(s, -1), s);
  const c = L.dropKey(two(), 'a:controller', 'right');
  assert.equal(L.focusPane(c, 2), c);
});

test('rects: one page fills the area, two pages are 6 and 6 at 1280 wide', () => {
  assert.deepEqual(L.rects({ mode: 'single' }, AREA), { panes: [AREA], dividers: [] });
  const r = L.rects({ mode: 'cols', ratio: 0.5 }, AREA);
  assert.equal(r.panes[0].w + L.GAP + r.panes[1].w, 1024);
  assert.equal(r.panes[0].w, 509);
  assert.equal(r.panes[1].x, r.panes[0].x + r.panes[0].w + L.GAP);
  assert.deepEqual(r.dividers, [{ rect: { x: 256 + 509, y: 85, w: L.GAP, h: 715 }, axis: 'x', drag: true }]);
});

test('rects: three pages are two over one with equal rows', () => {
  const r = L.rects({ mode: 'trio', ratio: 0.5 }, AREA);
  const [a, b, c] = r.panes;
  assert.equal(a.y, b.y);
  assert.equal(a.h, b.h);
  assert.deepEqual([c.x, c.w], [AREA.x, AREA.w]);
  assert.equal(c.y, a.y + a.h + L.GAP);
  assert.ok(Math.abs(c.h - a.h) <= 1);
  assert.equal(a.h + L.GAP + c.h, AREA.h);
  assert.deepEqual(r.dividers.map((d) => [d.axis, d.drag]), [['x', true], ['y', false]]);
});

test('rects: the ratio moves only the top row, and a pane keeps its minimum width', () => {
  const r = L.rects({ mode: 'trio', ratio: 0.3 }, AREA);
  assert.ok(r.panes[0].w < r.panes[1].w);
  assert.equal(r.panes[2].w, AREA.w);
  const area = { x: 0, y: 0, w: 1000, h: 700 };
  for (const mode of ['cols', 'trio']) {
    assert.ok(L.rects({ mode, ratio: 0.1 }, area).panes[0].w >= L.MIN_PANE);
    assert.ok(L.rects({ mode, ratio: 0.95 }, area).panes[1].w >= L.MIN_PANE);
  }
});

test('viewRect leaves a strip above each pane of a split but none for one page', () => {
  const r = { x: 10, y: 20, w: 300, h: 400 };
  assert.deepEqual(L.viewRect({ mode: 'single' }, r), r);
  assert.deepEqual(L.viewRect({ mode: 'cols' }, r), { x: 10, y: 20 + L.STRIP, w: 300, h: 400 - L.STRIP });
  assert.equal(L.viewRect({ mode: 'trio' }, { x: 0, y: 0, w: 5, h: 10 }).h, 0);
});

test('drop zones: halves for one page, top two thirds and a bottom third for two, the panes for three', () => {
  const s1 = L.dropZones(two(), AREA);
  assert.deepEqual(s1.map((z) => z.id), ['pane0', 'right']);
  assert.equal(s1[0].rect.w + s1[1].rect.w, AREA.w);
  assert.equal(s1[1].rect.x, s1[0].rect.x + s1[0].rect.w);
  const s2 = L.dropZones(L.dropKey(two(), 'a:controller', 'right'), AREA);
  assert.deepEqual(s2.map((z) => z.id), ['pane0', 'pane1', 'below']);
  assert.equal(s2[2].rect.w, AREA.w);
  assert.equal(s2[2].rect.y + s2[2].rect.h, AREA.y + AREA.h);
  assert.ok(Math.abs(s2[2].rect.h - AREA.h / 3) <= 1);
  assert.equal(s2[0].rect.h + s2[2].rect.h, AREA.h);
  const s3 = L.dropZones(split3(), AREA);
  assert.deepEqual(s3.map((z) => z.id), ['pane0', 'pane1', 'pane2']);
  assert.deepEqual(s3.map((z) => z.id), L.zoneIds(split3()));
  assert.deepEqual(s3.map((z) => z.rect), L.rects(split3(), AREA).panes);
});

test('serialize then restore gives the same layout and split to come back to', () => {
  let s = L.setRatio(split3(), 0.3);
  s = L.openTab(s, 'b', 'nodemon');
  s = L.openKey(s, 'b:nodemon');
  const back = L.restore(JSON.parse(JSON.stringify(L.serialize(s))), NODES, PAGES);
  assert.deepEqual(back.tabs, s.tabs);
  assert.deepEqual([back.panes, back.mode, back.ratio, back.focus, back.saved], [s.panes, s.mode, s.ratio, s.focus, s.saved]);
});

test('Last Heard is not saved, and a split that held it shrinks', () => {
  let s = L.dropKey(L.openLastHeard(two(), 'a', 'https://lh.example/x'), 'a:talker', 'right');
  s = L.dropKey(L.addTab(s, 'a', 'sysmon'), 'a:sysmon', 'below');
  const saved = L.serialize(s);
  assert.equal(saved.tabs.some((t) => t.pageId === 'lasthard'), false);
  assert.equal(JSON.stringify(saved).includes('"lh"'), false);
  const back = L.restore(JSON.parse(JSON.stringify(saved)), NODES, PAGES);
  assert.equal(back.tabs.some((t) => t.key === 'lh'), false);
  assert.equal(back.mode, 'cols');
});

test('restore drops tabs for missing nodes or pages and repairs the panes', () => {
  const saved = {
    tabs: [{ nodeId: 'a', pageId: 'controller' }, { nodeId: 'gone', pageId: 'talker' }, { nodeId: 'a', pageId: 'nope' }, { nodeId: 'a', pageId: 'controller' }],
    panes: ['gone:talker', 'a:controller', null],
    mode: 'trio',
    saved: { mode: 'trio', panes: ['a:controller', 'gone:talker', null] },
    ratio: 7,
    focus: 2,
  };
  const s = L.restore(saved, NODES, PAGES);
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.equal(s.mode, 'single');
  assert.deepEqual(s.panes, ['a:controller', null, null]);
  assert.equal(s.saved, null);
  assert.equal(s.ratio, 0.9);
  assert.equal(s.focus, 0);
});

test('restore of junk gives an empty layout', () => {
  assert.deepEqual(L.restore(null, NODES, PAGES), L.emptyState());
  assert.deepEqual(L.restore({ tabs: 5 }, NODES, PAGES), L.emptyState());
  const s = L.restore({ tabs: [{ nodeId: 'a', pageId: 'controller' }], saved: 7, panes: 'x', mode: 'weird' }, NODES, PAGES);
  assert.equal(s.mode, 'single');
});
